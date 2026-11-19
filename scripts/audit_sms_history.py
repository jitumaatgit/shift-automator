"""Retroactive audit of past shift offers scored against the CURRENT config.

Reconstructs an offer-by-offer chronology from termux-sms-list JSON exports
(filtered to the staffing shortcode), scores each offer with the rules engine
as configured today, and flags rows where the deployed behavior diverged from
what the current policy would do.

Usage:
    python scripts/audit_sms_history.py INBOX.json SENT.json [--out report.md]

Inputs are `termux-sms-list` JSON arrays:
    termux-sms-list -t inbox -l 500   (filter to address 337889)
    termux-sms-list -t sent  -l 500   (filter to address 337889)

This script NEVER constructs a Responder: no SMS, no pushes, no side effects.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Repo modules live flat under src/; make them importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

CLAIM_RE = re.compile(r"reply\s+(\d{5,8})")
CONFIRM_PREFIXES = ("Congratulations", "congratulations")
REJECT_PREFIXES = ("Sorry", "sorry", "We're sorry", "we're sorry")


def _ts_ms(record: dict) -> int:
    """termux-sms-list yields 'received'/'sent' as 'YYYY-MM-DD HH:MM:SS' (device-local)."""
    for key in ("received", "sent", "time"):
        if key in record and record[key]:
            val = record[key]
            if isinstance(val, (int, float)):
                return int(val)
            try:
                return int(datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S").timestamp())
            except ValueError:
                continue
    return 0


def _body(record: dict) -> str:
    return record.get("body", "") or record.get("thread", "") or ""


def filter_shortcode(records: List[dict], address: str = "337889") -> List[dict]:
    out = []
    for r in records:
        haystack = f'{r.get("thread", "")} {r.get("number", "")} {r.get("address", "")}'
        if address in haystack:
            out.append(r)
    return out


def build_chronology(inbox: List[dict], sent: List[dict]) -> List[dict]:
    """Return per-offer dicts: offer, claims, confirmations, rejections."""
    offers: List[dict] = []

    for msg in sorted(inbox, key=_ts_ms):
        body = _body(msg)
        m = CLAIM_RE.search(body)
        if not m:
            continue
        offers.append(
            {
                "offer_raw": body,
                "offer_ts": _ts_ms(msg),
                "code": m.group(1),
                "claims": [],
                "confirmations": [],
                "rejections": [],
            }
        )

    for msg in sorted(sent, key=_ts_ms):
        body = _body(msg).strip()
        if not body.isdigit() or not (5 <= len(body) <= 8):
            continue
        ts = _ts_ms(msg)
        for off in offers:
            if off["code"] == body and 0 <= ts - off["offer_ts"] <= 30 * 60:
                off["claims"].append(ts)
                break

    # Link confirmation/rejection messages to the offer whose CLAIM most
    # recently preceded them. The shortcode's reply bodies ("Congratulations!
    # You are now booked to do shift [X] ...", "Sorry this shift has already
    # been taken ...") never contain the claim code, so code-in-body matching
    # would miss every reply; nearest-claim linkage is unambiguous because
    # replies arrive seconds after the claim that triggered them.
    REPLY_LINK_WINDOW = 15 * 60  # seconds between claim and its reply
    BUILDING_RE = re.compile(r"\[([^\]]+)\]")

    def link_reply(ts: int, body: str) -> Optional[int]:
        # Replies name the shift's building ("Congratulations! ... [X] ..."),
        # offers do too; equality on that tag is the primary key, claim
        # proximity the tiebreaker (in bursts, several claims may sit within
        # the window of a single reply).
        body_b = BUILDING_RE.search(body)
        body_tag = body_b.group(1) if body_b else None
        candidates = []
        for i, off in enumerate(offers):
            for c in off["claims"]:
                d = ts - c
                if 0 <= d <= REPLY_LINK_WINDOW:
                    tag_eq = False
                    if body_tag is not None:
                        m = BUILDING_RE.search(off["offer_raw"])
                        tag_eq = m is not None and m.group(1) == body_tag
                    candidates.append((not tag_eq, d, c, i))
        if not candidates:
            return None
        candidates.sort(key=lambda t: (t[0], t[1], t[2]))
        return candidates[0][3]  # first: tag-equal, then min claim distance

    for msg in sorted(inbox, key=_ts_ms):
        body = _body(msg)
        ts = _ts_ms(msg)
        if body.startswith(CONFIRM_PREFIXES):
            best = link_reply(ts, body)
            if best is not None:
                offers[best]["confirmations"].append(ts)
        elif body.startswith(REJECT_PREFIXES):
            best = link_reply(ts, body)
            if best is not None:
                offers[best]["rejections"].append(ts)

    return offers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inbox_json", help="termux-sms-list inbox JSON")
    ap.add_argument("sent_json", help="termux-sms-list sent JSON")
    ap.add_argument("--out", default="audit_report.md", help="report output path")
    args = ap.parse_args()

    with open(args.inbox_json, encoding="utf-8") as f:
        inbox = json.load(f)
    with open(args.sent_json, encoding="utf-8") as f:
        sent = json.load(f)

    inbox = filter_shortcode(inbox)
    sent = filter_shortcode(sent)

    chronology = build_chronology(inbox, sent)
    if not chronology:
        print("No offers found after filtering to 337889.", file=sys.stderr)
        return 1

    import config as cfg
    from parser import parse_with_fallback
    from rules import RulesEngine
    from calendar_client import CalendarClient, CalendarError

    conf = cfg.load_config("config.yaml")
    calendar = CalendarClient(
        calendar_id=conf.calendar_id,
        credentials_path=conf.calendar_credentials_path,
        timezone=conf.calendar_timezone,
        dry_run=True,
        cache_ttl_seconds=conf.calendar_cache_ttl_seconds,
    )
    caveat = ""
    try:
        calendar.authenticate()
    except CalendarError as e:
        caveat = (
            f"\n> **Caveat:** calendar auth failed ({e}); conflict/hours rules ran blind "
            "(weekly hours reads as 0.0)."
        )
        print(f"Calendar auth failed: {e}", file=sys.stderr)

    engine = RulesEngine(conf, calendar=calendar)
    known_buildings = set(conf.shift_type_preferences.keys())

    rows = []
    for off in chronology:
        parsed, errors = parse_with_fallback(off["offer_raw"], known_buildings=known_buildings)
        scored = engine.evaluate(parsed, parse_errors=errors)
        n_claims = len(off["claims"])
        outcome = "confirmed" if off["confirmations"] else "rejected" if off["rejections"] else "no-reply"
        flags = []
        if n_claims > 1:
            flags.append("DOUBLE_CLAIM")
        decision_value = scored.decision.value
        if n_claims >= 1 and decision_value == "auto_decline":
            flags.append("CLAIMED_BUT_DECLINE")
        if n_claims == 0 and decision_value == "auto_accept":
            flags.append("NOT_CLAIMED_BUT_ACCEPT")
        rows.append(
            {
                "ts": off["offer_ts"],
                "when": datetime.fromtimestamp(off["offer_ts"]).strftime("%Y-%m-%d %H:%M"),
                "building": parsed.building,
                "title": parsed.title,
                "start": parsed.start_time.strftime("%a %m/%d %H:%M") if parsed.start_time and parsed.start_time.year > 2000 else "",
                "score": f"{scored.score:.1f}",
                "decision": decision_value,
                "claims": n_claims,
                "outcome": outcome,
                "flags": ",".join(flags) or "-",
            }
        )

    rows.sort(key=lambda r: r["ts"])
    lines = [
        "# Shift Offer Audit",
        "",
        f"Scored against current config at {datetime.now().isoformat(timespec='minutes')}.",
        caveat,
    ]
    lines += [
        "",
        "| Date | Building | Title | Start | Score | Decision | Claims | Outcome | Flags |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['when']} | {r['building']} | {r['title']} | {r['start']} | {r['score']} | "
            f"{r['decision']} | {r['claims']} | {r['outcome']} | {r['flags']} |"
        )
    total = len(rows)
    n_double = sum(1 for r in rows if "DOUBLE_CLAIM" in r["flags"])
    n_decline = sum(1 for r in rows if "CLAIMED_BUT_DECLINE" in r["flags"])
    n_missed = sum(1 for r in rows if "NOT_CLAIMED_BUT_ACCEPT" in r["flags"])
    lines += [
        "",
        f"**Totals:** {total} offers | {n_double} DOUBLE_CLAIM | {n_decline} CLAIMED_BUT_DECLINE | {n_missed} NOT_CLAIMED_BUT_ACCEPT",
        "",
    ]

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {args.out} ({total} offers)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())