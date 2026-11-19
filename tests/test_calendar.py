import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from calendar_client import CalendarClient, CalendarError, CC_EVENT_PREFIX, FakeCalendar, _filter_cc_events, _sum_cc_hours, compute_shift_context
from models import ParsedOffer, ShiftDecision, ShiftContext
from rules import RulesEngine, RuleAction
from config import load_config


def _make_offer(start_hour=9, duration=8, building="Special Projects") -> ParsedOffer:
    start = datetime(2026, 5, 15, start_hour, 0)
    end = datetime(2026, 5, 15, start_hour + duration, 0)
    return ParsedOffer(
        raw_text="test",
        building=building,
        title="Test Shift",
        start_time=start,
        end_time=end,
        shift_note="Test",
        address="Test Location",
        claim_code="1234567",
    )


def _mock_event(summary="Busy", start_str="2026-05-15T09:00:00", end_str="2026-05-15T17:00:00"):
    return {
        "summary": summary,
        "start": {"dateTime": start_str, "timeZone": "America/Los_Angeles"},
        "end": {"dateTime": end_str, "timeZone": "America/Los_Angeles"},
    }


class TestCalendarClientDryRun:

    def test_dry_run_get_events_returns_empty(self):
        client = CalendarClient(dry_run=True)
        events = client.get_events_between(datetime(2026, 5, 15), datetime(2026, 5, 16))
        assert events == []

    def test_dry_run_check_conflict_returns_none(self):
        client = CalendarClient(dry_run=True)
        offer = _make_offer()
        assert client.check_conflict(offer) is None

    def test_dry_run_add_event_returns_dry_run_id(self):
        client = CalendarClient(dry_run=True)
        offer = _make_offer()
        event_id = client.add_shift_event(offer)
        assert event_id == "dry-run-event-id"

    def test_dry_run_weekly_hours_returns_zero(self):
        client = CalendarClient(dry_run=True)
        assert client.get_weekly_hours() == 0.0

    def test_dry_run_delete_returns_true(self):
        client = CalendarClient(dry_run=True)
        assert client.delete_shift_event("any-id") is True


class TestCalendarClientRealAPI:

    def _make_client_with_mock_service(self, events_response=None):
        client = CalendarClient(dry_run=False, calendar_id="test@gmail.com")
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_list = MagicMock()

        if events_response is not None:
            mock_list.execute.return_value = events_response
        else:
            mock_list.execute.return_value = {"items": []}

        mock_events.list.return_value = mock_list
        mock_service.events.return_value = mock_events
        client._service = mock_service
        client._authed = True
        return client, mock_service

    def test_get_events_between_calls_api(self):
        events_data = {"items": [_mock_event()]}
        client, mock_svc = self._make_client_with_mock_service(events_data)

        events = client.get_events_between(datetime(2026, 5, 15), datetime(2026, 5, 16))
        assert len(events) == 1
        assert events[0]["summary"] == "Busy"

    def test_check_conflict_detects_overlap(self):
        overlapping = _mock_event(
            summary="Doctor Appointment",
            start_str="2026-05-15T08:30:00",
            end_str="2026-05-15T10:00:00",
        )
        client, _ = self._make_client_with_mock_service({"items": [overlapping]})

        offer = _make_offer(start_hour=9, duration=2)
        conflict = client.check_conflict(offer)
        assert conflict is not None
        assert conflict["summary"] == "Doctor Appointment"

    def test_check_conflict_no_overlap(self):
        non_overlapping = _mock_event(
            summary="Late Meeting",
            start_str="2026-05-15T18:00:00",
            end_str="2026-05-15T19:00:00",
        )
        client, _ = self._make_client_with_mock_service({"items": [non_overlapping]})

        offer = _make_offer(start_hour=9, duration=8)
        assert client.check_conflict(offer) is None

    def test_add_shift_event_calls_insert(self):
        client, mock_svc = self._make_client_with_mock_service()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = {"id": "real-event-id-123"}
        mock_svc.events().insert.return_value = mock_insert

        offer = _make_offer()
        event_id = client.add_shift_event(offer)
        assert event_id == "real-event-id-123"
        mock_svc.events().insert.assert_called_once()

    def test_delete_shift_event_calls_delete(self):
        client, mock_svc = self._make_client_with_mock_service()
        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_svc.events().delete.return_value = mock_delete

        assert client.delete_shift_event("event-123") is True

    def test_get_weekly_hours_sums_cc_events(self):
        cc_event = _mock_event(
            summary=f"{CC_EVENT_PREFIX} Special Projects",
            start_str="2026-05-15T08:00:00",
            end_str="2026-05-15T16:00:00",
        )
        personal_event = _mock_event(
            summary="Gym",
            start_str="2026-05-15T17:00:00",
            end_str="2026-05-15T18:00:00",
        )
        client, _ = self._make_client_with_mock_service({"items": [cc_event, personal_event]})

        week_start = datetime(2026, 5, 11)
        hours = client.get_weekly_hours(week_start=week_start)
        assert hours == 8.0

    def test_parse_event_dt_with_date_only(self):
        client = CalendarClient(dry_run=True)
        event = {"start": {"date": "2026-05-15"}, "end": {"date": "2026-05-16"}}
        dt = client._parse_event_dt(event, "start")
        assert dt == datetime(2026, 5, 15)


class TestCalendarCache:
    """Tests for cache invalidation behavior."""

    def test_invalidate_cache_deletes_file(self, tmp_path):
        cache_file = tmp_path / "calendar_cache.json"
        cache_file.write_text('{"events": []}')
        assert cache_file.exists()

        client = CalendarClient(dry_run=True, cache_file=str(cache_file))
        client.invalidate_cache()

        assert not cache_file.exists()

    def test_invalidate_cache_ignores_missing_file(self, tmp_path):
        cache_file = tmp_path / "calendar_cache.json"
        assert not cache_file.exists()

        client = CalendarClient(dry_run=True, cache_file=str(cache_file))
        client.invalidate_cache()  # should not raise

    def test_add_shift_event_invalidates_cache(self, tmp_path):
        cache_file = tmp_path / "calendar_cache.json"
        cache_file.write_text('{"events": []}')
        assert cache_file.exists()

        client = CalendarClient(dry_run=False, cache_file=str(cache_file))
        mock_svc = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = {"id": "real-event-id-123"}
        mock_svc.events().insert.return_value = mock_insert
        client._service = mock_svc
        client._authed = True

        offer = _make_offer()
        event_id = client.add_shift_event(offer)

        assert event_id == "real-event-id-123"
        assert not cache_file.exists()

    def test_delete_shift_event_invalidates_cache(self, tmp_path):
        cache_file = tmp_path / "calendar_cache.json"
        cache_file.write_text('{"events": []}')
        assert cache_file.exists()

        client = CalendarClient(dry_run=False, cache_file=str(cache_file))
        mock_svc = MagicMock()
        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_svc.events().delete.return_value = mock_delete
        client._service = mock_svc
        client._authed = True

        result = client.delete_shift_event("event-123")

        assert result is True
        assert not cache_file.exists()


    def test_refresh_cache_flag_exits_early(self):
        """--refresh-cache should initialize automator and exit without processing."""
        result = subprocess.run(
            [sys.executable, "src/main.py", "--refresh-cache"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "Calendar cache refreshed" in result.stderr

    def test_refresh_cache_skips_process_text(self):
        """--refresh-cache should not process text even when --text is provided."""
        result = subprocess.run(
            [sys.executable, "src/main.py", "--refresh-cache", "--text", "Open shift at [STS] ..."],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "Calendar cache refreshed" in result.stderr
        assert "DECISION" not in result.stdout


class TestRulesWithCalendar:

    def test_calendar_conflict_veto_with_real_client(self):
        config = load_config()

        client = CalendarClient(dry_run=False)
        mock_svc = MagicMock()
        mock_list = MagicMock()
        overlapping = _mock_event(
            summary="[CC] Existing Meeting",
            start_str="2026-05-15T09:00:00",
            end_str="2026-05-15T10:00:00",
        )
        mock_list.execute.return_value = {"items": [overlapping]}
        mock_svc.events().list.return_value = mock_list
        client._service = mock_svc

        engine = RulesEngine(config, calendar=client)
        offer = _make_offer(start_hour=9, duration=2)
        scored = engine.evaluate(offer)

        assert scored.decision == ShiftDecision.AUTO_DECLINE
        assert any("VETO-DECLINE" in r and "calendar_conflict" in r for r in scored.reasons)

    def test_calendar_conflict_no_veto_when_clear(self):
        config = load_config()

        engine = RulesEngine(config)
        offer = _make_offer(start_hour=9, duration=8)
        ctx = ShiftContext(timezone="America/Los_Angeles", conflicts=None)
        scored = engine.evaluate(offer, context=ctx)

        conflict_reason = [r for r in scored.reasons if "calendar_conflict" in r]
        assert len(conflict_reason) == 1
        assert "No calendar conflicts" in conflict_reason[0]

    def test_rest_gap_penalizes_short_gap(self):
        config = load_config()

        client = CalendarClient(dry_run=False)
        mock_svc = MagicMock()
        mock_list = MagicMock()

        prev_shift = _mock_event(
            summary=f"{CC_EVENT_PREFIX} Night Shift",
            start_str="2026-05-14T22:00:00",
            end_str="2026-05-15T06:00:00",
        )
        mock_list.execute.return_value = {"items": [prev_shift]}
        mock_svc.events().list.return_value = mock_list
        client._service = mock_svc

        engine = RulesEngine(config, calendar=client)
        offer = _make_offer(start_hour=9, duration=8)
        scored = engine.evaluate(offer)

        rest_reasons = [r for r in scored.reasons if "rest_gap" in r.lower()]
        assert len(rest_reasons) == 1
        assert "Only" in rest_reasons[0] or "rest" in rest_reasons[0].lower()

    def test_dry_run_still_skips_calendar_rules(self):
        config = load_config()

        engine = RulesEngine(config, calendar=None)
        offer = _make_offer()
        scored = engine.evaluate(offer)

        conflict_reason = [r for r in scored.reasons if "calendar_conflict" in r]
        assert "skipped" in conflict_reason[0].lower()


class TestFilterCcEvents:
    TZ = "America/Los_Angeles"

    def test_empty_events(self):
        assert _filter_cc_events([], self.TZ) == []

    def test_skips_non_cc_events(self):
        events = [
            _mock_event(summary="Gym", start_str="2026-05-15T09:00:00", end_str="2026-05-15T10:00:00"),
            _mock_event(summary="Doctor", start_str="2026-05-15T11:00:00", end_str="2026-05-15T12:00:00"),
        ]
        assert _filter_cc_events(events, self.TZ) == []

    def test_returns_cc_tuples(self):
        event = _mock_event(
            summary="[CC] Special Projects",
            start_str="2026-05-15T08:00:00",
            end_str="2026-05-15T16:00:00",
        )
        result = _filter_cc_events([event], self.TZ)
        assert len(result) == 1
        start, end, ev = result[0]
        assert isinstance(start, datetime)
        assert isinstance(end, datetime)
        assert ev is event
        assert start == datetime(2026, 5, 15, 8, 0)
        assert end == datetime(2026, 5, 15, 16, 0)

    def test_skips_missing_datetime(self):
        events = [
            {"summary": "[CC] Bad"},
            {"summary": "[CC] Also Bad", "start": {}},
        ]
        assert _filter_cc_events(events, self.TZ) == []

    def test_all_day_event(self):
        event = {
            "summary": "[CC] All Day",
            "start": {"date": "2026-05-15"},
            "end": {"date": "2026-05-16"},
        }
        result = _filter_cc_events([event], self.TZ)
        assert len(result) == 1
        start, end, _ev = result[0]
        assert start == datetime(2026, 5, 15)
        assert end == datetime(2026, 5, 16)

    def test_midnight_span(self):
        event = _mock_event(
            summary="[CC] Night Shift",
            start_str="2026-05-14T22:00:00",
            end_str="2026-05-15T06:00:00",
        )
        result = _filter_cc_events([event], self.TZ)
        assert len(result) == 1
        start, end, _ev = result[0]
        assert start == datetime(2026, 5, 14, 22, 0)
        assert end == datetime(2026, 5, 15, 6, 0)

    def test_timezone_conversion(self):
        event = {
            "summary": "[CC] UTC",
            "start": {"dateTime": "2026-05-15T15:00:00Z", "timeZone": "UTC"},
            "end": {"dateTime": "2026-05-15T23:00:00Z", "timeZone": "UTC"},
        }
        result = _filter_cc_events([event], self.TZ)
        assert len(result) == 1
        start, end, _ev = result[0]
        assert start == datetime(2026, 5, 15, 8, 0)
        assert end == datetime(2026, 5, 15, 16, 0)

    def test_skips_zero_duration(self):
        event = _mock_event(
            summary="[CC] Zero",
            start_str="2026-05-15T08:00:00",
            end_str="2026-05-15T08:00:00",
        )
        assert _filter_cc_events([event], self.TZ) == []

    def test_skips_negative_duration(self):
        event = _mock_event(
            summary="[CC] Backwards",
            start_str="2026-05-15T10:00:00",
            end_str="2026-05-15T08:00:00",
        )
        assert _filter_cc_events([event], self.TZ) == []


class TestSumCcHours:
    TZ = "America/Los_Angeles"

    def test_zero_events(self):
        hours, last_end = _sum_cc_hours([], self.TZ)
        assert hours == 0.0
        assert last_end is None

    def test_skips_non_cc(self):
        events = [
            _mock_event(summary="Gym", start_str="2026-05-15T09:00:00", end_str="2026-05-15T10:00:00"),
        ]
        hours, last_end = _sum_cc_hours(events, self.TZ)
        assert hours == 0.0
        assert last_end is None

    def test_sums_single_event(self):
        events = [
            _mock_event(
                summary="[CC] Shift",
                start_str="2026-05-15T08:00:00",
                end_str="2026-05-15T16:00:00",
            ),
        ]
        hours, last_end = _sum_cc_hours(events, self.TZ)
        assert hours == 8.0
        assert last_end == datetime(2026, 5, 15, 16, 0)

    def test_sums_multiple_events(self):
        events = [
            _mock_event(summary="[CC] Morning", start_str="2026-05-15T08:00:00", end_str="2026-05-15T12:00:00"),
            _mock_event(summary="[CC] Afternoon", start_str="2026-05-15T13:00:00", end_str="2026-05-15T17:00:00"),
        ]
        hours, last_end = _sum_cc_hours(events, self.TZ)
        assert hours == 8.0
        assert last_end == datetime(2026, 5, 15, 17, 0)

    def test_all_day_event(self):
        events = [
            {"summary": "[CC] All Day", "start": {"date": "2026-05-15"}, "end": {"date": "2026-05-16"}},
        ]
        hours, last_end = _sum_cc_hours(events, self.TZ)
        assert hours == 24.0
        assert last_end == datetime(2026, 5, 16)

    def test_midnight_span(self):
        events = [
            _mock_event(
                summary="[CC] Night",
                start_str="2026-05-14T22:00:00",
                end_str="2026-05-15T06:00:00",
            ),
        ]
        hours, last_end = _sum_cc_hours(events, self.TZ)
        assert hours == 8.0
        assert last_end == datetime(2026, 5, 15, 6, 0)

    def test_last_end_tracks_latest(self):
        events = [
            _mock_event(summary="[CC] Early", start_str="2026-05-15T08:00:00", end_str="2026-05-15T10:00:00"),
            _mock_event(summary="[CC] Late", start_str="2026-05-15T18:00:00", end_str="2026-05-15T23:00:00"),
        ]
        hours, last_end = _sum_cc_hours(events, self.TZ)
        assert hours == 7.0
        assert last_end == datetime(2026, 5, 15, 23, 0)


class TestComputeShiftContext:

    def test_derives_day_hours(self):
        cal = FakeCalendar(timezone="America/Los_Angeles", events_between=[
            {"summary": "[CC] Morning", "start": {"dateTime": "2026-05-15T08:00:00"}, "end": {"dateTime": "2026-05-15T12:00:00"}},
            {"summary": "[CC] Afternoon", "start": {"dateTime": "2026-05-15T13:00:00"}, "end": {"dateTime": "2026-05-15T17:00:00"}},
        ])
        offer = _make_offer(start_hour=9, duration=4)
        ctx = compute_shift_context(offer, cal)
        assert ctx is not None
        assert ctx.day_hours == 8.0

    def test_derives_weekly_hours(self):
        cal = FakeCalendar(timezone="America/Los_Angeles", events_between=[
            {"summary": "[CC] Mon", "start": {"dateTime": "2026-05-11T08:00:00"}, "end": {"dateTime": "2026-05-11T16:00:00"}},
            {"summary": "[CC] Tue", "start": {"dateTime": "2026-05-12T08:00:00"}, "end": {"dateTime": "2026-05-12T16:00:00"}},
        ])
        offer = _make_offer(start_hour=9, duration=4)
        ctx = compute_shift_context(offer, cal)
        assert ctx is not None
        assert ctx.weekly_hours == 16.0

    def test_derives_prev_day_hours(self):
        cal = FakeCalendar(timezone="America/Los_Angeles", events_between=[
            {"summary": "[CC] Prev shift", "start": {"dateTime": "2026-05-14T10:00:00"}, "end": {"dateTime": "2026-05-14T14:00:00"}},
        ])
        offer = _make_offer(start_hour=9, duration=4)
        ctx = compute_shift_context(offer, cal)
        assert ctx is not None
        assert ctx.prev_day_hours == 4.0
        assert ctx.prev_day_last_end == datetime(2026, 5, 14, 14, 0)

    def test_detects_conflict(self):
        cal = FakeCalendar(timezone="America/Los_Angeles", conflict={"summary": "[CC] Existing"})
        offer = _make_offer(start_hour=9, duration=4)
        ctx = compute_shift_context(offer, cal)
        assert ctx is not None
        assert ctx.conflicts is not None
        assert ctx.conflicts["summary"] == "[CC] Existing"

    def test_no_conflict_when_clear(self):
        cal = FakeCalendar(timezone="America/Los_Angeles")
        offer = _make_offer(start_hour=9, duration=4)
        ctx = compute_shift_context(offer, cal)
        assert ctx is not None
        assert ctx.conflicts is None

    def test_returns_none_when_no_calendar(self):
        offer = _make_offer(start_hour=9, duration=4)
        ctx = compute_shift_context(offer, None)
        assert ctx is None

    def test_adjacent_events_includes_nearby_cc(self):
        cal = FakeCalendar(timezone="America/Los_Angeles", events_between=[
            {"summary": "[CC] Early", "start": {"dateTime": "2026-05-14T22:00:00"}, "end": {"dateTime": "2026-05-15T02:00:00"}},
        ])
        offer = _make_offer(start_hour=9, duration=4)
        ctx = compute_shift_context(offer, cal)
        assert ctx is not None
        assert len(ctx.adjacent_events) == 1


class TestFakeCalendar:

    def test_defaults(self):
        cal = FakeCalendar()
        assert cal.get_events_between(datetime(2026, 1, 1), datetime(2026, 1, 2)) == []
        assert cal.get_weekly_hours() == 0.0
        assert cal.check_conflict(_make_offer()) is None
        assert cal.get_adjacent_events(_make_offer()) == []
        assert cal.timezone == "America/Los_Angeles"

    def test_overrides(self):
        cal = FakeCalendar(
            timezone="US/Eastern",
            weekly_hours=38.0,
            conflict={"summary": "Busy"},
            adjacent_events=[{"summary": "event"}],
            events_between=[{"summary": "[CC] Test"}],
        )
        assert cal.get_weekly_hours() == 38.0
        assert cal.check_conflict(_make_offer()) == {"summary": "Busy"}
        assert cal.get_adjacent_events(_make_offer()) == [{"summary": "event"}]
        assert cal.get_events_between(datetime(2026, 1, 1), datetime(2026, 1, 2)) == [{"summary": "[CC] Test"}]
        assert cal.timezone == "US/Eastern"

    def test_parse_event_dt(self):
        cal = FakeCalendar(timezone="America/Los_Angeles")
        event = {"start": {"dateTime": "2026-05-15T15:00:00Z"}}
        dt = cal._parse_event_dt(event, "start")
        assert dt is not None
        assert dt.hour == 8

    def test_callable_events_between(self):
        def _events(start, end):
            if start.year == 2026:
                return [{"summary": "[CC] 2026 event"}]
            return []

        cal = FakeCalendar(events_between=_events)
        result = cal.get_events_between(datetime(2026, 5, 1), datetime(2026, 5, 2))
        assert len(result) == 1
        result = cal.get_events_between(datetime(2025, 1, 1), datetime(2025, 1, 2))
        assert len(result) == 0