# #18 — Extract shared CC-hour computation to one function

**Status**: OPEN | **Labels**: ready-for-agent | **Link**: https://github.com/jitumaatgit/shift-automator/issues/18

## Parent

[#14](https://github.com/jitumaatgit/shift-automator/issues/14)

## What to build

Extract a module-level `sum_cc_hours(events, timezone) -> float` and `_parse_cc_events(events, timezone) -> List[Tuple[datetime, datetime, Dict]]` into `calendar_client.py`. Replace 4 inline `[CC]`-filter + `_parse_event_dt` + duration summation loops in `rule_day_hours_cap`, `rule_post_cap_break`, `get_weekly_hours`, and `rule_rest_gap_sleep` with calls to these shared helpers.

The `_parse_cc_events` variant returns parsed (start, end, event) tuples so `rule_post_cap_break` can also track `last_end` and `rule_rest_gap_sleep` can compute gaps without re-parsing. `sum_cc_hours` becomes a thin wrapper around `_parse_cc_events`.

## Acceptance criteria

- [ ] `sum_cc_hours()` unit-tested with known event dicts: correct parsing, timezone handling, summation, edge cases (zero events, all-day events, events spanning midnight, non-CC events skipped)
- [ ] `_parse_cc_events()` unit-tested: correct filtering of non-CC events, correct start/end extraction, typed return values
- [ ] `rule_day_hours_cap` calls `sum_cc_hours()` instead of its inline loop — same scoring behavior
- [ ] `rule_post_cap_break` calls `_parse_cc_events()` and uses returned tuples for hours and `last_end` — same scoring behavior
- [ ] `CalendarClient.get_weekly_hours` calls `sum_cc_hours()` instead of its inline loop — same weekly hours result
- [ ] `rule_rest_gap_sleep` calls `_parse_cc_events()` instead of its inline parsing loop — same gap-check behavior
- [ ] All existing rule and calendar tests pass unchanged
- [ ] No new imports or dependencies introduced

## Blocked by

None - can start immediately
