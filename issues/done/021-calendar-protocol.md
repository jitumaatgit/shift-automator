# #21 — Define explicit calendar interface protocol for rules engine

**Status**: OPEN | **Labels**: ready-for-agent | **Link**: https://github.com/jitumaatgit/shift-automator/issues/21

## Parent

[#13](https://github.com/jitumaatgit/shift-automator/issues/13)

## What to build

Define `CalendarProtocol` (a `typing.Protocol`) that declares the exact method signatures rules need from the calendar. Change `RulesEngine.__init__` and `RuleFn` signature from `Any` to `Optional[CalendarProtocol]`. Create `FakeCalendar` with sensible defaults. Replace `_mock_calendar()` helpers in `test_rules.py` and `test_calendar.py` with `FakeCalendar` instances.

The protocol declares: `get_events_between`, `get_adjacent_events`, `get_weekly_hours`, `check_conflict`, and `_parse_event_dt`. `CalendarClient` already implements all five — no code change needed, just the class now implicitly satisfies the protocol. Once `ShiftContext` (PRD #12) ships, the protocol shrinks to just `get_events_between`.

## Acceptance criteria

- [ ] `CalendarProtocol` class defined in `calendar_client.py` declaring 5 method signatures
- [ ] `RulesEngine.__init__` parameter typed as `Optional[CalendarProtocol] = None`
- [ ] `RuleFn` type alias updated: `Any` parameter becomes `Optional[CalendarProtocol]`
- [ ] `FakeCalendar` class in `calendar_client.py` with sensible defaults: `get_events_between` returns `[]`, `check_conflict` returns `None`, `get_weekly_hours` returns `0.0`, `get_adjacent_events` returns `[]`, `_parse_event_dt` works on mock event dicts
- [ ] `FakeCalendar` tested in isolation — verify defaults and overrides
- [ ] `_mock_calendar()` in `test_rules.py` replaced with `FakeCalendar(weekly_hours=38.0)` style construction
- [ ] `_mock_calendar()` pattern in `test_calendar.py` replaced with `FakeCalendar`
- [ ] All existing tests pass — `CalendarClient` continues to work unchanged
- [ ] `CalendarClient` satisfies the protocol without modification (structural subtyping)

## Blocked by

None - can start immediately
