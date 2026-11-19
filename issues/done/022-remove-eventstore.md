# #22 — Remove EventStore, merge caching into CalendarClient

**Status**: OPEN | **Labels**: ready-for-agent | **Link**: https://github.com/jitumaatgit/shift-automator/issues/22

## Parent

[#15](https://github.com/jitumaatgit/shift-automator/issues/15)

## What to build

Merge `EventStore` cache logic into `CalendarClient` as private methods. The `fetcher` callback parameter is removed — `_fetch_all_events` is called directly. Delete the `EventStore` class. Cache file path, TTL, and timezone remain as `CalendarClient` constructor parameters. No external API change.

## Acceptance criteria

- [ ] `EventStore` class deleted from `calendar_client.py`
- [ ] Cache state (`_cached_events`, `_cache_time`, `_cache_window_start/end`) moved to `CalendarClient` instance attributes
- [ ] Cache methods (`_load_cache_file`, `_save_cache_file`, `_filter_by_window`, `invalidate`) moved to `CalendarClient` as private methods
- [ ] `CalendarClient.__init__` no longer constructs `EventStore` — no `fetcher` callback parameter
- [ ] `get_events_between` calls `self._get_cached_events(start, end)` directly (or equivalent private method)
- [ ] Caching logic calls `self._fetch_all_events(window_start, window_end)` directly instead of through `self._fetcher(...)`
- [ ] `_fetch_all_events` dry_run guard (`return []` when `self.dry_run or not self._service`) preserved
- [ ] `_parse_event_dt` stays module-level
- [ ] Cache TTL, window-based lookup, superset in-memory matching, file cache persistence, and invalidation all work identically
- [ ] `invalidate_cache()` still works: deletes cache file, clears in-memory state
- [ ] All cache tests ported from `test_calendar.py` `TestCalendarCache` to test `CalendarClient` directly
- [ ] Full test suite passes

## Blocked by

- [#21](https://github.com/jitumaatgit/shift-automator/issues/21) — recommended: protocol provides stable interface while internals change
