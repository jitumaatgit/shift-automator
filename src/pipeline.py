import os
import time
from datetime import datetime
from typing import Optional

from models import ParsedOffer, ShiftDecision, ScoredOffer, PipelineResult, Action, ActionKind
from parser import parse_shift_text, parse_with_fallback, parse_confirmation, classify_incoming
from config import Config
from rules import RulesEngine
from calendar_client import CalendarClient
from responder import Responder, log_event


def process_offer(text: str, config: Config, calendar: CalendarClient, responder: Responder, reference_date: Optional[datetime] = None) -> PipelineResult:
    kind = classify_incoming(text)
    if kind == "confirmation":
        return _handle_confirmation(text, config, calendar, responder)
    if kind == "rejection":
        return _handle_rejection(text, config, responder)
    return _process_shift(text, config, calendar, responder, reference_date)


def _process_shift(text: str, config: Config, calendar: CalendarClient, responder: Responder, reference_date: Optional[datetime]) -> PipelineResult:
    start = datetime.now()
    actions: list[Action] = []

    known_buildings = set(config.shift_type_preferences.keys())
    parsed, parse_errors = parse_with_fallback(text, reference_date, known_buildings)
    actions.append(Action(ActionKind.PARSE, f"{parsed.title} ({parsed.duration_hours:.1f}h)"))

    engine = RulesEngine(config, calendar=calendar)
    scored = engine.evaluate(parsed, parse_errors=parse_errors)
    actions.append(Action(ActionKind.DECISION, f"{scored.decision.value} (score: {scored.score:.1f})"))

    if scored.decision == ShiftDecision.AUTO_ACCEPT:
        actions.extend(_execute_accept(scored, config, responder))
    elif scored.decision == ShiftDecision.AUTO_DECLINE:
        actions.extend(_execute_decline(scored, config, responder))

    elapsed = (datetime.now() - start).total_seconds() * 1000

    log_event({
        "dept": parsed.building,
        "title": parsed.title,
        "code": parsed.claim_code,
        "accepted": scored.decision == ShiftDecision.AUTO_ACCEPT,
        "score": scored.score,
        "reasons": scored.reasons,
        "elapsed_ms": elapsed,
        "raw_preview": parsed.raw_text[:200] if scored.reasons else None,
    })

    return PipelineResult(
        kind="offer",
        parsed=parsed,
        scored=scored,
        actions=actions,
        elapsed_ms=elapsed,
        dry_run=config.dry_run,
    )


def _handle_confirmation(text: str, config: Config, calendar: CalendarClient, responder: Responder) -> PipelineResult:
    offer = parse_confirmation(text)
    if not offer:
        return PipelineResult(kind="confirmation", error="Could not parse confirmation")

    msg_id = offer.shift_key
    event_id = calendar.add_shift_event(offer)

    if event_id and not event_id.startswith("dry-run"):
        responder.send_booking_push(offer, booked=True, message_id=msg_id)
    elif config.dry_run:
        responder.send_booking_push(offer, booked=True, message_id=msg_id)

    log_event({
        "action": "CONFIRMATION",
        "dept": offer.building,
        "title": offer.title,
        "event_id": event_id,
        "dry_run": config.dry_run,
    })

    return PipelineResult(
        kind="confirmation",
        parsed=offer,
        event_id=event_id,
        dry_run=config.dry_run,
    )


def _handle_rejection(text: str, config: Config, responder: Responder) -> PipelineResult:
    offer = ParsedOffer(raw_text=text)
    responder.send_booking_push(offer, booked=False)

    log_event({
        "action": "REJECTION",
        "raw_preview": text[:200],
    })

    return PipelineResult(
        kind="rejection",
        raw_preview=text[:200],
        dry_run=config.dry_run,
    )


CLAIM_MARKER_DEFAULT_PATH = "/sdcard/Tasker/shift_claim_sent.txt"
CLAIM_MARKER_TTL_SECONDS = 300


def _claim_marker_path() -> str:
    return os.environ.get("SHIFT_AUTOMATOR_CLAIM_MARKER", CLAIM_MARKER_DEFAULT_PATH)


def _native_claim_already_sent(claim_code: Optional[str], now: Optional[float] = None) -> bool:
    """True when Tasker's native claim path recorded sending this exact code recently."""
    if not claim_code:
        return False
    try:
        with open(_claim_marker_path(), encoding="utf-8") as fh:
            code, ts = fh.read().strip().split()
    except (OSError, ValueError):
        return False
    now = time.time() if now is None else now
    return code == claim_code and 0 <= now - float(ts) <= CLAIM_MARKER_TTL_SECONDS


def _execute_accept(scored: ScoredOffer, config: Config, responder: Responder) -> list[Action]:
    actions = []
    offer = scored.offer
    msg_id = offer.shift_key

    if not config.dry_run:
        responder.send_pending_push(offer, message_id=msg_id)
        actions.append(Action(ActionKind.PUSH_SENT, "pending confirmation push"))
        if _native_claim_already_sent(offer.claim_code):
            actions.append(Action(ActionKind.SKIPPED, "claim already sent by Tasker (marker)"))
        else:
            actions.append(Action(ActionKind.WARNING, f"no claim marker for {offer.claim_code} — Tasker native claim may have failed"))
    else:
        actions.append(Action(ActionKind.DRY_RUN, "would send pending confirmation push"))
        if _native_claim_already_sent(offer.claim_code):
            actions.append(Action(ActionKind.DRY_RUN, "would skip: claim already sent by Tasker (marker)"))
        else:
            actions.append(Action(ActionKind.DRY_RUN, f"WARNING: no claim marker for {offer.claim_code} — Tasker native claim may have failed"))

    return actions


def _execute_decline(scored: ScoredOffer, config: Config, responder: Responder) -> list[Action]:
    actions = []
    claimed = _native_claim_already_sent(scored.offer.claim_code)
    if not config.dry_run:
        responder.send_decline_push(scored, claimed=claimed)
        actions.append(Action(ActionKind.PUSH_SENT, "decline push"))
        if claimed:
            actions.append(Action(ActionKind.WARNING, f"claimed {scored.offer.claim_code} but scoring says DECLINE — call dispatch to cancel"))
    else:
        actions.append(Action(ActionKind.DRY_RUN, "would send decline push"))
        if claimed:
            actions.append(Action(ActionKind.DRY_RUN, f"WARNING: claimed {scored.offer.claim_code} would be declined — cancel needed"))
    return actions
