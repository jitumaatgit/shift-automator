"""
Test the rules engine against known scenarios.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import patch

from models import ParsedOffer, ShiftDecision, ShiftContext
from rules import RulesEngine
from config import load_config
from calendar_client import FakeCalendar


def make_context(
    timezone: str = "America/Los_Angeles",
    day_hours: float = 0.0,
    prev_day_hours: float = 0.0,
    prev_day_last_end: Optional[datetime] = None,
    adjacent_events: Optional[list] = None,
    weekly_hours: float = 0.0,
    conflicts: Optional[dict] = None,
) -> ShiftContext:
    return ShiftContext(
        timezone=timezone,
        day_hours=day_hours,
        prev_day_hours=prev_day_hours,
        prev_day_last_end=prev_day_last_end,
        adjacent_events=adjacent_events or [],
        weekly_hours=weekly_hours,
        conflicts=conflicts,
    )


class TestRulesEngine:
    def _make_offer(self, building="Special Projects", title="Test Shift", start_hour=9, duration=8, address="Test Location", shift_note="Test note") -> ParsedOffer:
        start = datetime(2026, 5, 15, start_hour, 0)
        end = start + timedelta(hours=duration)
        return ParsedOffer(
            raw_text="test",
            building=building,
            title=title,
            start_time=start,
            end_time=end,
            shift_note=shift_note,
            address=address,
            claim_code="1234567",
        )

    def test_clean_offer_auto_accept(self):
        config = replace(
            load_config(),
            location_preferences={"liked": ["Test Location"], "disliked": []},
            shift_type_preferences={"Special Projects": 2.0},
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=9, duration=8, address="Test Location")
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert scored.score >= 0.0

    def test_undesired_time_decline(self):
        config = replace(
            load_config(),
            undesired_hours=((0, 5),),
            undesired_time_penalty=5.0,
            auto_decline_threshold=-5.0,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=2, duration=3)
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE

    def test_overtime_veto(self):
        config = replace(
            load_config(),
            active_rules=("calendar_conflict", "location_preference", "shift_type_preference", "title_preference", "time_of_day", "rest_gap_sleep", "weekly_hours_cap"),
        )

        engine = RulesEngine(config)
        offer = self._make_offer(duration=4)
        ctx = make_context(weekly_hours=38.0)
        scored = engine.evaluate(offer, context=ctx)

        assert scored.decision == ShiftDecision.AUTO_DECLINE

    def test_overtime_approved_auto_accept(self):
        config = replace(
            load_config(),
            active_rules=("calendar_conflict", "location_preference", "shift_type_preference", "title_preference", "time_of_day", "rest_gap_sleep", "weekly_hours_cap"),
        )

        engine = RulesEngine(config)
        offer = self._make_offer(duration=4, shift_note="Overtime Approved")
        ctx = make_context(weekly_hours=38.0)
        scored = engine.evaluate(offer, context=ctx)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert any("Overtime shift (approved)" in r for r in scored.reasons)

    def test_location_disliked_decline(self):
        config = replace(
            load_config(),
            location_preferences={"liked": [], "disliked": ["Bad Building"]},
            location_disliked_penalty=6.0,
            auto_decline_threshold=-5.0,
            preferred_hours=(),
        )

        engine = RulesEngine(config)
        offer = self._make_offer(address="Bad Building - 123 Main St")
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE

    def test_title_preference_fd(self):
        config = replace(
            load_config(),
            title_preferences={"FD": 3.0},
            shift_type_preferences={"Estate": 1.0},
        )

        engine = RulesEngine(config)
        offer = self._make_offer(
            building="Estate",
            title="FD",
            start_hour=9,
            duration=8,
            address="225 NW Test Ct",
        )
        scored = engine.evaluate(offer)

        assert scored.score >= 3.0, f"Expected >=3.0, got {scored.score}"
        assert any("title_preference" in r for r in scored.reasons)
        assert any("FD" in r for r in scored.reasons)

    def test_title_preference_keyword_match(self):
        config = replace(
            load_config(),
            title_preferences={},
            title_keywords={"Janitorial": 2.0},
        )

        engine = RulesEngine(config)
        offer = self._make_offer(
            building="Estate",
            title="J1 Janitorial",
            start_hour=9,
            duration=8,
        )
        scored = engine.evaluate(offer)

        assert any("Janitorial" in r for r in scored.reasons)

    def test_location_preference_falls_back_to_building_name(self):
        config = replace(
            load_config(),
            location_preferences={"liked": ["Estate"], "disliked": []},
        )

        engine = RulesEngine(config)
        offer = self._make_offer(
            building="Estate",
            title="FD",
            start_hour=9,
            duration=8,
            address="",
        )
        scored = engine.evaluate(offer)

        assert any("Liked location: Estate" in r for r in scored.reasons)

    def test_veto_undesired_hours_blocks_overnight(self):
        config = replace(
            load_config(),
            undesired_hours=((22, 24), (0, 5)),
            shift_type_preferences={"Special Projects": 5.0},
            location_preferences={"liked": ["Test Location"], "disliked": []},
            veto_undesired_hours=True,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=23, duration=8)
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert any("VETO-DECLINE" in r and "time_of_day" in r for r in scored.reasons)

    def test_veto_undesired_hours_off_only_penalizes(self):
        config = replace(
            load_config(),
            undesired_hours=((22, 24),),
            undesired_time_penalty=6.0,
            auto_decline_threshold=-5.0,
            preferred_hours=(),
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=23, duration=8)
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert not any("VETO-DECLINE" in r for r in scored.reasons)
        assert any("undesired window" in r for r in scored.reasons)

    def test_binary_threshold_boundary(self):
        config = replace(
            load_config(),
            auto_decline_threshold=-5.0,
            shift_type_preferences={"Special Projects": -4.9},
        )

        engine = RulesEngine(config)
        offer = self._make_offer()
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert scored.score > -5.0

    def test_binary_threshold_at_floor_declines(self):
        config = replace(
            load_config(),
            auto_decline_threshold=-5.0,
            shift_type_preferences={"Special Projects": -6.0},
            preferred_hours=(),
        )

        engine = RulesEngine(config)
        offer = self._make_offer()
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert scored.score <= -5.0

    # -----------------------------------------------------------------------
    # Wakefulness gate
    # -----------------------------------------------------------------------

    def test_wakefulness_gate_blocks_early_morning(self):
        config = replace(
            load_config(),
            wakefulness_gate_start=0,
            wakefulness_gate_end=6,
            wakefulness_gate_current=5,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=4, duration=4)

        with patch("rules.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 3, 0)
            scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert any("VETO-DECLINE" in r and "wakefulness_gate" in r for r in scored.reasons)

    def test_wakefulness_gate_passes_when_awake(self):
        config = replace(
            load_config(),
            wakefulness_gate_start=0,
            wakefulness_gate_end=6,
            wakefulness_gate_current=5,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=4, duration=4)

        with patch("rules.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 7, 0)
            scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert not any("VETO-DECLINE" in r and "wakefulness_gate" in r for r in scored.reasons)

    # -----------------------------------------------------------------------
    # Day hours cap
    # -----------------------------------------------------------------------

    def test_day_hours_cap_veto(self):
        config = replace(
            load_config(),
            day_hours_cap=16.0,
            active_rules=("wakefulness_gate", "calendar_conflict", "day_hours_cap", "post_cap_break", "rest_gap_sleep", "location_preference", "shift_type_preference", "title_preference", "time_of_day"),
        )

        engine = RulesEngine(config, calendar=FakeCalendar(events_between=[
            {"summary": "[CC] Morning", "start": {"dateTime": "2026-05-15T08:00:00"}, "end": {"dateTime": "2026-05-15T16:00:00"}},
            {"summary": "[CC] Afternoon", "start": {"dateTime": "2026-05-15T17:00:00"}, "end": {"dateTime": "2026-05-15T23:30:00"}},
            {"summary": "[CC] Extra", "start": {"dateTime": "2026-05-15T06:00:00"}, "end": {"dateTime": "2026-05-15T08:00:00"}},
        ]))
        offer = self._make_offer(start_hour=9, duration=4)
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert any("VETO-DECLINE" in r and "day_hours_cap" in r for r in scored.reasons)

    def test_day_hours_cap_passes(self):
        config = replace(
            load_config(),
            day_hours_cap=16.0,
            active_rules=("wakefulness_gate", "calendar_conflict", "day_hours_cap", "post_cap_break", "rest_gap_sleep", "location_preference", "shift_type_preference", "title_preference", "time_of_day"),
        )

        engine = RulesEngine(config, calendar=FakeCalendar(events_between=[
            {"summary": "[CC] Morning", "start": {"dateTime": "2026-05-15T08:00:00"}, "end": {"dateTime": "2026-05-15T16:00:00"}},
        ]))
        offer = self._make_offer(start_hour=9, duration=4)
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert not any("VETO-DECLINE" in r and "day_hours_cap" in r for r in scored.reasons)

    # -----------------------------------------------------------------------
    # Post-cap break
    # -----------------------------------------------------------------------

    def test_post_cap_break_veto(self):
        config = replace(
            load_config(),
            day_hours_cap=16.0,
            post_cap_break_hours=8.0,
            active_rules=("wakefulness_gate", "calendar_conflict", "day_hours_cap", "post_cap_break", "rest_gap_sleep", "location_preference", "shift_type_preference", "title_preference", "time_of_day"),
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=8, duration=4)
        ctx = make_context(prev_day_hours=16.0, prev_day_last_end=datetime(2026, 5, 15, 1, 0))
        scored = engine.evaluate(offer, context=ctx)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert any("VETO-DECLINE" in r and "post_cap_break" in r for r in scored.reasons)

    def test_post_cap_break_passes(self):
        config = replace(
            load_config(),
            day_hours_cap=16.0,
            post_cap_break_hours=8.0,
            active_rules=("wakefulness_gate", "calendar_conflict", "day_hours_cap", "post_cap_break", "rest_gap_sleep", "location_preference", "shift_type_preference", "title_preference", "time_of_day"),
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=9, duration=4)
        ctx = make_context(prev_day_hours=16.0, prev_day_last_end=datetime(2026, 5, 15, 1, 0))
        scored = engine.evaluate(offer, context=ctx)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert not any("VETO-DECLINE" in r and "post_cap_break" in r for r in scored.reasons)

    # -----------------------------------------------------------------------
    # Rest gap sleep
    # -----------------------------------------------------------------------

    def test_rest_gap_sleep_penalizes_short_gap_when_event_in_sleep(self):
        config = replace(
            load_config(),
            rest_gap_sleep_hours=7.0,
            rest_gap_penalty=-10.0,
            rest_gap_sleep_start=22,
            rest_gap_sleep_end=6,
            auto_decline_threshold=-5.0,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=9, duration=8)
        ctx = make_context(adjacent_events=[
            {"summary": "[CC] Night shift", "start": {"dateTime": "2026-05-14T22:00:00"}, "end": {"dateTime": "2026-05-15T06:00:00"}},
        ])
        scored = engine.evaluate(offer, context=ctx)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert any("rest_gap_sleep" in r for r in scored.reasons)

    def test_rest_gap_sleep_ok_when_neither_in_sleep(self):
        config = replace(
            load_config(),
            rest_gap_sleep_hours=7.0,
            rest_gap_penalty=-10.0,
            rest_gap_sleep_start=22,
            rest_gap_sleep_end=6,
            auto_decline_threshold=-5.0,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=9, duration=8)
        ctx = make_context(adjacent_events=[
            {"summary": "[CC] Day shift", "start": {"dateTime": "2026-05-15T07:00:00"}, "end": {"dateTime": "2026-05-15T08:00:00"}},
        ])
        scored = engine.evaluate(offer, context=ctx)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert any("Rest gap OK" in r for r in scored.reasons)

    def test_rest_gap_sleep_ok_with_sufficient_gap(self):
        config = replace(
            load_config(),
            rest_gap_sleep_hours=7.0,
            rest_gap_penalty=-10.0,
            rest_gap_sleep_start=22,
            rest_gap_sleep_end=6,
            auto_decline_threshold=-5.0,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=9, duration=8)
        ctx = make_context(adjacent_events=[
            {"summary": "[CC] Night shift", "start": {"dateTime": "2026-05-14T22:00:00"}, "end": {"dateTime": "2026-05-14T23:00:00"}},
        ])
        scored = engine.evaluate(offer, context=ctx)

        assert scored.decision == ShiftDecision.AUTO_ACCEPT
        assert any("Rest gap OK" in r for r in scored.reasons)

    def test_rest_gap_sleep_no_calendar_skips(self):
        config = replace(
            load_config(),
            rest_gap_sleep_hours=7.0,
            rest_gap_penalty=-10.0,
        )

        engine = RulesEngine(config, calendar=None)
        offer = self._make_offer(start_hour=9, duration=8)
        scored = engine.evaluate(offer)

        assert any("FLAG-rest_gap_sleep" in r for r in scored.reasons)

    # -----------------------------------------------------------------------
    # Overnight shift veto
    # -----------------------------------------------------------------------

    def test_overnight_shift_vetoes_late_end(self):
        config = replace(
            load_config(),
            overnight_veto_start_hour=0,
            overnight_veto_end_hour=6,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=20, duration=8)  # 8pm-4am, ends at 4am
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert any("VETO-DECLINE" in r and "overnight_shift" in r for r in scored.reasons)

    def test_overnight_shift_passes_day_end(self):
        config = replace(
            load_config(),
            overnight_veto_start_hour=0,
            overnight_veto_end_hour=6,
        )

        engine = RulesEngine(config)
        offer = self._make_offer(start_hour=9, duration=8)  # 9am-5pm
        scored = engine.evaluate(offer)

        assert not any("VETO-DECLINE" in r and "overnight_shift" in r for r in scored.reasons)
