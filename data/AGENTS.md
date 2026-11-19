# data/ Agent Instructions

## tasker_backup.xml

- **This is the canonical Tasker config**: Full Tasker backup. Contains all tasks (Parse Shift Offer, RunShiftBot, Display Shift Notification, etc.) and profiles. Must be kept in sync with Python changes — when the JSON output format changes, the Variable Set actions here must be updated in the same commit.
- Deploy to phone with a timestamped filename (e.g. `backup7-16.xml` for a 2026-07-16 deploy) to preserve known-good baselines: `adb push data/tasker_backup.xml /sdcard/backupMM-DD.xml` → Tasker: Settings → Data → Restore. On the phone via Termux: `cp ~/shift-automator/data/tasker_backup.xml /sdcard/backupMM-DD.xml`.
- Variable Set (code 547) accepts `%SHIFT_JSON[key]` bracket syntax for arg1 when arg5=0. arg5=3 would treat it as literal text.
- **`<Project>` `<tids>` must exactly match available `<Task>` elements**: When removing tasks from the backup XML, update the comma-separated `<tids>` list on the `<Project>` element. A `<tids>` entry referencing a non-existent task ID causes "Bad packed data format" import error in Tasker. This applies to `<pids>` (profiles) as well.
- **Task 42 gates the native claim with three conditions** (all must hold for act2 Send SMS to fire):
  1. `%claim1` Is Set (op 12) — a claim code was extracted from the SMS body.
  2. `%SMSRB !~ *Building Lunch Coverage*` (op 3, glob NOT-match) — not a Building Lunch Coverage shift.
  3. `%SMSRB !~R starting\s+at\s+(?:\w{3}\s+\d{1,2}/\w{3}\s+)?(?:1[01]:[0-5][0-9]\s*pm|(?:12|0?[1-5]):[0-5][0-9]\s*am)` (op 5, regex NOT-match) — start time is NOT in the sleep window (22:00–05:59). PM hours 10pm/11pm (22/23) and AM hours 12am–5am (0–5) are vetoed; 6am and later pass.
  **Tasker op codes**: `op 3` = !Match (glob, the `!~` operator), `op 5` = !~R (regex NOT-match), `op 12` = Is Set. Do NOT confuse op 3 with regex match — op 4 is `~R` (regex match), op 5 is its negation. **Code 598 (Variable Search Replace) stores WHOLE matches, not capture groups** — `%claim1` contains the full match (e.g., `reply 1867694`), not just the capture group. Use lookbehind regex like `(?<=reply\s)\d{5,8}` to extract only the digits.
- **Task 42 act21 writes the claim marker immediately after act2 (Send SMS)** (code 410 Write File, inside the claim gate): file `/sdcard/Tasker/shift_claim_sent.txt`, text `%claim1 %TIMES` (Append=0, Newline=0). This marker is the single authoritative "claimed" signal — `_native_claim_already_sent()` in `src/pipeline.py` reads it (`code, ts = ...split()`), Python NEVER claims itself. Execution order matters: Send SMS MUST precede the marker write — if Send SMS errors, Tasker aborts the task and no marker is written, which must mean "not claimed". Do NOT reorder act2/act21.
- **Task 43 (RunShiftBot) plugin timeout is 60s** (`<Int sr="arg3" val="60"/>`): Python's worst case (calendar fetch) is ~15s; the old 10s timeout killed mid-pipeline runs (2026-08-06 23:20: A Err at 11s, no log entry). Task 2 (RefreshCalendarCache) keeps 10s — it is fire-and-forget (`WAIT_FOR_RESULT=false`) so the timeout is inert there.
- **Task 43 Collision Handling must be "Run Both Together" — UI-only, not in the XML backup**: re-apply it in Tasker task properties after EVERY XML restore. A confirmation arriving while Python runs previously hit the default "Abort New" (`T RejCopy ID43` in runlog) and was silently dropped; with Run Both Together the wrapper's flock serializes concurrent copies safely.

## shift-bot

- Must live at `~/.termux/tasker/shift-bot` on the phone with `chmod +x`. Deploy via Termux: `cd ~/shift-automator && git pull && cp data/shift-bot ~/.termux/tasker/shift-bot`.
- **Reads SMS body from STDIN, not `$*`** (final state): Tasker's `RunShiftBot` (task43) passes `%SMSRB` via `com.termux.tasker.extra.STDIN` with `com.termux.execute.arguments: <null>`. The wrapper does `INPUT=$(cat)`, appends a fingerprint line to `~/.termux/tasker/shift-bot-runs.log` (that line's absence on the phone is how the stale wrapper was caught), flock-serializes via `flock -w 120 9` on `~/.termux/tasker/shift-bot.lock` (logs `LOCK_TIMEOUT` and exits 1 if the lock is busy), then runs `python src/main.py --json --text "$INPUT"`. Python never claims — Tasker's act2 Send SMS is the only claimer; `--text "$INPUT"` keeps multi-line bodies intact in one argv. A version that reads `$*` silently gets empty input (the historical double-claim bug). There is NO `SHIFT_AUTOMATOR_FAST_CLAIM` export and NO claim-code/grep logic in the wrapper anymore — the claim record is task42 act21's marker write, which is why the wrapper no longer needs to know the code.
- The old `grep -qi 'building lunch coverage'` guard is gone: Python's `_execute_accept` emits a WARNING (not a decline) when the marker is missing, and the BLC veto is enforced by Tasker act1 + the full rules engine (`shift_type_preference` scores BLC at -100.0).

## tasker_refresh_cache.xml

- Tasker import XML MUST wrap everything in `<Project sr="proj0" ve="2">` — any other `sr` value (e.g. `proj2`) causes "no project found" import error. The `sr` attribute is a const per the Tasker schema.
- `<Profile>` and `<Task>` elements are siblings of `<Project>` under `<TaskerData>`, not children of Project. The Project only references IDs via `<pids>` and `<tids>` comma-separated lists.
- Termux:Tasker plugin action code is `1256900802` — not in the tasker-automation skill's REFERENCE.md (plugin codes excluded). Found by extracting `<code>` from the live phone backup.
- The `com.termux.tasker.extra.EXECUTABLE` field is a script basename (e.g. `shift-bot-refresh`), not a full path. Tasker resolves it to `~/.termux/tasker/<name>`. The wrapper script must exist at that path with execute permissions.

## shift-bot-refresh

- Must live at `~/.termux/tasker/shift-bot-refresh` on the phone with `chmod +x`.
- Script runs `python src/main.py --refresh-cache` — the `--refresh-cache` flag triggers `_build_calendar()` which constructs and authenticates `CalendarClient` (no event fetch), then exits early in `_handle_cli_actions`.
