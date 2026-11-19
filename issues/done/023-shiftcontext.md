# #23 — Pre-computed ShiftContext to consolidate calendar queries

**Status**: OPEN | **Labels**: ready-for-agent | **Link**: https://github.com/jitumaatgit/shift-automator/issues/23

## Parent

[#12](https://github.com/jitumaatgit/shift-automator/issues/12)

## What to build

Introduce a `ShiftContext` frozen dataclass that pre-computes all calendar-derived state in one pass. A single `compute_shift_context(offer, calendar)` factory does one wide-window query (1 week before to 7 days after offer) and derives all fields: `day_hours`, `prev_day_hours`, `prev_day_last_end`, `adjacent_events`, `weekly_hours`, `conflicts`. Rules consume `ShiftContext` instead of querying the calendar directly. `RulesEngine.evaluate()` computes the context once and passes it to all rules.

The CC-hour summation logic uses the shared `sum_cc_hours()` helper (from #18). The single wide-window query spans all 5 rule windows. `EventStore` superset matching handles the "cached window wider than requested" case automatically.

## Acceptance criteria

- [ ] `ShiftContext` frozen dataclass defined with fields: `day_hours: float`, `prev_day_hours: float`, `prev_day_last_end: Optional[datetime]`, `adjacent_events: List[Dict]`, `weekly_hours: float`, `conflicts: Optional[Dict]`
- [ ] `compute_shift_context(offer, calendar) -> ShiftContext` does one wide-window query, derives all fields, uses `sum_cc_hours()` for CC-hour totals
- [ ] `compute_shift_context` unit-tested independently: feed known event data, assert correct derived fields
- [ ] `rule_calendar_conflict` accepts `context: ShiftContext` instead of `calendar` — reads `context.conflicts`
- [ ] `rule_day_hours_cap` accepts `context: ShiftContext` — reads `context.day_hours`
- [ ] `rule_post_cap_break` accepts `context: ShiftContext` — reads `context.prev_day_hours` and `context.prev_day_last_end`
- [ ] `rule_rest_gap_sleep` accepts `context: ShiftContext` — reads `context.adjacent_events`
- [ ] `rule_weekly_hours_cap` accepts `context: ShiftContext` — reads `context.weekly_hours`
- [ ] `RuleFn` signature changes from `(offer, config, calendar, errors)` to `(offer, config, context, errors)` where `context` is `Optional[ShiftContext]`
- [ ] `RulesEngine.evaluate()` calls `compute_shift_context()` once, passes result to all rules
- [ ] `RulesEngine` works without calendar: `ShiftContext` is `None` when `calendar=None`, rules handle `None` gracefully (preference-based rules already do)
- [ ] Scoring behavior identical to current — same decisions for all 41+ sample shifts
- [ ] `make_context(day_hours=8.0, ...)` factory replaces per-rule `_mock_calendar()` + `side_effect` chains in tests
- [ ] No rule calls `calendar.get_events_between`, `calendar.check_conflict`, `calendar.get_weekly_hours`, or `calendar.get_adjacent_events` directly
- [ ] Full test suite passes

## Blocked by

- [#18](https://github.com/jitumaatgit/shift-automator/issues/18) — shared CC-hour computation (`sum_cc_hours`)
- [#21](https://github.com/jitumaatgit/shift-automator/issues/21) — calendar protocol (type-safe interface)
