# Shift Automator - Agent Instructions

## Quick Navigation
- **Entry**: `src/main.py`
- **Config**: `config.yaml` (all behavior)
- **Tests**: `pytest tests/`
- **Deps**: `pip install -r requirements.txt`
- **Handoff location**: `C:\Users\student\AppData\Local\Temp\handoff-*.md` (temp handoff files)

## Critical: Android/Termux Deployment

This runs on Android phones with **dual SIMs** via Termux. Key setup:

1. **Install**: Termux, Termux:API, Termux:Tasker, Tasker (use F-Droid)
2. **SIM ID**: Find `work_sim_sub_id` by testing:
   ```bash
   termux-sms-send -s 1 -n YOUR_NUMBER "test"
   termux-sms-send -s 2 -n YOUR_NUMBER "test"
   ```
3. **Tasker Wrapper**: Create `~/.termux/tasker/shift-bot`:
   ```bash
   #!/data/data/com.termux/files/usr/bin/bash
   cd /data/data/com.termux/files/home/shift-automator
   python src/main.py --json --text "$*"
   ```
4. **Tasker Profile**: Event → Phone → Received Text (matching `staffing_number` in config)
5. **Battery**: Set Tasker + Termux to "Unrestricted" in Android settings
6. **Cache Refresh Script**: Create `~/.termux/tasker/shift-bot-refresh` and make it executable (`chmod +x`):
   ```bash
   #!/data/data/com.termux/files/usr/bin/bash
   cd /data/data/com.termux/files/home/shift-automator
   python src/main.py --refresh-cache
   ```
    Then import `data/tasker_refresh_cache.xml` in Tasker — it adds a Time profile that runs this every 15 minutes to keep `calendar_cache.json` fresh.

### Deployment to Phone

The project **must live at** `/data/data/com.termux/files/home/shift-automator/` (Termux private home). The Tasker wrapper hardcodes this path. Do NOT clone to `/sdcard/`:
- `/sdcard/` is FUSE-emulated shared storage — slower I/O
- `credentials.json` on `/sdcard/` is readable by any app with storage permission
- ADB cannot write to Termux's private data dir (UID isolation)

```bash
# Preferred: git pull from within Termux (no sdcard involvement)
cd ~/shift-automator && git pull

# For pushing individual changed files: push to /sdcard/, mv into project, rm sdcard copy
# (never leave source files on shared storage)
MSYS_NO_PATHCONV=1 adb push config.yaml /sdcard/
# In Termux: mv /sdcard/config.yaml ~/shift-automator/config.yaml
```

## Preferred: SSH to phone via Termux (`ssh phone`)

ADB is a last resort — the Debian tablet has **no USB host controller** (`/sys/bus/usb` empty; the only enabled USB node is `usbdrd` in **gadget/peripheral mode**, so a phone cabled to the tablet never enumerates). Use SSH instead:

```bash
ssh phone                          # key-only, alias in ~/.ssh/config (port 8022)
ssh phone 'cd ~/shift-automator && python -m pytest tests/ -q'
```

- **Alias**: `~/.ssh/config` → `Host phone` = `10.0.70.203`, port `8022`, user `u0_a240` (Termux sshd ignores the login username; the real uid is what `whoami` reports). Key: `~/.ssh/id_ed25519` (`fomar@tablet-arch-rescue`), installed on the phone via `ssh-copy-id`.
- **IP is DHCP — it drifts**: if `ssh phone` hangs, find the new IP with `ip neigh show` (look for the Doogee's MAC `d2:d0:33:72:c6:69`), or ask the user; then update `~/.ssh/config`. mDNS/`.local` does **not** resolve on this tablet.
- **File access**: `read`/`write` tools work over `ssh://phone/<abs-path>` — home is `/data/data/com.termux/files/home/`, so e.g. `read ssh://phone/data/data/com.termux/files/home/shift-automator/config.yaml`. Relative paths resolve against `/` and fail; always use the absolute `/data/data/com.termux/files/home/…` prefix.
- **Runtime artifacts**: `shift_automator_log.json` and `calendar_cache.json` live on the phone at `~/shift-automator/` — always read them over SSH, never from a stale local copy.
- **Remote shell**: `ssh phone '…'` runs in the phone's Termux (`zsh`); `/tmp` does NOT exist there — use `~` or the bot's dir for scratch files.

## Google Calendar Setup

Requires `credentials.json` (service account key):
1. Create GCP project → Enable Google Calendar API
2. Create service account → Download JSON key → Save as `credentials.json`
3. Share calendar with service account email (give "Make changes" permission)
4. Set `calendar_id` to your Gmail in `config.yaml`

**Security**: Never commit `credentials.json` to git (already in `.gitignore`)

## Testing Strategy

**Always run parser tests first** to validate against real samples:
```bash
pytest tests/test_parser.py tests/test_rules.py -v
```

Tests use **real shift texts** from `data/sample_shifts.md` (41+ samples). When modifying parsers, verify against all samples.

Dry-run mode (`dry_run: true` in config) skips real SMS/calendar changes.

## Key Configuration

Nearly all behavior is in `config.yaml`. Critical sections:

- **Decision threshold**: Binary `auto_decline_threshold` — score > threshold → AUTO_ACCEPT, else AUTO_DECLINE. No manual confirm step.
- **SIM IDs**: `work_sim_sub_id`, phone numbers: `staffing_number`, `personal_number`
- **Preferences**: `shift_type_preferences`, `title_preferences`, `location_preferences`
- **Calendar**: `calendar_id`, `calendar_credentials_path`, `calendar_timezone`
- **Active rules**: `active_rules` (order matters)

## Command Patterns

Process sample shift:
```bash
python src/main.py --sample 1
```

Process raw text (JSON output for automation):
```bash
python src/main.py --json --text "Open shift at [Special Projects] ..."
```

Run specific test file:
```bash
pytest tests/test_parser.py -v
```

## Architecture Notes

**Flow**: Tasker task42 native Send SMS (act2) is the ONLY claimer — gated by act1 (claim code found, not Building Lunch Coverage, start not in 22:00–06:00). Immediately after claiming, task42 act21 writes the claim marker file `/sdcard/Tasker/shift_claim_sent.txt` (`code epoch`). Task43 (`RunShiftBot`) then runs `data/shift-bot`, which serializes via flock and calls Python with `--text`; Python classifies/scores the offer and NEVER sends a claim — it reads the marker for accept-skip logging and decline cancel-warnings. Confirmation SMS (shortcode reply) → Calendar event + ✅ push; rejection → ❌ push; everything appends to `shift_automator_log.json`. Binary decision — no manual confirm step.

- `parser.py`: Regex-based, handles 4+ shift formats + confirmation/rejection detection
- `rules.py`: Configurable scoring, location/title matching uses both address AND building name
- `pipeline.py`: `process_offer()` router classifies incoming SMS via `classify_incoming()` → dispatches to offer pipeline (`_process_shift`), confirmation handler, or rejection handler
- `calendar_client.py`: Event conflict detection, weekly hours, rest gaps; event creation only on confirmation
- `responder.py`: Supports `stub`, `termux`, `twilio` transports; ntfy `X-Message` header links pending→booked/not-booked pushes

## Common Pitfalls

- **Wrong SIM ID**: Test both SIM slots before deploying Tasker profile
- **Battery optimization**: Android kills background apps aggressively; Tasker is the listener, not a persistent Python loop
- **Calendar timezone**: All naive times interpreted as `calendar_timezone` (default: `America/Los_Angeles`)
- **Location matching**: Scores against `display_address` AND `building.name` - even if address parsing fails, bracket match still works
- **Service account calendar sharing**: Must grant "Make changes and manage sharing" not "See only" for event CRUD
- **`load_config()` uses `copy.deepcopy(DEFAULTS)`** (config.py:145) — nested dicts/lists are safe from mutation leaking across callers. The old shallow `dict(DEFAULTS)` was a historical bug; the fix is already in place.
- **Classification is unified into a single step**: `classify_incoming()` is the sole classification entry point. The deleted `_classify_non_offer_text()` and its `benign` set synchronization risk are gone. Parser trusts the router to pre-classify offer text.
- **Calendar auth failure previously returned 40.0 weekly hours**: Before the fix, `get_weekly_hours()` returned 40.0 (the cap) when unauthenticated, silently vetoing every shift via `weekly_hours_cap`. Now returns 0.0 with a warning — calendar-proven shifts pass through unguarded when auth is down.
- **Config key `work_sim_sub_id` is a slot index, not the work number**: On this device SIM 1 = Access Wireless = personal number (+15035550100), contradicting the config name. The label is historical — it means "the SIM slot to use for outgoing SMS", which may be personal or work depending on the phone's SIM arrangement.
- **`calendar_cache.json` and `shift_automator_log.json` are runtime artifacts**: These change on every pipeline run and always show up in `git diff`. Never commit them — they are auto-generated state, not configuration. **Always ADB pull fresh from phone before analyzing** — the local copy may be hours stale if the phone is the active runtime.
- **`elapsed_ms` in the JSON log measures only `_process_shift()`** — the timer starts AFTER config loading, calendar auth, Tasker health check, and all imports. The 2-3.7s measurement covers only 15-40% of the 10-50s end-to-end gap. Query `content://sms` for true send timestamps — never trust `elapsed_ms` for claim-speed analysis.
- **Documented exclusions must actually be in `.gitignore`**: The runtime artifacts above were called out as "never commit" but were not ignored. Verify AGENTS.md advice is enforced in `.gitignore`, not just written down.
- **`.gitignore` does not affect already-tracked files**: If `calendar_cache.json` or `shift_automator_log.json` were previously committed, they continue showing up in `git diff` until `git rm --cached` is run.
- **`.gitignore` does not support inline `#` comments**: A line like `.opencode/ # comment` treats the entire text including `# comment` as the literal pattern name. The `#` is only treated as a comment when it appears as the first non-whitespace character on a line. Always put comments on their own line above the pattern.
- **Gitignore `*` appends only — it does not insert**: `shift_automator_log.json*` only matches files starting with `shift_automator_log.json` plus optional trailing chars, NOT `shift_automator_log_sdcard.json` (which inserts `_sdcard` before `.json`). Use `shift_automator_log*` to catch all variants.
- **`git check-ignore -v <path>` debugs gitignore matching**: Shows which `.gitignore` line matched a path, or returns nothing if no pattern matches. First tool to reach for when a file won't stay ignored.
- **Shortcode always replies to claim code SMS**: Confirmed via actual SMS logs — either "Congratulations..." (booked) or "Sorry... already taken" (failed). No timeout/watchdog mechanism is needed; the confirmation/rejection handlers are stateless and react to the next incoming SMS.
- **ADB cannot verify Termux files**: `adb shell ls /data/data/com.termux/files/home/` returns Permission denied (Termux is not debuggable). Do not assume files are missing just because ADB can't see them. The `shift-bot` wrapper script exists on the phone at `~/.termux/tasker/shift-bot` — verified manually in Termux (2026-05-16).
- **Tasker's Variable Set must explicitly extract each consumed JSON field**: The Python `--json` output includes many fields, but a `%SHIFT_*` variable is only populated when a Variable Set (code 547) action extracts it from `%SHIFT_JSON[key]`. Undefined variables fail silently downstream — there's no visible error beyond `A Err` in the runlog.
- **`tasker-setup.md` can diverge from phone reality**: Documented Tasker commands (e.g., `termux-sms-send -s 337889`) may be wrong for months while the phone runs the same broken command. When debugging silent Tasker failures, compare `tasker-setup.md` against the runlog — the runlog is authoritative.
- **Ephemeral Windows `/tmp` is cleared between sessions**: Do not rely on temporary file persistence. Work on files stored in the repo directly. The ADB push → pull verify cycle should target the repo copy, not `/tmp`.
- **Enum removal cascades silently across multiple test files**: Removing a value from `ShiftDecision` breaks tests across multiple files. These failures only surface on `pytest tests/` — targeted runs like `pytest tests/test_rules.py` miss them. Always run the full suite before committing enum/model changes.
- **Empty YAML list values parse as `null`**: `disliked:` (empty line, no value) becomes `None`, not `[]`. `_deep_merge` overwrites the default `[]` because the key exists. Always use explicit `[]` for empty lists in `config.yaml`, or add code guards downstream.
- **`undesired_hours` entries must be `[start, end]` pairs**: Single-element lists like `[24]` crash tuple unpacking in `rule_time_of_day`. Malformed entries are now skipped, but config should still be valid.
- **AGENTS.md files become stale alongside code**: When removing config fields, rules, or enum values, the root AGENTS.md "Key Configuration" and "Architecture Notes" sections may still reference the deleted names. Audit AGENTS.md alongside config changes.
- **Phone logs reveal code version drift**: Log entries record the rule names that were active at the time of processing. May 17-20 entries show `[minimum_rest]`/`[force_accept]`/`[weekly_hours]`; May 21-22 entries show `[rest_gap]`/`[time_of_day]`. Before diagnosing from logs, check whether the logged rule names match current `active_rules` — the phone may run a different commit than repo HEAD.
- **Config dataclass changes break tests immediately**: Removing a field from `Config` (e.g., `rest_gap_strict_hours`) breaks any test using `replace(removed_field=...)`. The frozen dataclass gives no deprecation window — `TypeError` on the next run. Grep `tests/` for the old key before deleting.
- **Calendar rules share one precomputed `ShiftContext`**: `RulesEngine.evaluate()` calls `compute_shift_context()` once (a single wide `get_events_between` fetch), and `day_hours_cap`/`post_cap_break`/`rest_gap_sleep`/`weekly_hours_cap` read its fields. In tests, construct a `ShiftContext` directly or pass `FakeCalendar` to `RulesEngine`.
- **A shift that "auto-declined" with a passed score and a pending ntfy push actually suffered a silent SMS spawn failure, not a rules veto**. The pending push sends successfully (ntfy shows ⏳), but if the accept SMS thread dies before spawning `termux-sms-send`, the shift is never claimed. Check the action log for "sent: accept text" — if present without a corresponding SMS log, the thread was killed during interpreter shutdown.
- **Reordering operations in `_execute_accept` can break the implicit thread-lifecycle contract**: The pending push's 1–3s HTTP latency previously masked that the SMS daemon thread needed the main thread to stay alive. Moving push first allowed main-thread exit during the push call, killing the daemon before `subprocess.run` could spawn `termux-sms-send`.
- **`active_rules` changes require syncing 4 locations**: `config.yaml` active_rules list, `Config` dataclass tuple (config.py:17-28), `DEFAULTS` list (config.py:81-92), and the hardcoded assertion in `tests/test_config.py::test_config_no_dict_access_needed`. Miss any one → silent drift between code defaults and test expectations.
- **No project-level `opencode.json`**: the project inherits the global config at `~/.config/opencode/opencode.json` (provider `opencode-go`, models `deepseek-v4-pro`/`deepseek-v4-flash`, server on port 3000). Do NOT re-add a project `opencode.json` to switch providers/models — edit the global config instead. NVIDIA NIM is NOT used locally (override removed 2026-07-15), but its API key IS still used by the GitHub Actions agent workflows — see "GitHub Actions" below.
- **`opencode run` / `occ` auth**: `OPENCODE_SERVER_PASSWORD` is exported by OpenCode Desktop and inherited by child shells; `occ` and `opencode run` authenticate fine WITH it set. Do NOT unset it (the old #24747 "Session not found" unset advice is obsolete as of 1.17.18; see `~/.config/opencode/AGENTS.md` "OpenCode Server Auth").
- **Tasker code 598 (Variable Search Replace) stores WHOLE matches, not regex capture groups**: The `%claim1` variable contains the full match (e.g., `reply 1867694`), not the first capture group. Tasker's implementation of search-and-replace discards capture groups immediately. Do NOT use capture groups in code 598 regex patterns; use lookbehind/lookahead assertions instead (e.g., `(?<=reply\s)\d{5,8}` matches just the digits). This affected the claim-code extraction in Tasker's native Send SMS path.
- **Tasker Received Text Sender field matching**: shortcodes like `337889` have no `+1` prefix and match fine. Regular phone numbers stored as `+15035550103` in `content://sms` need the Sender field to either include the `+1` (e.g., `+15035550103`) or be left empty (matches any sender). The Sender field does a substring/contains match.
- **`adb shell content query --where` with `+` prefix fails**: the `+` in phone numbers gets URL-mangled by the shell. To query for a number with `+1` prefix, query by `date` instead, or use an un-prefixed variant.
- **ADB can drive Termux via keystroke injection when direct file access fails — never give up on unreadable private files**: `adb shell am start -n com.termux/.app.TermuxActivity` to foreground, then `adb shell 'input text "cmd%sargs%s>%s/sdcard/out.txt"'` + `input keyevent ENTER`, `sleep`, then `adb pull /sdcard/out.txt`. Single-quote the outer adb arg so `>`/`&`/`|` inside the double quotes are typed literally into Termux instead of being eaten by the device shell; `%s` = space. Reverse direction: `adb push` a file to `/sdcard/`, then Termux reads it via `python src/main.py --json < /sdcard/file.txt` (stdin redirect also bypasses `isatty()`). This recovered the phone's `shift_automator_log.json`, git state, and replayed the real confirmation SMS to recreate the missing calendar event (2026-07-16, issue #48).
- **Termux `pkg` Python upgrades wipe pip site-packages silently**: symptom is sudden `ModuleNotFoundError` for previously-working deps (dateutil, requests, yaml...). Reinstall with `pip install -r requirements.txt`, EXCEPT `cryptography` — its pip source build fails (no rust toolchain); use `pkg install python-cryptography` (prebuilt) instead.
- **Native Tasker claim path masks a dead Python pipeline**: the claim SMS fires from Tasker itself (~400ms) even when `python` crashes on import — shifts get booked with zero log entries, zero pushes, zero calendar events. Detection: Tasker runlog shows `RunShiftBot ExitOK` but `shift_automator_log.json` has no matching entry → Python crashed before logging started (issue #48).
- **`data/shift-bot` reads SMS body from STDIN, not `$*`** (final state): Tasker's `RunShiftBot` (task43) dispatches `%SMSRB` via `com.termux.tasker.extra.STDIN` with `com.termux.execute.arguments: <null>`. The wrapper does `INPUT=$(cat)`, appends a fingerprint line to `~/.termux/tasker/shift-bot-runs.log`, flock-serializes (task43 collision = Run Both Together), then runs `python src/main.py --json --text "$INPUT"`. Python never sends a claim SMS — the claim record is Tasker's marker file (see Architecture Notes). Multi-line SMS bodies survive as a single argv via `--text "$INPUT"`. A version that reads `$*` silently gets empty input (the historical double-claim bug, issue #43-era).
- **Tasker condition op codes** (authoritative, from the tasker-automation skill): `op 0`=eq, `op 1`=ne, `op 2`=Matches (glob `~`), `op 3`=!Match (glob `!~`), `op 4`=~R (regex match), `op 5`=!~R (regex NOT-match), `op 12`=Is Set, `op 13`=NotSet. The existing task42 act1 c1 uses `op 3` with `*Building Lunch Coverage*` — that's a **glob** NOT-match, not regex. A common mistake is reading `op 3` as "regex match" (the handoff doc that diagnosed the 1am-accept bug had this wrong). Regex conditions use op 4 or op 5. Ops 6-11 are numeric only.

## GitHub Actions (opencode agent CI)

The repo's agent runs in CI via the official `anomalyco/opencode/github@latest` action. Four workflows live in `.github/workflows/`:

- **`opencode.yml`** — triggered by `/oc` or `/opencode` comments on issues or PRs. Runs on the issue/PR body + comment. This is the main interactive agent.
- **`opencode-issues.yml`** ("Issue Implement") — triggers on `issues: [labeled]`, fires ONLY when BOTH `ready-for-agent` AND `ticket` labels are present after a label-add event (order-tolerant). Uses the `/implement` skill methodology to implement the ticket and open a PR. This is the Grilling→Spec→Tickets→**Implement** gate.
- **`opencode-review.yml`** ("PR Review") — triggers on PR opened/sync/reopened/ready-for-review.
- **`opencode-scheduled.yml`** — weekly cron TODO sweep.

**Models**: primary `nvidia/z-ai/glm-5.2` (NVIDIA NIM provider `nvidia`, model id `z-ai/glm-5.2` — successor to glm-5.1 which was retired on the API in early July 2026, build card still resolves but the endpoint rejects it), with `nvidia/deepseek-ai/deepseek-v4-pro` as fallback (deepseek's NIM id was confirmed still current 2026-07-16). The action's `model` input is `provider/model` format; the first `/` splits provider from model id (NIM ids contain a slash, so `nvidia/z-ai/glm-5.2` is correct).

When upgrading models: the NIM model id can change across releases (publishers can publish a new successor card while retiring the old endpoint with no notice — GLM-5.1 → GLM-5.2 happened 07/02/2026 with the 5.1 endpoint silently 404'ing). Re-verify ids at `https://build.nvidia.com/models` after any "Model not found" CI error and update all 4 workflows + AGENTS.md.

**Fallback mechanism**: the action has NO native `fallback-model` input — `chat()` reads `MODEL` once. Fallback is implemented as a second step with `if: steps.primary.outcome == 'failure'`, with the primary step using `continue-on-error: true`. Caveat on `opencode.yml`: the primary step posts a `[Working...]` comment and (on failure) an error comment before the fallback step posts another `[Working...]` comment then the real result — slightly noisy but functional.

**Secret**: all workflows use `secrets.NVIDIA_API_KEY` (NVIDIA NIM trial key, base `https://integrate.api.nvidia.com/v1`). Set/refresh via repo Settings → Secrets and variables → Actions.

**Label gating** (triage labels are issues-only, not PRs):
- `opencode-issues.yml` (label trigger): fires ONLY when an issue has BOTH `ready-for-agent` AND `ticket` labels after a label-add event. `ready-for-agent` alone (specs / PRDs) does NOT fire — only tracer-bullet implementation tickets (carrying both labels) do. HITL (`ready-for-human`) and unlabeled issues never fire it.
- `opencode.yml` (comment trigger): requires `/oc`|`/opencode` AND (PR comment OR issue carrying `ready-for-agent` OR `ready-for-human`). HITL issues can still get one-shot agent help via an explicit `/oc`, but won't auto-run on open.
- PR review comments and PR issue-comments are not gated by triage labels.

**Why issue #41 auto-ran**: `opencode-issues.yml` previously fired on every `issues: [opened]` with no label gate, so #41 (opened already labeled `ready-for-agent`) triggered the agent and it created PR #42. First gated to the `ready-for-agent` label-add event via `issues: [labeled]`; then, on 2026-07-16, tightened further to require BOTH `ready-for-agent` AND `ticket` so that specs/PRDs carrying only `ready-for-agent` no longer fire the runner.

**Why the trigger requires both `ready-for-agent` AND `ticket` labels**: specs and PRDs themselves carry `ready-for-agent` (they're agent-readable) but should NOT auto-release the runner — only the tracer-bullet *tickets* derived from them should. The `ticket` label is the signal that "this issue is a single implementer-grabbable slice", distinguished from a spec/PRD that may require splitting first. Adding the two labels in any order fires the runner exactly once (whichever completes the pair triggers the gate); adding only one leaves the issue dormant.

**Why the trigger is `issues: [labeled]`, not `issues: [opened]`**: issues normally open unlabeled or `needs-triage`, then pass through Grilling→Spec→Tickets before the labels are applied. `issues: [opened]` would almost never fire because the labels are added later. `issues: [labeled]` is the correct trigger for the Implement phase.

**`opencode-issues.yml` is an implementation workflow**: its prompt asks the agent to implement the issue, run tests, and open a PR. The action auto-creates a branch + PR whenever the branch ends dirty — so a `ready-for-agent` + `ticket` issue yielding a real implementation PR (e.g. #41→PR#42) is the intended behavior. The prompt drives the `/implement` skill methodology (TDD at pre-agreed seams, regular typechecks, single-test sweeps, full sweep at end, handoff/compact across sessions).

## Tasker Configuration

- **Backup file locations**: `/sdcard/Tasker/configs/user/backup*.xml` is **project-scoped** (only the active project's tasks/profiles). `/sdcard/backup.xml` is the **full app** backup (all projects, all settings).
- **Runlog location**: `/sdcard/Tasker/log/runlog.txt` — pull with `adb pull`. Logs every action execution with error codes (`A Err`), task IDs, and timestamps. First place to check when a task silently fails.
- **HTTP Server 503 = sub-task error**: When Tasker's built-in HTTP Server routes a URL to a task and that task exits with any error, the server returns HTTP 503. The error is NOT descriptive — 503 looks like "server down" but actually means "the routed task failed." Pull the runlog to find the real error.
- **Global variable UI scoping**: `%UPPERCASE` global variables are accessible from any project at runtime, but the Variables tab only shows them when viewing the project where they were created. A global created in the Home project is invisible in the shift-automator project's Variables tab despite being usable by its tasks.
- **SIM slot in Tasker XML**: Hardcode `-s 1` in `termux-sms-send` commands, not a variable like `%STAFFING_NUMBER`. The SIM slot is constant per device (always slot 1 here). The Python pipeline reads `work_sim_sub_id` from config; Tasker XML has no equivalent config lookup.
- **Variable Set (code 547) arg5=3 means literal, arg5=0 means variable reference**: `arg5=3` treats arg1 as a literal string (e.g., `arg1="start_time"` sets the variable to `start_time`). `arg5=0` interprets arg1 as a variable/expression (e.g., `arg1="%SHIFT_JSON[start_time]"` resolves the JSON field). The `%SHIFT_START`/`%SHIFT_END` bug was `arg5=3` with literal strings — fixed by changing to `arg5=0` with `%SHIFT_JSON[start_time]`.
- **Tasker backup XML is canonical**: `data/tasker_backup.xml` is the authoritative copy of the phone's Tasker tasks. When Python JSON output changes, this file must be updated in the same commit. Deploy via `adb push data/tasker_backup.xml /sdcard/backupMM-DD.xml` (timestamped, e.g. `backup7-16.xml` for a 2026-07-16 deploy) then restore in Tasker — preserves known-good baselines.

## Commit Convention

- **Prefix with scope**: `core:` (backend logic), `docs:` (documentation/md files), `tui:` (terminal/CLI UX), `ci:` (automation/tooling), `wip:` (in-progress), `ignore:` (non-functional).
- **Describe WHY from end-user perspective**, not WHAT changed. Example: "core: simplify to binary accept/decline, remove manual confirm and ntfy action buttons" — explains the user-facing behavior change, not the code changes.

## Agent skills

### Issue tracker

GitHub Issues on `jitumaatgit/shift-automator` via `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Standard canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo. See `docs/agents/domain.md`.
