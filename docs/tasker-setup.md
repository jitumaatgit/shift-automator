# Shift Automator — Tasker Setup Guide

> ⚠️⚠️⚠️ **OUTDATED — NEEDS REWRITE** ⚠️⚠️⚠️  
> This guide documents the removed manual-confirm architecture (`MANUAL_CONFIRM`, `Accept Manual Shift`, `Keep Shift`, `Decline Shift` tasks, Tasker-owned calendar events).  
> The canonical Tasker config is `data/tasker_backup.xml`; the Tasker runlog is authoritative over anything written here. Do not rely on task lists or flow diagrams below.

Reference for AI configuring Tasker on the user's Android phone.

## Architecture

```
SMS arrives → Tasker catches SMS → pipes text to Python → Python scores + pushes ntfy notification
                                                                          ↓
                                                              ntfy notification arrives on phone
                                                                          ↓
                                                    Tasker shows notification with action buttons
                                                                          ↓
                                              User taps button → Tasker executes corresponding action
```

**Python owns:** parsing shift text, scoring rules, sending ntfy push, sending accept SMS (via termux-sms-send)
**Tasker owns:** SMS intercept, notification display, button action dispatch, 5-min auto-cancel timer, calendar event create/delete, phone dialing

Python exits after pushing ntfy. No background Python process. All ongoing logic = Tasker.

---

## Profiles Needed

### Profile 1: SMS Received (Shift Offer)

- **Trigger:** Event → Phone → Received SMS
- **Sender filter:** `337889` (staffing shortcode)
- **Task:** `Parse Shift Offer` (see below)

### Profile 2: Ntfy Notification Received

- **Trigger:** Event → Plugin → Ntfy → Notification Received
- **Channel:** `YOUR_SECRET_NTFY_TOPIC`
- **Task:** `Display Shift Notification` (see below)

This is how Tasker learns about the decision and offer details. Python includes all relevant data in the ntfy message body and JSON payload.

---

## Tasks Needed

### Task: `Parse Shift Offer`

Runs when staffing SMS arrives.

1. **Run Shell:**
   ```
   python /path/to/shift-automator/src/main.py --text "%SMSRB" --json --config /path/to/shift-automator/config.yaml
   ```
   - `%SMSRB` = SMS body text (Tasker variable)
   - `--json` flag outputs structured result

2. **Parse JSON output** → set Tasker variables. The Python `--json` output includes these fields. **All must be extracted** — the `Accept Manual Shift` task's Calendar Insert action requires `%SHIFT_START` and `%SHIFT_END`:
   - `%SHIFT_DECISION` = `decision` field (auto_accept / manual_confirm / auto_decline)
   - `%SHIFT_TITLE` = `title`
   - `%SHIFT_BUILDING` = `category` (building name)
   - `%SHIFT_START` = `start_time` ← **REQUIRED for Calendar Insert**
   - `%SHIFT_END` = `end_time` ← **REQUIRED for Calendar Insert**
   - `%SHIFT_DURATION` = `duration_hours`
   - `%SHIFT_CLAIM_CODE` = `claim_code`
   - `%SHIFT_CANCEL_NUM` = `cancel_number`
   - `%SHIFT_ADDRESS` = `address`
   - `%SHIFT_SCORE` = `score`
   - `%SHIFT_REASONS` = `reasons` (joined)
   - `%SHIFT_EVENT_ID` = `calendar_event_id` (may be null for manual_confirm)

   Use **JSON Read** action or **Variable Set** + **Variable Search Replace** to extract fields. With JSON Read: enable **Structured Output** and set the variable name (e.g., `%parsed`), then access individual fields with dot notation (`%parsed.start_time`).

3. **If `%SHIFT_DECISION` = `auto_accept`:**
   - Python already sent accept SMS + created calendar event
   - Ntfy push already sent with CALL + KEEP buttons
   - Start 5-min cancel timer: **Wait** 300s then run `Auto Cancel Shift`

4. **If `%SHIFT_DECISION` = `manual_confirm`:**
   - Ntfy push already sent with ACT + DEC buttons
   - No timer needed

5. **If `%SHIFT_DECISION` = `auto_decline`:**
   - Nothing to do

### Task: `Display Shift Notification`

Runs when ntfy notification arrives. Tasker intercepts ntfy to show a rich notification with action buttons.

1. **Create Notification** with:
   - Title: `%SHIFT_TITLE` at `%SHIFT_BUILDING`
   - Body: Score: `%SHIFT_SCORE` | `%SHIFT_START` - `%SHIFT_END` (%SHIFT_DURATION h)
   - Action buttons depend on decision:

   **If AUTO_ACCEPT:**
   - Button 1: "CALL" → runs `Cancel Shift Via Call`
   - Button 2: "KEEP" → runs `Keep Shift`

   **If MANUAL_CONFIRM:**
   - Button 1: "ACCEPT" → runs `Accept Manual Shift`
   - Button 2: "DECLINE" → dismiss notification only (no SMS to shortcode)

### Task: `Accept Manual Shift`

Runs when user taps ACCEPT on a MANUAL_CONFIRM notification.

1. **Run Shell:**
   ```
   termux-sms-send -n 337889 "%SHIFT_CLAIM_CODE"
   ```
   Only the claim code is sent to the shortcode. Nothing else. If Termux prompts which SIM to use, add `-s 0` before `-n` (matches `work_sim_sub_id` in config.yaml).

2. **Create Calendar Event** (via Tasker built-in **Calendar Insert** action):
   - Title: `[CC] %SHIFT_TITLE - %SHIFT_ADDRESS`
   - Begin: `%SHIFT_START`
   - End: `%SHIFT_END`
   - Description: `Building: %SHIFT_BUILDING Claim Code: %SHIFT_CLAIM_CODE`

   **Or** via Run Shell:
   ```
   termux-calendar-insert --title "[CC] %SHIFT_TITLE - %SHIFT_ADDRESS" --begin "%SHIFT_START" --end "%SHIFT_END" --description "Building: %SHIFT_BUILDING\nClaim Code: %SHIFT_CLAIM_CODE"
   ```

3. **Start 5-min cancel timer:** Wait 300s then run `Auto Cancel Shift`

4. **Dismiss notification**

### Task: `Cancel Shift Via Call`

Runs when user taps CALL on an AUTO_ACCEPT notification (wants to cancel by calling dispatch).

1. **Run Shell:**
   ```
   termux-telephony-call +15035550101
   ```
   (This is the dispatch number from config. Store in global `%DISPATCH_NUMBER`.)

2. **Delete Calendar Event** (if `%SHIFT_EVENT_ID` is set):
   - Use Tasker's **Calendar Delete** action or:
   ```
   termux-calendar-delete --event-id "%SHIFT_EVENT_ID"
   ```

3. **Cancel 5-min timer** (stop the pending Wait)

4. **Dismiss notification**

### Task: `Keep Shift`

Runs when user taps KEEP on an AUTO_ACCEPT notification (wants to keep the accepted shift).

1. **Cancel 5-min timer** (stop the pending Wait)
2. **Dismiss notification**

### Task: `Auto Cancel Shift`

Runs automatically after 5-min timer expires (user didn't tap KEEP or CALL).

1. **Run Shell:**
   ```
   termux-telephony-call +15035550101
   ```
2. **Delete Calendar Event** (if event ID available)
3. **Send ntfy push:**
   ```
   curl -H "Priority: urgent" -H "Title: Shift Auto-Cancelled" -d "5-min window expired. Calling dispatch to cancel %SHIFT_TITLE." ntfy.sh/YOUR_SECRET_NTFY_TOPIC
   ```
4. **Dismiss notification**

### Task: `Decline Shift`

Runs when user taps DECLINE on a MANUAL_CONFIRM notification.

1. **Dismiss notification** — that's it. No SMS sent to shortcode. No action taken.

---

## Global Variables

Set these once in Tasker → Vars tab:

| Variable | Value | Notes |
|---|---|---|
| `%DISPATCH_NUMBER` | `+15035550101` | Main dispatch number for cancel calls |
| `%STAFFING_NUMBER` | `337889` | Shortcode for shift claim codes |
| `%PYTHON_PATH` | `/data/data/com.termux/files/usr/bin/python` | Termux Python |
| `%PROJECT_DIR` | `/data/data/com.termux/files/home/shift-automator` | Project location |
| `%NTFY_CHANNEL` | `YOUR_SECRET_NTFY_TOPIC` | ntfy channel for push notifications |
| `%TASKER_BASE_URL` | `http://localhost:8080` | Tasker HTTP Server for action button callbacks |

---

## Python CLI Commands (Reference)

Tasker calls these via **Run Shell** action. Working directory = `%PROJECT_DIR`.

### Process incoming shift SMS
```bash
%PYTHON_PATH src/main.py --text "%SMSRB" --json --config config.yaml
```
Returns JSON with: decision, score, title, category, start_time, end_time, duration_hours, claim_code, cancel_number, calendar_event_id, address, reasons, actions, dry_run

### Send accept SMS for a specific claim code
```bash
%PYTHON_PATH src/main.py --send-accept "CLAIMCODE" --config config.yaml
```

### Dial dispatch
```bash
%PYTHON_PATH src/main.py --call --config config.yaml
```

### Cancel pending timers (keep shift)
```bash
%PYTHON_PATH src/main.py --keep --config config.yaml
```

### Handle reply action
```bash
%PYTHON_PATH src/main.py --reply "CALL" --reply-offer-json '%SHIFT_JSON%' --config config.yaml
```
Valid reply values: `YES`, `NO`, `ACCEPT`, `CANCEL`, `CALL`, `KEEP`

### Health check Tasker HTTP Server
```bash
%PYTHON_PATH src/main.py --check-tasker --config config.yaml
```
Automator checks Tasker reachability at startup. Logs warning if unreachable (action buttons won't work).

---

## Ntfy Notification Format

Python sends ntfy push using JSON API mode. Example payloads:

### AUTO_ACCEPT notification
```json
{
  "topic": "YOUR_SECRET_NTFY_TOPIC",
  "priority": 4,
  "title": "AUTO-ACCEPTED",
  "message": "⚠️ CALL to cancel within 5 min. KEEP to keep.",
  "actions": [
    {"action": "http", "label": "CALL", "url": "http://localhost:8080/call?code=CLAIMCODE"},
    {"action": "http", "label": "KEEP", "url": "http://localhost:8080/keep?code=CLAIMCODE"}
  ]
}
```

### MANUAL_CONFIRM notification
```json
{
  "topic": "YOUR_SECRET_NTFY_TOPIC",
  "priority": 3,
  "title": "MANUAL CONFIRM REQUIRED",
  "message": "ACT to accept. DEC to decline.",
  "actions": [
    {"action": "http", "label": "ACT", "url": "http://localhost:8080/accept?code=CLAIMCODE"},
    {"action": "http", "label": "DEC", "url": "http://localhost:8080/decline?code=CLAIMCODE"}
  ]
}
```

> **Note:** Python POSTs to `https://ntfy.sh/` (root) with JSON body including `"topic"`. Action buttons POST back to Tasker HTTP Server at `tasker_base_url` (default `http://localhost:8080`).

---

## Important Design Decisions

### Why Python doesn't own timers
Python runs as a short-lived process (`python main.py ...`). When it exits, `threading.Timer` objects die. Tasker's persistent process is the only reliable place for user-facing timers.

### Why only claim codes go to shortcode
The staffing system at `337889` only accepts claim codes. Sending anything else (like "CANCEL" or "NO") is ignored or causes errors. Acceptance = sending the claim code. Decline = sending nothing.

### Why dry-run still reads calendar
Python's `dry_run` mode prevents writes (no SMS sent, no calendar events created) but still reads calendar data for accurate scoring. This way dry-run scores match real-run scores.

### Why ntfy instead of direct SMS
ntfy.sh provides action buttons, priority levels, and works without a phone number. The personal SMS channel is reserved for accept confirmations only.

### Why Tasker handles calendar events
Python creates calendar events during AUTO_ACCEPT. But Tasker needs to be able to delete them (CALL/CANCEL) and create them (ACCEPT on MANUAL_CONFIRM). If Tasker creates the event, it also owns the event ID for later deletion. This avoids coordination problems.

### Calendar caching
Python caches calendar events in `calendar_cache.json` with 60s TTL. If multiple shift texts arrive within 60 seconds, the second invocation reads from cache instead of hitting Google Calendar API again. This reduces latency from ~3s (3 API calls) to ~50ms (1 API call + local filters).

---

## Troubleshooting

| Problem | Check |
|---|---|
| SMS not intercepted | Profile sender filter = `337889`, Tasker has SMS permissions |
| ntfy not received | Install ntfy app, subscribe to channel `YOUR_SECRET_NTFY_TOPIC` |
| `termux-sms-send` fails | Run `pkg install termux-api`, grant SMS permission to Termux |
| `termux-telephony-call` fails | Grant phone permission to Termux: `Settings → Apps → Termux → Permissions → Phone` |
| Python not found | Set `%PYTHON_PATH` to Termux Python binary location |
| Calendar event not created | Check `credentials.json` exists in project dir, service account has write access |
| Timer not firing | Tasker must be running (not killed by battery optimization). Add Tasker to battery optimization whitelist. |

---

## File Locations on Phone (Termux)

```
/data/data/com.termux/files/home/shift-automator/
├── src/main.py           # CLI entry point
├── src/config.py         # Config loading + defaults
├── src/rules.py          # Scoring rules engine
├── src/parser.py         # SMS text parser
├── src/models.py         # Data classes (ShiftOffer, etc.)
├── src/calendar_client.py # Google Calendar client
├── src/responder.py      # SMS + ntfy notifications
├── config.yaml           # Live configuration
├── credentials.json      # Google service account key
├── calendar_cache.json   # Cached calendar events (auto-generated)
├── shift_automator_log.json  # Decision log
└── tasker-setup.md       # This file
```
