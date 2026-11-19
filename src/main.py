from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Optional

from models import ParsedOffer, ShiftDecision, ScoredOffer, Action, format_action
from parser import load_sample_shifts


def _check_tasker(url: str, http) -> bool:
    try:
        r = http.get(url, timeout=3)
        return r.status_code < 500
    except Exception:
        return False


def _dial_dispatch(config: Config) -> None:
    if config.dry_run:
        print(f"[Dispatcher] Would dial: {config.dispatch_number}", file=sys.stderr)
        return
    subprocess.run(["termux-telephony-call", config.dispatch_number], timeout=15)


def _build_args() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Shift Offer Automator")
    p.add_argument("--text", type=str, help="Raw shift offer text to process")
    p.add_argument("--config", type=str, default="config.yaml", help="Path to config YAML")
    p.add_argument("--sample", type=str, help="Process sample by ID from data/sample_shifts.md")
    p.add_argument("--json", action="store_true", help="Output result as JSON (for Tasker/automation)")
    p.add_argument("--send-accept", type=str, help="Send accept SMS (pass claim code)")
    p.add_argument("--call", action="store_true", help="Dial dispatch to cancel current shift")
    p.add_argument("--claim-code", type=str, help="Claim code for action flags")
    p.add_argument("--reply", type=str, help="Handle reply action: CANCEL, CALL")
    p.add_argument("--reply-offer-json", type=str, help="JSON-encoded offer for --reply")
    p.add_argument("--refresh-cache", action="store_true", help="Refresh calendar cache and exit")
    return p


def _build_calendar(config: Config, CC, CE) -> CC:
    cal = CC(
        calendar_id=config.calendar_id,
        credentials_path=config.calendar_credentials_path,
        timezone=config.calendar_timezone,
        dry_run=config.dry_run,
        cache_ttl_seconds=config.calendar_cache_ttl_seconds,
    )
    try:
        cal.authenticate()
    except CE as e:
        print(f"[ShiftAutomator] Calendar auth failed: {e}", file=sys.stderr)
    return cal


def _build_responder(config: Config, SMS, create) -> Responder:
    sms = SMS(
        staffing_number=config.staffing_number,
        personal_number=config.personal_number,
        sms_transport=config.sms_transport,
        work_sim_sub_id=str(config.work_sim_sub_id),
        ntfy_channel=config.ntfy_channel,
        tasker_base_url=config.tasker_base_url,
        cancel_warning_seconds=config.cancel_warning_seconds,
        dry_run=config.dry_run,
    )
    return create(sms)


def _handle_cli_actions(args, config: Config, calendar: CalendarClient, responder: Responder) -> Optional[str]:
    if args.refresh_cache:
        print("Calendar cache refreshed", file=sys.stderr)
        return None
    if args.send_accept:
        offer = type('Offer', (), {'claim_code': args.send_accept})()
        responder.send_accept(offer)
        print(f"Sent accept SMS: {args.send_accept}", file=sys.stderr)
        return None
    if args.call:
        _dial_dispatch(config)
        return None
    if args.reply:
        if args.reply_offer_json:
            d = json.loads(args.reply_offer_json)
            offer = ParsedOffer(**{k: v for k, v in d.items() if k in ParsedOffer.__dataclass_fields__})
        else:
            offer = ParsedOffer(raw_text="reply")
        for a in _handle_reply(args.reply, offer, config, calendar, responder):
            print(f" > {a}", file=sys.stderr)
        return None
    return _resolve_input(args)


def _handle_reply(reply_text: str, offer: ParsedOffer, config: Config, calendar: CalendarClient, responder: Responder) -> list[str]:
    reply = reply_text.strip().upper()
    actions = []

    if reply == "CANCEL":
        if offer.calendar_event_id and not offer.calendar_event_id.startswith("dry-run"):
            calendar.delete_shift_event(offer.calendar_event_id)
            actions.append(f"calendar: deleted event {offer.calendar_event_id}")
        else:
            actions.append("calendar: no event to delete")
        actions.append("manual: user cancelled")
    elif reply == "CALL":
        _dial_dispatch(config)
        actions.append("manual: dialed dispatch to cancel")
    else:
        actions.append(f"manual: unrecognized reply '{reply_text}'")

    return actions


def _format_result(result, json_mode: bool = False) -> str:
    if result.kind in ("confirmation", "rejection"):
        if json_mode:
            return json.dumps({
                "handled": result.kind,
                "event_id": result.event_id,
                "title": result.parsed.title if result.parsed else None,
                "building": result.parsed.building if result.parsed else None,
                "raw_preview": result.raw_preview,
                "error": result.error,
            }, indent=2)
        out = f"\n{'=' * 60}\nHANDLED: {result.kind}\n{'=' * 60}"
        if result.parsed and result.parsed.title:
            out += f"\nTitle: {result.parsed.title}"
        if result.event_id:
            out += f"\n  event_id: {result.event_id}"
        return out + "\n"

    offer = result.parsed
    scored = result.scored

    if json_mode:
        return json.dumps({
            "decision": scored.decision.value,
            "score": scored.score,
            "elapsed_ms": result.elapsed_ms,
            "title": offer.title,
            "category": offer.building,
            "start_time": offer.start_time.isoformat() if offer.start_time.year > 2000 else None,
            "end_time": offer.end_time.isoformat() if offer.end_time.year > 2000 else None,
            "start_epoch": int(offer.start_time.timestamp()) if offer.start_time.year > 2000 else None,
            "end_epoch": int(offer.end_time.timestamp()) if offer.end_time.year > 2000 else None,
            "duration_hours": offer.duration_hours,
            "claim_code": offer.claim_code,
            "cancel_number": offer.cancel_number,
            "calendar_event_id": offer.calendar_event_id,
            "address": offer.display_address[:100],
            "reasons": scored.reasons,
            "actions": [{"kind": a.kind.name.lower(), "detail": a.detail} for a in result.actions],
            "dry_run": result.dry_run,
        }, indent=2)

    out = f"\n{'=' * 60}\nDECISION: {scored.decision.value.upper()}\nScore: {scored.score:.1f}\nElapsed: {result.elapsed_ms:.1f}ms\n{'=' * 60}"
    out += f"\nTitle: {offer.title}\nBuilding: {offer.building}\nTime: {offer.start_time} -> {offer.end_time}"
    out += f"\nDuration: {offer.duration_hours:.1f}h\nClaim Code: {offer.claim_code}"
    if offer.cancel_number:
        out += f"\nCancel#: {offer.cancel_number}"
    if offer.is_multi_site:
        out += f"\nLocations: {len(offer.locations)}"
        for loc in offer.locations:
            out += f"\n - {loc.name}: {loc.address} ({loc.start_time.strftime('%H:%M')}-{loc.end_time.strftime('%H:%M')})"
    else:
        out += f"\nAddress: {offer.address}"
    out += f"\nContact: {offer.contact_name or 'N/A'} {offer.contact_phone or ''}"
    out += "\n" + "-" * 60 + "\nRule reasons:"
    for reason in scored.reasons:
        out += f"\n  - {reason}"
    out += "\n" + "-" * 60 + "\nActions:"
    for action in result.actions:
        out += f"\n  > {format_action(action)}"
    return out + "\n" + "=" * 60


def _resolve_input(args) -> str:
    if args.sample:
        shifts = load_sample_shifts()
        text = next((t for sid, t in shifts if sid == args.sample), "")
        if not text:
            print(f"Sample '{args.sample}' not found", file=sys.stderr)
            sys.exit(1)
        return text
    if args.text:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    print("Usage: python main.py --text '...' or --sample 1 or pipe input via stdin", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    args = _build_args().parse_args()

    import requests
    import config as _cfg
    import calendar_client as _cal
    import responder as _resp
    import pipeline as _pipe

    config = _cfg.load_config(args.config)
    calendar = _build_calendar(config, _cal.CalendarClient, _cal.CalendarError)
    responder = _build_responder(config, _resp.SMSConfig, _resp.create_responder)
    _resp.init_logging(config.log_file)
    if not _check_tasker(config.tasker_base_url, requests):
        print("[ShiftAutomator] Warning: Tasker HTTP Server not reachable", file=sys.stderr)
        print(f"[ShiftAutomator] {config.tasker_base_url}", file=sys.stderr)
    text = _handle_cli_actions(args, config, calendar, responder)
    if text is None:
        return
    print(_format_result(_pipe.process_offer(text, config, calendar, responder), args.json))


if __name__ == "__main__":
    main()
