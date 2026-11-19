import json
from datetime import datetime

from models import ParsedOffer, ShiftDecision, ScoredOffer, PipelineResult, Action, ActionKind
from main import _format_result


class TestFormatResult:
    def test_confirmation_json(self):
        parsed = ParsedOffer(
            raw_text="Congratulations! You are now booked for [Special Projects]...",
            building="Special Projects",
            title="Special Projects",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
        )
        result = PipelineResult(
            kind="confirmation",
            parsed=parsed,
            event_id="abc123",
            dry_run=True,
        )
        out = _format_result(result, json_mode=True)
        data = json.loads(out)
        assert data["handled"] == "confirmation"
        assert data["event_id"] == "abc123"
        assert data["title"] == "Special Projects"
        assert data["building"] == "Special Projects"

    def test_rejection_json(self):
        result = PipelineResult(
            kind="rejection",
            raw_preview="Sorry, already taken",
            dry_run=True,
        )
        out = _format_result(result, json_mode=True)
        data = json.loads(out)
        assert data["handled"] == "rejection"
        assert data["raw_preview"] == "Sorry, already taken"

    def test_offer_json_has_all_keys(self):
        parsed = ParsedOffer(
            raw_text="Open shift at [Special Projects]...",
            building="Special Projects",
            title="Special Projects",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
            claim_code="1790228",
            cancel_number="503-555-0109",
            address="Portland, OR",
            calendar_event_id="evt_abc",
        )
        scored = ScoredOffer(
            offer=parsed,
            score=-6.0,
            decision=ShiftDecision.AUTO_DECLINE,
            reasons=["reason 1", "reason 2"],
        )
        result = PipelineResult(
            kind="offer",
            parsed=parsed,
            scored=scored,
            actions=[Action(ActionKind.PARSE, "Special Projects (8.0h)"), Action(ActionKind.PUSH_SENT, "decline push")],
            elapsed_ms=1234.5,
            dry_run=False,
        )
        out = _format_result(result, json_mode=True)
        data = json.loads(out)

        assert data["decision"] == "auto_decline"
        assert data["score"] == -6.0
        assert data["elapsed_ms"] == 1234.5
        assert data["title"] == "Special Projects"
        assert data["category"] == "Special Projects"
        assert data["start_time"] == "2026-05-15T09:00:00"
        assert data["end_time"] == "2026-05-15T17:00:00"
        assert data["duration_hours"] == 8.0
        assert data["claim_code"] == "1790228"
        assert data["cancel_number"] == "503-555-0109"
        assert data["calendar_event_id"] == "evt_abc"
        assert data["address"] == "Portland, OR"
        assert data["reasons"] == ["reason 1", "reason 2"]
        assert data["actions"] == [{"kind": "parse", "detail": "Special Projects (8.0h)"}, {"kind": "push_sent", "detail": "decline push"}]
        assert data["dry_run"] is False

    def test_stdout_offer_includes_decision(self):
        parsed = ParsedOffer(
            raw_text="test",
            building="Special Projects",
            title="Test Shift",
            start_time=datetime(2026, 5, 15, 9, 0),
            end_time=datetime(2026, 5, 15, 17, 0),
            claim_code="123",
            address="123 Main St",
        )
        scored = ScoredOffer(
            offer=parsed,
            score=5.0,
            decision=ShiftDecision.AUTO_ACCEPT,
            reasons=["r1"],
        )
        result = PipelineResult(
            kind="offer",
            parsed=parsed,
            scored=scored,
            actions=[Action(ActionKind.PARSE, "Test Shift (8.0h)")],
            elapsed_ms=500.0,
        )
        out = _format_result(result, json_mode=False)
        assert "DECISION: AUTO_ACCEPT" in out
        assert "Score: 5.0" in out
        assert "Test Shift" in out
        assert "123 Main St" in out

    def test_stdout_confirmation_includes_handled(self):
        parsed = ParsedOffer(
            raw_text="congrats",
            building="Special Projects",
            title="Booked Shift",
        )
        result = PipelineResult(
            kind="confirmation",
            parsed=parsed,
            event_id="evt_123",
        )
        out = _format_result(result, json_mode=False)
        assert "HANDLED: confirmation" in out
        assert "Booked Shift" in out
        assert "event_id: evt_123" in out

    def test_json_parsed_failure_has_null_dates(self):
        parsed = ParsedOffer(
            raw_text="garbage text",
            building="Unknown",
            title="",
        )
        scored = ScoredOffer(
            offer=parsed,
            score=0.0,
            decision=ShiftDecision.AUTO_DECLINE,
            reasons=[],
        )
        result = PipelineResult(
            kind="offer",
            parsed=parsed,
            scored=scored,
            actions=[],
            elapsed_ms=0.0,
        )
        out = _format_result(result, json_mode=True)
        data = json.loads(out)
        assert data["start_time"] is None
        assert data["end_time"] is None
        assert data["duration_hours"] == 0.0
