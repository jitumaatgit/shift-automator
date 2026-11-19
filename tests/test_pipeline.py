from datetime import datetime
from dataclasses import replace
from unittest.mock import MagicMock
import time

from models import ParsedOffer, PipelineResult, ActionKind, ScoredOffer, ShiftDecision
from parser import parse_confirmation, classify_incoming
from config import load_config, Config
from calendar_client import CalendarClient
from responder import SMSConfig, create_responder, init_logging
from pipeline import process_offer, _execute_accept, _execute_decline, _native_claim_already_sent
from rules import RuleAction


def _dummy_calendar() -> CalendarClient:
    cal = CalendarClient(dry_run=True, cache_ttl_seconds=-1)
    cal._service = MagicMock()
    cal._authed = True
    return cal


def _dummy_responder():
    return create_responder(SMSConfig(dry_run=True, sms_transport="stub"))


class TestPipelineRouting:
    def test_classify_offer_routes_to_offer_kind(self):
        config = load_config()
        text = "Open shift available at [Special Projects] Special Projects starting at Fri 15/May 9:00am - 05:00pm Code: 1790228"
        result = process_offer(text, config, _dummy_calendar(), _dummy_responder())
        assert result.kind == "offer"
        assert result.parsed is not None
        assert result.scored is not None

    def test_classify_confirmation_routes_to_confirmation_kind(self):
        config = load_config()
        text = "Congratulations! You are now booked for [Special Projects] Friday 5/15 9am-5pm. Code 1790228."
        result = process_offer(text, config, _dummy_calendar(), _dummy_responder())
        assert result.kind == "confirmation"

    def test_classify_rejection_routes_to_rejection_kind(self):
        config = load_config()
        text = "We're sorry, the shift you selected has already been taken. Please try again."
        result = process_offer(text, config, _dummy_calendar(), _dummy_responder())
        assert result.kind == "rejection"
        assert result.raw_preview is not None

    def test_pipeline_result_has_correct_fields(self):
        config = load_config()
        text = "Open shift available at [Special Projects] Special Projects starting at Fri 15/May 9:00am - 05:00pm Code: 1790228"
        result = process_offer(text, config, _dummy_calendar(), _dummy_responder())

        assert result.kind == "offer"
        assert result.parsed.title == "Special Projects"
        assert result.scored.score is not None
        assert len(result.actions) >= 2
        assert result.elapsed_ms > 0
        assert result.dry_run == config.dry_run

    def test_pipeline_actions_include_parse_and_decision(self):
        config = load_config()
        text = "Open shift available at [Special Projects] Special Projects starting at Fri 15/May 9:00am - 05:00pm Code: 1790228"
        result = process_offer(text, config, _dummy_calendar(), _dummy_responder())

        assert any(a.kind == ActionKind.PARSE for a in result.actions)
        assert any(a.kind == ActionKind.DECISION for a in result.actions)


class TestShiftKey:
    def test_shift_key_is_deterministic(self):
        offer1 = ParsedOffer(
            raw_text="test",
            building="Special Projects",
            title="Test Shift",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
            claim_code="1234567",
        )
        offer2 = ParsedOffer(
            raw_text="different text",
            building="Special Projects",
            title="Test Shift",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
            claim_code="7654321",
        )
        assert offer1.shift_key == offer2.shift_key

    def test_shift_key_differs_by_building(self):
        a = ParsedOffer(
            raw_text="test",
            building="Special Projects",
            title="Test Shift",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
        )
        b = ParsedOffer(
            raw_text="test",
            building="TCC",
            title="Test Shift",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
        )
        assert a.shift_key != b.shift_key

    def test_shift_key_differs_by_title(self):
        a = ParsedOffer(
            raw_text="test",
            building="Special Projects",
            title="Front Desk",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
        )
        b = ParsedOffer(
            raw_text="test",
            building="Special Projects",
            title="Janitorial",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
        )
        assert a.shift_key != b.shift_key


def _offer(code: str = "1867694") -> ParsedOffer:
    return ParsedOffer(
        raw_text="test",
        building="Special Projects",
        title="Test Shift",
        start_time=datetime(2026, 5, 15, 9, 0),
        end_time=datetime(2026, 5, 15, 17, 0),
        claim_code=code,
    )


def _write_marker(tmp_path, code: str, ts: float) -> str:
    path = tmp_path / "shift_claim_sent.txt"
    path.write_text(f"{code} {int(ts)}")
    return str(path)


class TestClaimsMarker:
    def test_fresh_matching_code_is_within_ttl(self, tmp_path, monkeypatch):
        now = time.time()
        marker = _write_marker(tmp_path, "2027694", now)
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", marker)
        assert _native_claim_already_sent("2027694", now=now) is True

    def test_stale_timestamp_over_ttl_is_not_claimed(self, tmp_path, monkeypatch):
        now = time.time()
        marker = _write_marker(tmp_path, "2027694", now - 400)
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", marker)
        assert _native_claim_already_sent("2027694", now=now) is False

    def test_different_code_is_not_claimed(self, tmp_path, monkeypatch):
        now = time.time()
        marker = _write_marker(tmp_path, "1111111", now)
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", marker)
        assert _native_claim_already_sent("2027694", now=now) is False

    def test_missing_file_is_not_claimed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", str(tmp_path / "nope.txt"))
        assert _native_claim_already_sent("2027694", now=time.time()) is False

    def test_malformed_content_is_not_claimed(self, tmp_path, monkeypatch):
        path = tmp_path / "shift_claim_sent.txt"
        path.write_text("garbage-not-two-fields")
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", str(path))
        assert _native_claim_already_sent("2027694", now=time.time()) is False


class TestSingleClaimerAccept:
    def _config_and_responder(self):
        config = replace(load_config(), dry_run=False)
        responder = _dummy_responder()
        responder.send_accept = MagicMock()
        return config, responder

    def test_fresh_marker_skips_and_never_sends_accept(self, tmp_path, monkeypatch):
        now = time.time()
        scored = ScoredOffer(offer=_offer(), decision=ShiftDecision.AUTO_ACCEPT, score=100.0)
        marker = _write_marker(tmp_path, scored.offer.claim_code, now)
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", marker)
        config, responder = self._config_and_responder()

        actions = _execute_accept(scored, config, responder)

        assert any(a.kind == ActionKind.SKIPPED and "claim already sent by Tasker" in a.detail for a in actions)
        responder.send_accept.assert_not_called()

    def test_missing_marker_warns_but_never_sends_accept(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", str(tmp_path / "missing.txt"))
        config, responder = self._config_and_responder()
        scored = ScoredOffer(offer=_offer(), decision=ShiftDecision.AUTO_ACCEPT, score=100.0)

        actions = _execute_accept(scored, config, responder)

        assert any(a.kind == ActionKind.WARNING and "no claim marker" in a.detail for a in actions)
        responder.send_accept.assert_not_called()


class TestSingleClaimerDecline:
    def test_claimed_but_decline_warns_to_cancel(self, tmp_path, monkeypatch):
        now = time.time()
        scored = ScoredOffer(offer=_offer(), decision=ShiftDecision.AUTO_DECLINE, score=-100.0)
        marker = _write_marker(tmp_path, scored.offer.claim_code, now)
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", marker)
        config = replace(load_config(), dry_run=False)
        responder = _dummy_responder()
        responder.send_decline_push = MagicMock()

        actions = _execute_decline(scored, config, responder)

        assert any(a.kind == ActionKind.WARNING and "call dispatch to cancel" in a.detail for a in actions)
        assert any(a.kind == ActionKind.PUSH_SENT for a in actions)
        responder.send_decline_push.assert_called_once_with(scored, claimed=True)

    def test_unclaimed_decline_has_no_cancel_warning(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHIFT_AUTOMATOR_CLAIM_MARKER", str(tmp_path / "missing.txt"))
        scored = ScoredOffer(offer=_offer(), decision=ShiftDecision.AUTO_DECLINE, score=-100.0)
        config = replace(load_config(), dry_run=False)
        responder = _dummy_responder()
        responder.send_decline_push = MagicMock()

        actions = _execute_decline(scored, config, responder)

        assert not any(a.kind == ActionKind.WARNING for a in actions)
        assert any(a.kind == ActionKind.PUSH_SENT for a in actions)
        responder.send_decline_push.assert_called_once_with(scored, claimed=False)
