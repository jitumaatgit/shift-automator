# tests/ Agent Instructions

## General

- **`SystemExit` crashes pytest collection**: Raising `SystemExit` during module import in `test_*.py` causes `INTERNALERROR` (not graceful skip). Use `if __name__ == "__main__":` guard for standalone scripts moved into `tests/`, or rename to not match `test_*.py` glob.

## test_parser.py

- **`is not None` → year check for parse success**: Since `ParsedOffer.start_time` is no longer `Optional`, use `offer.start_time.year > 2000` instead of `offer.start_time is not None` to verify parsing succeeded. The sentinel for failed parses is `datetime(1970, 1, 1)`.
- **Return type is now tuple**: `parse_shift_text()` returns `(ParsedOffer, list[str])` — assign with `offer, errors = parse_shift_text(...)`. Parse errors are a separate list, not in `offer.decision_reasons`.

## test_rules.py

- **`_make_offer()` builds frozen `ParsedOffer`**: `ParsedOffer` is frozen — fields cannot be mutated after construction. Tests that need non-default field values (e.g., overtime `shift_note`) must pass them as `_make_offer()` parameters, not assign after construction.
- **`engine.evaluate()` returns `ScoredOffer`**: Assert with `scored = engine.evaluate(...)` then `scored.score`, `scored.reasons`, `scored.decision`. No more `hasattr(offer, "decision_score")` — decision state never lives on the input offer.
- **`_mock_calendar(hours)` replaces pre-computed `weekly_hours` param**: Overtime tests use `RulesEngine(config, calendar=self._mock_calendar(hours=38.0))` instead of `RulesEngine(config, weekly_hours=38.0)`. The mock calendar always returns the same hours regardless of `week_start`, controlled by `get_weekly_hours.return_value`. Must also mock `check_conflict` and `get_adjacent_events` to prevent AttributeError in other rules.
- **`get_adjacent_events` mock data must use `[CC]` prefix for rest_gap_sleep tests**: `rule_rest_gap_sleep` skips non-`[CC]` events. If the test expects a penalty, the mock event summary must start with `[CC]` (e.g., `"[CC] Morning shift"`). The old `test_rest_gap_violation_relaxed_hours` passed for the wrong reason — its mock `"Day shift"` lacked `[CC]`, so the rule skipped it entirely rather than exercising relaxed-hours logic.
- **Multiple calendar rules in one test need window-specific mocks**: `day_hours_cap` and `post_cap_break` both call `get_events_between` with different day windows. A static `return_value` causes cross-rule contamination — e.g., `day_hours_cap` sees previous-day data intended for `post_cap_break`. Use `side_effect` keyed on the query window to return distinct data per rule.
- **`rule_wakefulness_gate` tests must patch `rules.datetime`**: `rules.py` imports `datetime` at module level. Patching the global `datetime.datetime.now` does not reach the module's local binding. Use `@patch("rules.datetime")` or `patch.object(rules, "datetime", ...)`.

## test_calendar.py

- **File cache contamination across tests**: Tests using `_make_client_with_mock_service()` write `calendar_cache.json` via `_fetch_all_events()` → `_save_cache_file()`. Subsequent tests that check the file cache (exact window match or superset) load stale mock data from prior tests — e.g., returning "Busy" instead of "Doctor Appointment". Superset file-cache matching amplifies this. Keep cache window checks in-memory only; file cache serves cross-process reuse, not same-session test isolation.
- **Mock bypass must set `_authed = True`**: `_make_client_with_mock_service()` already does this. Any new mock setup that assigns `_service` directly without `_authed = True` causes `get_weekly_hours()` to return 0.0 silently.
- **Pass `cache_file` param instead of monkeypatching `CACHE_FILE`**: Use `CalendarClient(cache_file=str(tmp_path / "calendar_cache.json"), cache_ttl=1)` instead of `monkeypatch.setattr("calendar_client.CACHE_FILE", ...)`. The `CACHE_FILE` module constant is deleted — cache file path is a constructor parameter.
- **Mock event summaries must use `[CC]` prefix for conflict/rest-gap tests**: When CC-only filtering is added to `check_conflict` or `rule_rest_gap_sleep`, non-`[CC]` events are silently skipped. Tests with summaries like `"Existing Meeting"` or `"Morning shift"` will falsely report "no conflict" / "rest gap OK". Update mock event summaries in the same commit as the filtering logic.

## test_pipeline.py

- **CalendarClient stub needs both `_service` mock and `_authed = True`**: Without `_authed = True`, `get_weekly_hours()` silently returns 0.0 — mask scoring differences and can hide bugs where weekly hour capping should block a shift. The `_dummy_calendar()` helper sets both.
- **`_resolve_input` returns `str`, not `Tuple`**: The helper was refactored from `(text, done)` tuple to plain `str`. Indexing with `[0]` on a string grabs the first character. The bug manifested as empty claim_code in the only integration test (`test_stdin_piping_parses_correctly`) but parser tests passed fine — isolated parser call succeeded while the full pipeline (via main.py) failed.
- **`test_stdin_piping_parses_correctly` is the only CLI integration test**: Exercises `subprocess.run(["src/main.py", "--json"], input=text)`. It is the canary for output format regressions — all other tests are unit/integration at the parser/rules/calendar level.

## test_presenter.py

- **`_format_result` handles `parsed=None`**: Confirmation parse failures return `PipelineResult(parsed=None)`. The formatter guards with `result.parsed and result.parsed.title` (short-circuit) and `result.parsed.title if result.parsed else None` (ternary in JSON mode). Both patterns handle None correctly.
- **Failed-parser sentinel check**: `offer.start_time.year > 2000` distinguishes valid dates from the `datetime(1970, 1, 1)` sentinel. JSON output gets `null` when the sentinel is detected.
- **`_format_result` action strings are opaque magic strings**: Test assertions like `assert data["actions"] == ["parsed: ...", "sent: decline push"]` must exactly match the literal strings appended in `pipeline.py`. There are no shared constants. When pipeline action strings change, the matching test assertion must be updated identically — a silent break with no compiler/runtime warning.

## test_responder.py

- **The test suite previously had zero coverage for `TermuxResponder._send_sms`**: The `subprocess.run` → `Popen` bug was invisible to all 92 tests because no test exercised the real transport path. Any change to SMS spawning logic needs a dedicated test that asserts `subprocess.Popen` is called with the correct command and stdin is written.
