from __future__ import annotations

"""
Modular rules engine for shift acceptance decisions.

Each rule evaluates a ParsedOffer and returns a RuleResult.
The engine aggregates results and produces a ScoredOffer.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Optional
from datetime import datetime, timedelta
from enum import Enum

from models import ParsedOffer, ShiftDecision, ScoredOffer, ShiftContext
from config import Config
from calendar_client import CalendarProtocol, _filter_cc_events, compute_shift_context


class RuleAction(Enum):
    VETO_DECLINE = "veto_decline"
    SCORE = "score"
    FLAG = "flag"


@dataclass
class RuleResult:
    rule_name: str
    action: RuleAction
    value: float = 0.0
    reason: str = ""


RuleFn = Callable[[ParsedOffer, Config, Optional[ShiftContext], Optional[list[str]]], RuleResult]


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

def rule_wakefulness_gate(offer: ParsedOffer, config: Config, calendar=None, parse_errors=None) -> RuleResult:
    """Block shifts that start in the sleep window when it's currently too early."""
    if not offer.start_time:
        return RuleResult("wakefulness_gate", RuleAction.FLAG, 0, "No start time to check wakefulness")

    start_hour = offer.start_time.hour
    now_hour = datetime.now().hour

    if (config.wakefulness_gate_start <= start_hour < config.wakefulness_gate_end and
            config.wakefulness_gate_start <= now_hour <= config.wakefulness_gate_current):
        return RuleResult(
            "wakefulness_gate",
            RuleAction.VETO_DECLINE,
            0,
            f"Start hour {start_hour}:00 in sleep window and current time {now_hour}:00 is too early",
        )

    return RuleResult("wakefulness_gate", RuleAction.SCORE, 0, "Wakefulness gate OK")


def rule_calendar_conflict(offer: ParsedOffer, config: Config, context=None, parse_errors=None) -> RuleResult:
    """Check if shift conflicts with existing calendar events."""
    if not context:
        return RuleResult("calendar_conflict", RuleAction.FLAG, 0, "Calendar check skipped (no client)")

    if context.conflicts:
        summary = context.conflicts.get("summary", "Busy")
        return RuleResult("calendar_conflict", RuleAction.VETO_DECLINE, -100, f"Calendar conflict: {summary}")

    return RuleResult("calendar_conflict", RuleAction.SCORE, 0, "No calendar conflicts")


def rule_day_hours_cap(offer: ParsedOffer, config: Config, context=None, parse_errors=None) -> RuleResult:
    """Veto if the calendar already has >= day_hours_cap of [CC] shifts on this date."""
    if not context or not offer.start_time or offer.start_time.year <= 2000:
        return RuleResult("day_hours_cap", RuleAction.FLAG, 0, "Day hours cap check skipped")

    total = context.day_hours
    if total >= config.day_hours_cap:
        return RuleResult(
            "day_hours_cap",
            RuleAction.VETO_DECLINE,
            -100,
            f"Already booked {total:.1f}h on this date (cap {config.day_hours_cap}h)",
        )

    return RuleResult("day_hours_cap", RuleAction.SCORE, 0, f"Day total: {total:.1f}h")


def rule_post_cap_break(offer: ParsedOffer, config: Config, context=None, parse_errors=None) -> RuleResult:
    """Veto if previous day hit day cap and break before this shift is too short."""
    if not context or not offer.start_time or offer.start_time.year <= 2000:
        return RuleResult("post_cap_break", RuleAction.FLAG, 0, "Post-cap break check skipped")

    total = context.prev_day_hours
    last_end = context.prev_day_last_end

    if total >= config.day_hours_cap:
        if last_end is None:
            return RuleResult(
                "post_cap_break",
                RuleAction.VETO_DECLINE,
                -100,
                f"Previous day hit {total:.1f}h cap but no last shift end found",
            )
        gap = (offer.start_time - last_end).total_seconds() / 3600.0
        if gap < config.post_cap_break_hours:
            return RuleResult(
                "post_cap_break",
                RuleAction.VETO_DECLINE,
                -100,
                f"Only {gap:.1f}h break after {total:.1f}h day (need {config.post_cap_break_hours}h)",
            )

    return RuleResult("post_cap_break", RuleAction.SCORE, 0, f"Previous day: {total:.1f}h, break OK")


def rule_location_preference(offer: ParsedOffer, config: Config, calendar=None, parse_errors=None) -> RuleResult:
    """Score based on location preferences. Checks display_address, then falls back to building name."""
    prefs = config.location_preferences
    liked = prefs.get("liked", [])
    disliked = prefs.get("disliked", [])

    address = offer.display_address.lower()
    building_name = offer.building.lower()

    score, liked_reasons = _match_locations(address, building_name, liked, config.location_liked_bonus, "Liked")
    penalty, disliked_reasons = _match_locations(address, building_name, disliked, config.location_disliked_penalty, "Disliked")
    score -= penalty

    reasons = liked_reasons + disliked_reasons
    return RuleResult("location_preference", RuleAction.SCORE, score, "; ".join(reasons) if reasons else "Neutral location")


def _match_locations(address: str, building_name: str, locations: list[str], score_per: float, label: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    locations = locations or []
    for loc in locations:
        loc_lower = loc.lower()
        if loc_lower in address or loc_lower in building_name:
            score += score_per
            reasons.append(f"{label} location: {loc}")
    return score, reasons


def rule_shift_type_preference(offer: ParsedOffer, config: Config, calendar=None, parse_errors=None) -> RuleResult:
    """Score based on the building/category of the shift."""
    type_prefs = config.shift_type_preferences
    building_name = offer.building

    if building_name in type_prefs:
        score = type_prefs[building_name]
        return RuleResult("shift_type", RuleAction.SCORE, score, f"{building_name} preference = {score}")

    return RuleResult("shift_type", RuleAction.SCORE, 0, "No preference configured")


def rule_title_preference(offer: ParsedOffer, config: Config, calendar=None, parse_errors=None) -> RuleResult:
    """Score based on the shift title/role (e.g. FD=Front Desk, J1=Janitorial)."""
    title_prefs = config.title_preferences
    title = offer.title.strip()

    if title in title_prefs:
        score = title_prefs[title]
        return RuleResult("title_preference", RuleAction.SCORE, score, f"Title '{title}' preference = {score}")

    keywords = config.title_keywords
    for keyword, keyword_score in keywords.items():
        if keyword.lower() in title.lower():
            return RuleResult("title_preference", RuleAction.SCORE, keyword_score, f"Title keyword '{keyword}' matched (+{keyword_score})")

    return RuleResult("title_preference", RuleAction.SCORE, 0, "No title preference configured")


def rule_time_of_day(offer: ParsedOffer, config: Config, calendar=None, parse_errors=None) -> RuleResult:
    """Score based on start time preferences."""
    if not offer.start_time:
        return RuleResult("time_of_day", RuleAction.SCORE, 0, "No start time")

    hour = offer.start_time.hour
    score = 0.0
    reasons = []

    for start, end in config.preferred_hours:
        if start <= hour < end:
            score += config.preferred_time_bonus
            reasons.append(f"Within preferred window {start}:00-{end}:00")

    for entry in config.undesired_hours:
        if len(entry) != 2:
            continue
        start, end = entry
        if start <= hour < end:
            if config.veto_undesired_hours:
                return RuleResult("time_of_day", RuleAction.VETO_DECLINE, 0, f"Start hour {hour}:00 in undesired window {start}:00-{end}:00 (veto)")
            score -= config.undesired_time_penalty
            reasons.append(f"Within undesired window {start}:00-{end}:00")

    return RuleResult("time_of_day", RuleAction.SCORE, score, "; ".join(reasons) if reasons else "Neutral time")


def rule_weekly_hours_cap(offer: ParsedOffer, config: Config, context=None, parse_errors=None) -> RuleResult:
    """Check against weekly hours cap using the shift's actual week."""
    cap = config.weekly_hours_cap
    if not context or not offer.start_time or offer.start_time.year <= 2000:
        return RuleResult("weekly_hours", RuleAction.FLAG, 0, f"Weekly hours check skipped (no calendar or unparsed shift)")

    hours = context.weekly_hours
    projected = hours + offer.duration_hours

    if projected > cap and not offer.is_overtime_eligible:
        return RuleResult(
            "weekly_hours",
            RuleAction.VETO_DECLINE,
            -100,
            f"Projected {projected:.1f}h exceeds cap {cap}h (no overtime approval)"
        )

    if projected > cap and offer.is_overtime_eligible:
        return RuleResult(
            "weekly_hours",
            RuleAction.SCORE,
            0,
            f"Overtime shift (approved): {hours:.1f}h + {offer.duration_hours:.1f}h = {projected:.1f}h"
        )

    return RuleResult("weekly_hours", RuleAction.SCORE, 0, f"Projected weekly: {projected:.1f}h")


def rule_overnight_shift(offer: ParsedOffer, config: Config, calendar=None, parse_errors=None) -> RuleResult:
    """Veto shifts whose end time lands in the overnight window."""
    if not offer.end_time or offer.end_time.year <= 2000:
        return RuleResult("overnight_shift", RuleAction.FLAG, 0, "No end time to check overnight")
    end_hour = offer.end_time.hour
    start = config.overnight_veto_start_hour
    end = config.overnight_veto_end_hour
    if start <= end:
        in_window = start <= end_hour < end
    else:
        in_window = end_hour >= start or end_hour < end
    if in_window:
        return RuleResult(
            "overnight_shift",
            RuleAction.VETO_DECLINE,
            -100,
            f"Shift ends at {end_hour}:00 in overnight window {start}:00-{end}:00",
        )
    return RuleResult("overnight_shift", RuleAction.SCORE, 0, f"End hour {end_hour}:00 outside overnight window")


def rule_rest_gap_sleep(offer: ParsedOffer, config: Config, context=None, parse_errors=None) -> RuleResult:
    """Check rest gap only when offer or adjacent event starts in the sleep window."""
    if not context:
        return RuleResult("rest_gap_sleep", RuleAction.FLAG, 0, "Rest gap check skipped (no client)")

    if not offer.start_time or not offer.end_time:
        return RuleResult("rest_gap_sleep", RuleAction.FLAG, 0, "No shift times to check rest gap")

    def in_sleep(dt: datetime) -> bool:
        hour = dt.hour
        if config.rest_gap_sleep_start <= config.rest_gap_sleep_end:
            return config.rest_gap_sleep_start <= hour < config.rest_gap_sleep_end
        return hour >= config.rest_gap_sleep_start or hour < config.rest_gap_sleep_end

    offer_in_sleep = in_sleep(offer.start_time)

    tz = context.timezone
    for event_start, event_end, event in _filter_cc_events(context.adjacent_events, tz):
        if event_end <= offer.start_time:
            gap = (offer.start_time - event_end).total_seconds() / 3600.0
        elif event_start >= offer.end_time:
            gap = (event_start - offer.end_time).total_seconds() / 3600.0
        else:
            continue

        event_in_sleep = in_sleep(event_start)

        if offer_in_sleep or event_in_sleep:
            required = config.rest_gap_sleep_hours
            if 0 < gap < required:
                return RuleResult(
                    "rest_gap_sleep",
                    RuleAction.SCORE,
                    config.rest_gap_penalty,
                    f"Only {gap:.1f}h rest vs {required}h required (with '{event.get('summary', 'event')}')",
                )

    return RuleResult("rest_gap_sleep", RuleAction.SCORE, 0, "Rest gap OK")


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

BUILTIN_RULES: Dict[str, RuleFn] = {
    "wakefulness_gate": rule_wakefulness_gate,
    "calendar_conflict": rule_calendar_conflict,
    "day_hours_cap": rule_day_hours_cap,
    "post_cap_break": rule_post_cap_break,
    "rest_gap_sleep": rule_rest_gap_sleep,
    "location_preference": rule_location_preference,
    "shift_type_preference": rule_shift_type_preference,
    "title_preference": rule_title_preference,
    "time_of_day": rule_time_of_day,
    "overnight_shift": rule_overnight_shift,
    "weekly_hours_cap": rule_weekly_hours_cap,
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RulesEngine:
    """
    Evaluates ParsedOffers against configured rules.

    Binary decision: score > auto_decline_threshold => AUTO_ACCEPT, else AUTO_DECLINE.
    """

    def __init__(self, config: Config, calendar: Optional[CalendarProtocol] = None):
        self.config = config
        self._calendar = calendar
        self.rules: List[RuleFn] = []
        self._load_rules()

    def _load_rules(self) -> None:
        active = self.config.active_rules or list(BUILTIN_RULES.keys())
        for name in active:
            if name in BUILTIN_RULES:
                self.rules.append(BUILTIN_RULES[name])
            else:
                print(f"Warning: unknown rule '{name}' skipped")

    def evaluate(self, offer: ParsedOffer, parse_errors: Optional[list[str]] = None, context: Optional[ShiftContext] = None) -> ScoredOffer:
        """Run all rules and produce a scored decision."""
        if context is None and self._calendar is not None:
            context = compute_shift_context(offer, self._calendar)

        score = 0.0
        veto_decline = False
        reasons: List[str] = []

        for rule_fn in self.rules:
            try:
                result = rule_fn(offer, self.config, context, parse_errors)

                if result.action == RuleAction.VETO_DECLINE:
                    veto_decline = True
                    reasons.append(f"[VETO-DECLINE] {result.rule_name}: {result.reason}")
                elif result.action == RuleAction.SCORE:
                    score += result.value
                    if result.value != 0 or result.reason:
                        reasons.append(f"[{result.rule_name}] {result.reason} ({result.value:+.1f})")
                elif result.action == RuleAction.FLAG:
                    reasons.append(f"[FLAG-{result.rule_name}] {result.reason}")
            except Exception as e:
                reasons.append(f"[ERROR-{rule_fn.__name__}] {e}")

        decline_thresh = self.config.auto_decline_threshold

        if veto_decline:
            decision = ShiftDecision.AUTO_DECLINE
        elif score > decline_thresh:
            decision = ShiftDecision.AUTO_ACCEPT
        else:
            decision = ShiftDecision.AUTO_DECLINE

        return ScoredOffer(offer=offer, score=score, decision=decision, reasons=reasons)


# load_config imported from config.py
