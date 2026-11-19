# Shift Automator

> ⚠️⚠️⚠️ **OUTDATED — NEEDS REWRITE** ⚠️⚠️⚠️  
> This README references removed features (`MANUAL_CONFIRM`, `force_accept`, `auto_accept_threshold`).  
> See `AGENTS.md` and `docs/` for current architecture. Do not rely on config examples or flow diagrams.

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3c873a?style=flat-square)
[![Tests](https://img.shields.io/badge/tests-86%20passing-brightgreen?style=flat-square)](./tests/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](./LICENSE)

**Automated shift-offer decision engine for Android** — parses incoming SMS, scores against configurable rules, checks Google Calendar, and auto-accepts within 3 seconds. No background process needed.

[Overview](#overview) • [Quick Start](#quick-start) • [Config](#configuration) • [Android Setup](#android-deployment) • [Commands](#cli-reference)

</div>

---

## Overview

Shift Automator runs on an Android phone through **Termux + Tasker**. When your staffing agency texts a shift offer, Tasker pipes the SMS to Python, the rules engine scores it against your preferences and calendar, and a claim code is sent back — all in under 3 seconds.

For shifts that don't auto-accept, you get an **ntfy push notification** with action buttons (Accept / Decline / Call to cancel / Keep). One tap dispatches your decision.

The project is **stateless** — Python exits after each invocation. Tasker handles SMS interception, notification display, and button dispatch. No background Python loop that Android can kill.

```text
SMS arrives → Tasker catches → Python scores (10ms) → claim code sent (~2s) → ntfy push (~1s)
                                                                                       ↓
                                                                     Tasker shows notification with action buttons
```

---

## Quick Start

### Install

```bash
pip install -r requirements.txt
```

On Termux, use the system packages where available:

```bash
pkg install python python-pip python-pyyaml python-pytest python-requests termux-api -y
pip install python-dateutil google-api-python-client tzdata
```

### Test

```bash
# All 33 tests (requires google-api-python-client)
pytest tests/ -v

# Parser + rules only (22 tests, no Google deps)
pytest tests/test_parser.py tests/test_rules.py -v
```

### Run

```bash
# Process a sample shift (dry-run, no API calls)
python src/main.py --sample 1

# Process raw text with JSON output (for Tasker)
python src/main.py --json --text "Open shift available at [Estate - FD] ..."

# Pipe from stdin
echo "Open shift..." | python src/main.py
```

> [!NOTE]
> `credentials.json` (Google service account key) is only needed for live calendar access. Dry-run mode works without it — set `dry_run: true` in `config.yaml` for testing.

---

## How It Works

```text
┌────────────┐
│ Incoming SMS│
└─────┬──────┘
      │
  ┌───▼────┐    ┌───────────┐    ┌────────────┐
  │ Parser  │───▶│   Rules    │───▶│  Responder  │
  │ (regex) │    │  Engine    │    │ (SMS + Push)│
  └───┬─────┘    └─────┬─────┘    └────────────┘
      │                │
  ┌───▼─────┐    ┌─────▼──────┐
  │ Calendar│    │ ntfy Push   │
  │ Check   │    │ Notification│
  └─────────┘    └────────────┘
```

### Pipeline (`src/pipeline.py`)

1. **Classify**: Is this an offer, confirmation, or rejection SMS?
2. **Parse**: Extract building, title, times, address, claim code, shift notes (regex-based, 4 formats supported)
3. **Score**: 10 configurable rules evaluate the shift, producing a weighted score
4. **Decide**: AUTO_ACCEPT (≥4.5), MANUAL_CONFIRM (-3.0 to 4.5), or AUTO_DECLINE (≤-3.0)
5. **Act**: Send accept SMS (fire-and-forget) + ntfy push with action buttons

### Rules Engine (`src/rules.py`)

| Rule | What it checks |
|------|---------------|
| `force_accept` | Building + role combos that auto-accept instantly (with optional hour exclusions + calendar conflict check) |
| `parsing_quality` | Penalty for parser issues (missing times, unknown building, unparsed address) |
| `calendar_conflict` | Hard overlap with existing Google Calendar events → VETO_DECLINE |
| `location_preference` | Liked/disliked buildings — matches both address text AND bracket building name |
| `shift_type_preference` | Per-building base score (e.g., `Larry Naito: 3.0`, `Medford: 0.5`) |
| `title_preference` | Role-based scoring (`FD: 3.0`, `J1: 1.0`, `CBA: 1.0`) + partial keyword matching |
| `time_of_day` | Bonus for preferred hours (6-18), veto for undesired (22-5) |
| `minimum_rest` | Penalty if < 2h rest between this shift and adjacent calendar events |
| `weekly_hours_cap` | Veto if this shift would push you over 40h for the shift's week |
| `duration_preference` | Penalty for shifts < 4h or > 10h |

All weights, thresholds, and preference lists live in `config.yaml`. No code changes needed to tune behavior.

### Supported Shift Formats (`src/parser.py`)

| Format | Bracket | Type |
|--------|---------|------|
| Building shifts | `[Estate - FD]`, `[STS]`, `[8x8 - Front Desk]` | Single-site with role + address |
| Special Projects | `[Special Projects]` | Single-site, contact info in note |
| Building Lunch Coverage | `[Building Lunch Coverage]` | Multi-site, multiple addresses + break schedule |
| Building Lockout | `[Building Lockout]` | Single-site, lockout contact or provider phone in note |

40+ known buildings across Portland, OR — all recognized from bracket text. Parser searches all lines for the header, so forwarded texts with prefix lines still parse correctly.

---

## Configuration

All behavior is controlled through `config.yaml`. Key sections:

```yaml
# Decision thresholds
auto_accept_threshold: 4.5
auto_decline_threshold: -3.0

# Instant-accept favorite shifts (building + role combos)
force_accept:
  - building: "Larry Naito"
    title: "Front Desk"
    exclude_start_hours:
      - [22, 24]   # don't auto-accept overnights
      - [0, 7]

# Location preferences (matched against address AND bracket building name)
location_preferences:
  liked:
    - "Estate"
    - "Larry Naito"
    - "HRR"
  disliked:
    - "Medford"

# Per-building base scores
shift_type_preferences:
  Larry Naito: 3.0
  HRR: 2.0
  Estate: 2.0
  Medford: 0.5

# Role (title) scores
title_preferences:
  FD: 3.0       # Front Desk
  J1: 1.0       # Janitorial
  CBA: 1.0

# Title keyword partial matches
title_keywords:
  "Front Desk": 3.0
  "Janitorial": 1.0

# Time preferences
preferred_hours:
  - [6, 18]
undesired_hours:
  - [0, 5]
  - [22, 24]
veto_undesired_hours: true

# Active rules (order matters — first veto wins)
active_rules:
  - force_accept
  - parsing_quality
  - calendar_conflict
  - location_preference
  - shift_type_preference
  - title_preference
  - time_of_day
  - minimum_rest
  - duration_preference

# Phone numbers
staffing_number: "337889"          # CC Staffing's shortcode
personal_number: "+15035550100"    # Your number for personal SMS
work_sim_sub_id: "0"               # SIM slot for outgoing SMS

# ntfy push notifications
ntfy_channel: "YOUR_SECRET_NTFY_TOPIC"
tasker_base_url: "http://localhost:8080"
cancel_warning_seconds: 300        # Auto-cancel timer (5 min)

# Google Calendar
calendar_id: "your-email@gmail.com"
calendar_credentials_path: "credentials.json"
calendar_timezone: "America/Los_Angeles"
calendar_cache_ttl_seconds: 86400  # 24h cache
```

> [!TIP]
> **`force_accept.building` must match the parser output**, not the `shift_type_preferences` key. Bracket `[8x8 - Front Desk]` parses to building `"8x8"`, so use `building: "8x8"` — not `"Golden West/8x8"`.

---

## Android Deployment

Runs on a single physical Android phone with dual SIMs. **Tasker** is the SMS listener (never killed), **Termux** runs the Python pipeline.

### Setup Steps

1. **Install apps**: Termux, Termux:Tasker, Termux:API, Tasker (use F-Droid)
2. **Clone into Termux private home** (not `/sdcard/` — FUSE is slow and exposes secrets):

   ```bash
   # From within Termux:
   cd ~ && git clone https://github.com/jitumaatgit/shift-automator.git
   cd shift-automator && pip install -r requirements.txt
   ```

3. **Find SIM slot**: Test which SIM sends from your staffing number:

   ```bash
   termux-sms-send -s 1 -n <YOUR_PERSONAL> "test sim 1"
   termux-sms-send -s 2 -n <YOUR_PERSONAL> "test sim 2"
   ```

   Set `work_sim_sub_id: "1"` or `"2"` in `config.yaml`.

4. **Create Tasker wrapper** (`~/.termux/tasker/shift-bot`):

   ```bash
   #!/data/data/com.termux/files/usr/bin/bash
   cd /data/data/com.termux/files/home/shift-automator
   python src/main.py --json --text "$*"
   ```

5. **Tasker profile**: Event → Phone → Received Text (Sender: `staffing_number` from config)
6. **Tasker task**: Plugin → Termux:Tasker → Executable: `shift-bot`, stdin: `%SMSRB`
7. **Battery**: Set Tasker + Termux to **Unrestricted** in Android app settings

> [!IMPORTANT]
> Termux files cannot be verified via ADB (`Permission denied`). The `shift-bot` wrapper must be created directly in the Termux app, not pushed via ADB.

### Expected Flow

```text
0s    SMS arrives, Tasker intercepts
0s    Python pipeline starts (~10ms parse + rules)
2s    Claim code SMS sent (fire-and-forget thread)
3s    ntfy push delivered with action buttons
5min  Auto-cancel timer starts (configurable)
```

---

## Google Calendar Setup

Uses a **service account** — no browser auth, no token expiry, portable.

1. Create a GCP project, enable **Google Calendar API**
2. Create a service account, download JSON key as `credentials.json`
3. Share your calendar with the service account email (give **"Make changes and manage sharing"** permission)
4. Set `calendar_id` to your Gmail in `config.yaml`

> [!WARNING]
> Never commit `credentials.json`. It's already in `.gitignore`.

What the calendar enables:

- **Conflict detection** — veto shifts that overlap existing events
- **Rest gap enforcement** — penalize shifts with insufficient rest between adjacent events
- **Weekly hours tracking** — veto overtime past 40h for the shift's week
- **Event CRUD** — add booked shifts, delete cancelled shifts, 1-hour popup reminder

### Cache refresh

Calendar events are cached for 24 hours. For fresher data, deploy the 30-minute auto-refresh:

```bash
# In Termux, create the refresh wrapper:
cat > ~/.termux/tasker/shift-bot-refresh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd /data/data/com.termux/files/home/shift-automator
python src/main.py --refresh-cache
EOF
chmod +x ~/.termux/tasker/shift-bot-refresh
```

Then import `data/tasker_refresh_cache.xml` in Tasker (adds a Time profile that runs every 30 min).

---

## CLI Reference

```bash
# Process a sample shift by ID
python src/main.py --sample 1

# Process raw text (human-readable output)
python src/main.py --text "Open shift available at [Special Projects] ..."

# JSON output (for Tasker / automation)
python src/main.py --json --text "..."

# Send accept SMS directly (manual override)
python src/main.py --send-accept "CLAIM-CODE-123"

# Handle user reply (YES/NO/CANCEL/KEEP/CALL)
python src/main.py --reply YES --reply-offer-json '{"title":"FD","building":{"value":"Estate"},"start_time":"2025-06-01T08:00:00","end_time":"2025-06-01T16:00:00"}'

# Refresh calendar cache
python src/main.py --refresh-cache

# Dial dispatch (cancel current shift)
python src/main.py --call

# Keep shift (cancel pending timers)
python src/main.py --keep
```

### JSON Output Fields

```json
{
  "decision": "AUTO_ACCEPT",
  "score": 6.0,
  "elapsed_ms": 3.2,
  "title": "FD",
  "category": "Estate",
  "start_time": "2025-06-01T08:00:00",
  "end_time": "2025-06-01T16:00:00",
  "start_epoch": 1717239600,
  "end_epoch": 1717268400,
  "duration_hours": 8.0,
  "claim_code": "ABC123",
  "cancel_number": "5035550123",
  "calendar_event_id": null,
  "address": "123 NW Main St",
  "reasons": ["force_accept: instant accept"],
  "actions": ["sent: accept text", "sent: pending confirmation push"],
  "dry_run": false
}
```

---

## Testing

```bash
# All tests
pytest tests/ -v

# Parser + rules subset (no Google deps needed)
pytest tests/test_parser.py tests/test_rules.py -v

# Single test
pytest tests/test_rules.py::test_force_accept -v
```

Tests use **real shift texts** from `data/sample_shifts.md` (41+ samples spanning all 4 formats). Calendar tests mock the Google API — no network calls in CI.

---

## Performance

| Mode | Pipeline time | Notes |
|------|--------------|-------|
| Dry-run | 2–10ms | Parser + rules only, no API calls |
| Production (cached) | ~100ms | Calendar cache hit + SMS send |
| Production (uncached) | 3–6s | Full calendar API fetch |

All within the 10-second SMS reply window. Most latency is SMS transit (~2s) and user notification latency (~1s).

---

## Project Structure

```
src/
  main.py              CLI entry point, text routing
  pipeline.py          Process orchestration: classify → parse → score → act
  parser.py            Regex parsers for 4 shift formats + confirmation/rejection
  models.py            Frozen dataclasses (ParsedOffer, ScoredOffer, ShiftBuilding enum)
  rules.py             Rules engine: 10 configurable rules with SCORE/VETO actions
  config.py            Config loading with deep-copied defaults → frozen Config dataclass
  calendar_client.py   Google Calendar API (auth, conflict detection, event CRUD, cache)
  responder.py         SMS (stub/Termux/Twilio) + ntfy push notifications
tests/
  test_parser.py       41+ samples, format validation
  test_rules.py        Rule scoring scenarios
  test_calendar.py     Mocked calendar API tests
  test_config.py       Config loading and defaults
  test_pipeline.py     End-to-end pipeline tests
  test_presenter.py    Output formatting
data/
  sample_shifts.md     Synthetic shift texts (sample corpus, no real PII)
  tasker_backup.xml    Tasker task/project backup
  tasker_refresh_cache.xml  Tasker 30-min calendar refresh profile
config.yaml            All thresholds, preferences, and rules
```

---

## Extending

### Add a new rule

```python
from rules import RuleResult, RuleAction

def rule_my_check(offer, config, calendar, parse_errors=None):
    if "keyword" in offer.shift_note:
        return RuleResult("my_rule", RuleAction.VETO_DECLINE, -100, "Bad keyword")
    return RuleResult("my_rule", RuleAction.SCORE, 0, "Clean")
```

Then add `"my_rule"` to `active_rules` in `config.yaml`.

### Add a new SMS transport

Implement the `SMSResponder` protocol in `responder.py` and register with `register_responder(name, factory)`.

---

## Logging

Every pipeline run logs a JSON line to `shift_automator_log.json` (set `log_file: ""` in config to disable). Includes decision, score, reasons, elapsed ms, and raw SMS preview (on parse failures only).
