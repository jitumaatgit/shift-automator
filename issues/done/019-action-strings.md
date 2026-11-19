# #19 — Lift action strings to structured types

**Status**: OPEN | **Labels**: ready-for-agent | **Link**: https://github.com/jitumaatgit/shift-automator/issues/19

## Parent

[#17](https://github.com/jitumaatgit/shift-automator/issues/17)

## What to build

Define `ActionKind` enum and `Action` dataclass in `models.py`. Pipeline functions append `Action` objects instead of raw strings. A single `format_action(action) -> str` converts to display strings. Update tests to assert on `action.kind` instead of exact strings. Update `data/tasker_backup.xml` JSON Read paths for the new structured format.

The enum has members: `PARSE`, `DECISION`, `SMS_SENT`, `PUSH_SENT`, `DRY_RUN`, `WARNING`, `SKIPPED`. Each `Action` has `kind: ActionKind` and `detail: str`. Display formatting uses the same wording as today — only the data model changes.

## Acceptance criteria

- [ ] `ActionKind` enum and `Action` dataclass defined in `models.py`
- [ ] `PipelineResult.actions` type changes from `List[str]` to `List[Action]`
- [ ] `_process_shift` appends `Action(ActionKind.PARSE, ...)` and `Action(ActionKind.DECISION, ...)`
- [ ] `_execute_accept` appends `Action(ActionKind.PUSH_SENT, ...)` and `Action(ActionKind.SMS_SENT, ...)`
- [ ] `_execute_decline` appends `Action(ActionKind.PUSH_SENT, ...)` and `Action(ActionKind.WARNING, ...)`
- [ ] `_handle_confirmation` and `_handle_rejection` append structured actions
- [ ] `format_action()` in a single location converts actions to display strings (same wording as current)
- [ ] JSON presenter outputs `{"kind": "sms_sent", "detail": "..."}` instead of raw string
- [ ] `data/tasker_backup.xml` JSON Read paths updated for new structured format
- [ ] All existing tests pass (test_presenter updated to assert on `kind` not exact strings)

## Blocked by

None - can start immediately
