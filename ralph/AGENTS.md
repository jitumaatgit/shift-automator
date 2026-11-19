# Ralph — AFK Coding Loop (shift-automator)

## Script path resolution

Scripts must resolve `prompt.md` relative to their own directory, not CWD.

```bash
script_dir="$(cd "$(dirname "$0")" && pwd)"
prompt=$(cat "$script_dir/prompt.md")
```

## Issue integration (local files)

Issues stored as `issues/*.md` markdown files. Completed tasks moved to `issues/done/`.

## opencode run

Uses `--dangerously-skip-permissions` for auto-approve. `OPENCODE_SERVER_PASSWORD` (exported by OpenCode Desktop, inherited by child shells) must stay SET — `opencode run` authenticates against the running server with it. Do NOT unset (old #24747 advice is obsolete as of 1.17.18; see `~/.config/opencode/AGENTS.md` "OpenCode Server Auth"). Single-run via `once.sh`, loop via `afk.sh <iterations>`.

## Feedback loops

`pytest tests/ -v` before commit. Prompt in `prompt.md` enforces this.

## Stop signal

Agent outputs `NO MORE TASKS` when all issues complete. `afk.sh` detects this phrase and exits the loop.
