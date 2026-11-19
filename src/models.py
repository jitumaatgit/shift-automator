import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum, auto


class ActionKind(Enum):
    PARSE = auto()
    DECISION = auto()
    SMS_SENT = auto()
    PUSH_SENT = auto()
    DRY_RUN = auto()
    WARNING = auto()
    SKIPPED = auto()


@dataclass
class Action:
    kind: ActionKind
    detail: str


def format_action(a: Action) -> str:
    if a.kind == ActionKind.DRY_RUN:
        return f"[DRY-RUN] {a.detail}"
    prefixes = {
        ActionKind.PARSE: "parsed",
        ActionKind.DECISION: "decision",
        ActionKind.SMS_SENT: "sent",
        ActionKind.PUSH_SENT: "sent",
        ActionKind.WARNING: "WARNING",
        ActionKind.SKIPPED: "skipped",
    }
    return f"{prefixes[a.kind]}: {a.detail}"


class ShiftDecision(Enum):
    AUTO_ACCEPT = "auto_accept"
    AUTO_DECLINE = "auto_decline"


@dataclass
class LocationSegment:
    """A single location/time block within a shift (used for multi-site shifts)."""
    name: str
    address: str
    start_time: datetime
    end_time: datetime


_PARSE_FAIL_DATE = datetime(1970, 1, 1)


@dataclass(frozen=True)
class ParsedOffer:
    """Immutable parser output. Guaranteed start_time, end_time, building, title."""
    raw_text: str
    building: str = "Unknown"
    title: str = ""
    start_time: datetime = _PARSE_FAIL_DATE
    end_time: datetime = _PARSE_FAIL_DATE
    claim_code: str = ""
    cancel_number: str = ""
    address: str = ""
    shift_note: str = ""
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    year_inferred: int = 2026
    locations: tuple[LocationSegment, ...] = ()
    calendar_event_id: Optional[str] = None

    @property
    def shift_key(self) -> str:
        parts = [self.building, self.title]
        if self.start_time and self.start_time.year > 2000:
            parts.append(self.start_time.strftime("%Y-%m-%dT%H:%M"))
        raw = "|".join(parts)
        return f"shift-{hashlib.md5(raw.encode()).hexdigest()[:8]}"

    @property
    def duration_hours(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() / 3600.0
        return 0.0

    @property
    def is_multi_site(self) -> bool:
        return len(self.locations) > 0

    @property
    def is_overtime_eligible(self) -> bool:
        return "overtime approved" in self.shift_note.lower()

    @property
    def display_address(self) -> str:
        if self.is_multi_site:
            return " / ".join([f"{loc.name}: {loc.address}" for loc in self.locations])
        return self.address

    def to_calendar_summary(self) -> str:
        prefix = "[CC] "
        if self.is_multi_site:
            return f"{prefix}{self.title} ({len(self.locations)} sites)"
        return f"{prefix}{self.title} - {self.address[:30]}"

    def to_calendar_description(self) -> str:
        lines = [
            f"Building: {self.building}",
            f"Claim Code: {self.claim_code}",
            f"Note: {self.shift_note[:200]}",
        ]
        if self.contact_name:
            lines.append(f"Contact: {self.contact_name} {self.contact_phone or ''}")
        if self.is_multi_site:
            lines.append("\nLocations:")
            for loc in self.locations:
                lines.append(f"  {loc.name}: {loc.address} ({loc.start_time.strftime('%H:%M')}-{loc.end_time.strftime('%H:%M')})")
        else:
            lines.append(f"Address: {self.address}")
        return "\n".join(lines)


@dataclass
class ScoredOffer:
    """Rules-engine output wrapping a ParsedOffer with decision metadata."""
    offer: ParsedOffer
    score: float = 0.0
    decision: ShiftDecision = ShiftDecision.AUTO_DECLINE
    reasons: List[str] = field(default_factory=list)
    calendar_event_id: Optional[str] = None


@dataclass(frozen=True)
class ShiftContext:
    timezone: str = "America/Los_Angeles"
    day_hours: float = 0.0
    prev_day_hours: float = 0.0
    prev_day_last_end: Optional[datetime] = None
    adjacent_events: List[Dict[str, Any]] = field(default_factory=list)
    weekly_hours: float = 0.0
    conflicts: Optional[Dict[str, Any]] = None


@dataclass
class PipelineResult:
    """Typed result from process_offer conveying kind and outcome."""
    kind: str
    parsed: Optional[ParsedOffer] = None
    scored: Optional[ScoredOffer] = None
    actions: List[Action] = field(default_factory=list)
    elapsed_ms: float = 0.0
    dry_run: bool = True
    error: Optional[str] = None
    event_id: Optional[str] = None
    raw_preview: Optional[str] = None