# #20 — Consolidate building data to one source of truth

**Status**: OPEN | **Labels**: ready-for-agent | **Link**: https://github.com/jitumaatgit/shift-automator/issues/20

## Parent

[#16](https://github.com/jitumaatgit/shift-automator/issues/16)

## What to build

Make `config.yaml` the canonical building list. Remove the `ShiftBuilding` enum — use plain strings. Shrink `_bracket_to_building` to alias-only entries (where bracket text differs from canonical name). `_resolve_building` validates against `config.shift_type_preferences` keys. Replace all `offer.building.value` with `offer.building` and `ShiftBuilding.UNKNOWN` with `"Unknown"`.

The parser resolves bracket text by checking the alias map first, then doing a direct config key lookup. If a bracket text has no alias and no config entry, log a warning and return `"Unknown"`. Adding a building becomes a 1-line YAML edit.

## Acceptance criteria

- [ ] `ShiftBuilding` enum and `_BUILDING_MAP` dict removed from `models.py` / `parser.py`
- [ ] `ParsedOffer.building` type changes from `ShiftBuilding` to `str` (default `"Unknown"`)
- [ ] `_bracket_to_building` map in `parser.py` contains only alias entries (e.g. `"EAC" -> "Employment Access Center"`, `"TCC/Chez Ami" -> "TCC"`) — redundant `"Special Projects" -> "Special Projects"` entries removed
- [ ] `_resolve_building` falls through to direct `config.shift_type_preferences` key check when no alias matches
- [ ] `_resolve_building` logs a warning when resolved name is not in config, returns `"Unknown"`
- [ ] All `offer.building.value` references replaced with `offer.building` throughout rules, pipeline, presenter
- [ ] Multi-site logic (`BUILDING_LUNCH_COVERAGE`) checks against string `"Building Lunch Coverage"`
- [ ] `rule_shift_type_preference` looks up `offer.building` directly in config (no `.value`)
- [ ] All parser tests updated: `assert offer.building == "Special Projects"` instead of `ShiftBuilding.SPECIAL_PROJECTS`
- [ ] New parser test: bracket text with no alias and no config entry returns `"Unknown"`
- [ ] New parser test: alias resolution works (`"EAC" -> "Employment Access Center"`)
- [ ] Full test suite passes

## Blocked by

None - can start immediately
