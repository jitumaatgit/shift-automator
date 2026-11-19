"""
Regex-based shift text parser.
Handles known formats:
  1. Building shifts (Estate, Starlight, etc.) — most common
  2. Special Projects (single-site)
  3. Building Lunch Coverage (multi-site)
  4. Building Lockout

Extensible: new formats can be added by registering new parse functions.
"""
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Callable
from dateutil import parser as date_parser

from models import LocationSegment, ParsedOffer

STAFFING_REPLY_PATTERNS = [
    re.compile(r"already been taken|has been closed|shift is no longer available", re.IGNORECASE),
    re.compile(r"sorry,? this position", re.IGNORECASE),
]
CONFIRMATION_PATTERNS = [
    re.compile(r"congratulations.*booked|successfully accepted|offer confirmed", re.IGNORECASE),
]
GARBAGE_RE = re.compile(r"^Open$|^Open\s*$|^$|^\s{0,3}$")

CONFIRMATION_HEADER_RE = re.compile(
    r"Congratulations!\s+You\s+are\s+now\s+booked\s+to\s+do\s+shift\s+\[(?P<building>[^\]]+)\]\s+"
    r"(?P<title>.+?)\s+"
    r"starting\s+at\s+"
    r"(?P<day>[A-Za-z]{3})\s+"
    r"(?P<date>\d{1,2}/[A-Za-z]{3})\s+"
    r"(?P<start_time>\d{1,2}:\d{2}[ap]m)\s*"
    r"[-–—]\s*"
    r"(?P<end_time>\d{1,2}:\d{2}[ap]m)"
)

def classify_incoming(text: str) -> str:
    """Classify incoming SMS as confirmation, rejection, garbage, or offer."""
    stripped = text.strip()
    if GARBAGE_RE.match(stripped):
        return "garbage"
    for pat in STAFFING_REPLY_PATTERNS:
        if pat.search(stripped):
            return "rejection"
    for pat in CONFIRMATION_PATTERNS:
        if pat.search(stripped):
            return "confirmation"
    return "offer"





def parse_confirmation(text: str, reference_date: Optional[datetime] = None, known_buildings: Optional[set[str]] = None) -> Optional[ParsedOffer]:
    """Parse a shift confirmation text into a ParsedOffer. Returns None if parsing fails."""
    stripped = text.strip()
    m = CONFIRMATION_HEADER_RE.search(stripped)
    if not m:
        return None

    building_str = m.group("building").strip()
    building = _resolve_building(building_str, known_buildings)

    date_str = m.group("date")
    start_time_str = m.group("start_time").replace(" ", "")
    end_time_str = m.group("end_time").replace(" ", "")

    month_abbr = date_str.split("/")[1]
    day_num = int(date_str.split("/")[0])
    month_num = datetime.strptime(month_abbr, "%b").month
    year = _infer_year(month_num, day_num, reference_date)

    start_dt = date_parser.parse(f"{year}-{month_num:02d}-{day_num:02d} {start_time_str}")
    end_dt = date_parser.parse(f"{year}-{month_num:02d}-{day_num:02d} {end_time_str}")

    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    address = _extract_address(stripped, building_str)
    shift_note = _extract_shift_note(stripped, building)
    title = m.group("title").strip()

    return ParsedOffer(
        raw_text=stripped,
        building=building,
        title=title,
        start_time=start_dt,
        end_time=end_dt,
        address=address,
        shift_note=shift_note,
        year_inferred=year,
    )


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

HEADER_RE = re.compile(
    r"Open shift available at \[(?P<building>[^\]]+)\] "
    r"(?P<title>.+?) "
    r"starting at "
    r"(?P<day>[A-Za-z]{3}) "
    r"(?P<date>\d{1,2}/[A-Za-z]{3}) "
    r"(?P<start_time>\d{1,2}:\d{2}[ap]m) "
    r"- "
    r"(?P<end_time>\d{1,2}:\d{2}[ap]m)"
)

HEADER_LOOSE_RE = re.compile(
    r"(?:Open\s+)?[Ss]hift\s+available\s+at\s+\[(?P<building>[^\]]+)\]\s+"
    r"(?P<title>.+?)\s+"
    r"starting(?:\s+at)?\s+"
    r"(?P<day>[A-Za-z]{3,})\s+"
    r"(?P<date>\d{1,2}/[A-Za-z]{3})\s+"
    r"(?P<start_time>\d{1,2}:\d{2}\s*[ap]m)\s*"
    r"[-–—]\s*"
    r"(?P<end_time>\d{1,2}:\d{2}\s*[ap]m)"
)

CLAIM_CODE_RE = re.compile(r"reply\s+(\d+)\s+\(only this number\)")
CLAIM_CODE_LOOSE_RE = re.compile(r"reply\s+(\d{5,})", re.IGNORECASE)

CANCEL_NUMBER_RE = re.compile(r"Call\s+.*?at\s+(\d{3}-\d{3}-\d{4})", re.IGNORECASE)

SCHEDULE_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9\s]+?):\s*"
    r"(?P<start>\d{1,2}[;:]?\d{0,2}[ap]m)\s*"
    r"-\s*"
    r"(?P<end>\d{1,2}[;:]?\d{0,2}[ap]m)"
)

MULTI_ADDRESS_SEGMENT_RE = re.compile(
    r"(?P<name>[A-Za-z0-9\s]+?)\s+-\s+(?P<address>[^/]+)"
)

CONTACT_RE = re.compile(
    r"Call\s+(?P<name>[A-Za-z\s]+?)\s+upon arrival at\s+(?P<phone>[\d-]+)"
)

LOCKOUT_CONTACT_RE = re.compile(
    r"Contact\s+(?:@?(?P<phone>[\d-]+)|(?P<name>[A-Za-z\s]+?)\s+@?(?P<phone2>[\d-]+))"
)


# ---------------------------------------------------------------------------
# Building name → canonical name aliases
# ---------------------------------------------------------------------------

_bracket_to_building = {
    "Special Projects": "Special Projects",
    "Building Lunch Coverage": "Building Lunch Coverage",
    "Building Lockout": "Building Lockout",
    "Estate": "Estate",
    "Starlight": "Starlight",
    "Hazel Heights": "Hazel Heights",
    "Golden West/8x8": "Golden West/8x8",
    "8x8": "8x8",
    "Golden West": "Golden West",
    "STS": "STS",
    "HRR": "HRR",
    "Old Town Clinic AM": "Old Town Clinic AM",
    "Old Town Clinic PM": "Old Town Clinic PM",
    "Old Town Recovery Center AM": "Old Town Recovery Center AM",
    "Old Town Recovery Center PM": "Old Town Recovery Center PM",
    "Hooper": "Hooper",
    "Blackburn Clinic": "Blackburn Clinic",
    "CB Rutherford": "CB Rutherford",
    "Larry Naito": "Larry Naito",
    "Evergreen": "Evergreen",
    "Karibu": "Karibu",
    "Admin": "Admin",
    "IT": "IT",
    "Imani": "Imani",
    "Employment Access Center": "Employment Access Center",
    "EAC": "Employment Access Center",
    "16th & Burnside": "16th & Burnside",
    "Hill Park": "Hill Park",
    "Shoreline": "Shoreline",
    "Ankeny/Sally": "Ankeny/Sally",
    "Biltmore/Butte": "Biltmore/Butte",
    "Medford": "Medford",
    "Madrona": "Madrona",
    "Henry": "Henry",
    "Alder": "Alder",
    "Ceder Commons": "Ceder Commons",
    "Meridian Gardens": "Meridian Gardens",
    "River Haven": "River Haven",
    "TCC/Chez Ami": "TCC",
    "TCC": "TCC",
    "Chez Ami": "TCC",
    "ROC": "ROC",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_time_string(t: str) -> str:
    """Normalize semicolons to colons in time strings."""
    return t.replace(";", ":")


def _infer_year(month: int, day: int, reference_date: Optional[datetime] = None) -> int:
    """Infer the year for a shift date. If >30 days in past, assume next year."""
    now = reference_date or datetime.now()
    candidate = datetime(now.year, month, day)
    if (now - candidate).days >= 31:
        return now.year + 1
    return now.year


def _resolve_building(bracket_text: str, known_buildings: Optional[set[str]] = None) -> str:
    """Resolve bracket value to a canonical building name string."""
    if bracket_text in _bracket_to_building:
        return _bracket_to_building[bracket_text]

    if known_buildings is not None and bracket_text in known_buildings:
        return bracket_text

    if " - " in bracket_text:
        base = bracket_text.split(" - ", 1)[0].strip()
        if base in _bracket_to_building:
            return _bracket_to_building[base]
        if known_buildings is not None and base in known_buildings:
            return base
        print(f"Warning: unknown building '{bracket_text}'")
        return "Unknown"

    if known_buildings is not None:
        print(f"Warning: unknown building '{bracket_text}'")
        return "Unknown"

    return "Unknown"


def _parse_header_line(line: str, reference_date: Optional[datetime] = None, known_buildings: Optional[set[str]] = None) -> Optional[dict]:
    """Extract core metadata from the header line."""
    m = HEADER_RE.search(line)
    if not m:
        m = HEADER_LOOSE_RE.search(line)
    if not m:
        return None

    building_str = m.group("building").strip()
    building = _resolve_building(building_str, known_buildings)

    date_str = m.group("date")
    start_time_str = m.group("start_time")
    end_time_str = m.group("end_time")

    month_abbr = date_str.split("/")[1]
    day_num = int(date_str.split("/")[0])
    month_num = datetime.strptime(month_abbr, "%b").month
    year = _infer_year(month_num, day_num, reference_date)

    start_dt = date_parser.parse(f"{year}-{month_num:02d}-{day_num:02d} {start_time_str}")
    end_dt = date_parser.parse(f"{year}-{month_num:02d}-{day_num:02d} {end_time_str}")

    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    return {
        "building": building,
        "bracket_text": building_str,
        "title": m.group("title").strip(),
        "start_time": start_dt,
        "end_time": end_dt,
    }


def _extract_claim_code(text: str) -> str:
    m = CLAIM_CODE_RE.search(text)
    if m:
        return m.group(1)
    m = CLAIM_CODE_LOOSE_RE.search(text)
    return m.group(1) if m else ""


def _extract_shift_note(text: str, building: str) -> str:
    """Extract the shift note section."""
    lines = text.splitlines()
    note_lines = []
    in_note = False

    for line in lines:
        if line.startswith("Shift Note:"):
            in_note = True
            note_lines.append(line.replace("Shift Note:", "").strip())
            continue
        if in_note:
            if line.strip() == "":
                break
            if "Address" in line or "Break Schedule" in line or "reply" in line.lower():
                break
            note_lines.append(line.strip())

    return " ".join(note_lines).strip()


def _extract_contact(note: str) -> tuple[Optional[str], Optional[str]]:
    m = CONTACT_RE.search(note)
    if m:
        return m.group("name").strip(), m.group("phone").strip()
    m2 = LOCKOUT_CONTACT_RE.search(note)
    if m2:
        name = m2.group("name") or ""
        phone = m2.group("phone") or m2.group("phone2") or ""
        return (name.strip(), phone.strip()) if phone else (None, None)
    # Fallback: extract any 10-digit phone number embedded in the note
    m3 = re.search(r"\b(\d{3}-?\d{3}-?\d{4})\b", note)
    if m3:
        return None, m3.group(1)
    return None, None


def _extract_address(text: str, bracket_text: str) -> str:
    """Extract address using the '{bracket_text} Address:' pattern."""
    pattern = re.compile(rf"{re.escape(bracket_text)}\s+Address\s*:\s*(.+)")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = pattern.search(line)
        if m:
            addr = m.group(1).strip()
            if addr:
                return addr
        # Could be split across lines: "{Name} Address :" standalone, then next line
        if bracket_text in line and "Address" in line and ":" in line:
            parts = line.split(":", 1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip()
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    return ""


def _extract_multi_site_schedule(text: str, base_date: datetime) -> List[LocationSegment]:
    """Extract building schedule and addresses for Building Lunch Coverage."""
    lines = text.splitlines()
    segments: Dict[str, Dict] = {}

    for line in lines:
        m = SCHEDULE_LINE_RE.match(line.strip())
        if m:
            name = m.group("name").strip()
            start_str = _clean_time_string(m.group("start").strip())
            end_str = _clean_time_string(m.group("end").strip())

            start_t = date_parser.parse(start_str).time()
            end_t = date_parser.parse(end_str).time()

            start_dt = datetime.combine(base_date.date(), start_t)
            end_dt = datetime.combine(base_date.date(), end_t)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

            segments[name] = {
                "start_time": start_dt,
                "end_time": end_dt,
                "address": "",
            }

    for line in lines:
        if "Building Lunch Coverage Address" in line and ":" in line:
            addr_text = line.split(":", 1)[1].strip()

            building_positions = []
            for name in segments.keys():
                pattern = re.compile(rf"\b{re.escape(name)}\b\s*-")
                m = pattern.search(addr_text)
                if m:
                    building_positions.append((m.start(), name, m.end()))

            building_positions.sort(key=lambda x: x[0])

            for i, (_, name, name_end) in enumerate(building_positions):
                if i + 1 < len(building_positions):
                    next_start = building_positions[i + 1][0]
                    address = addr_text[name_end:next_start].strip()
                else:
                    address = addr_text[name_end:].strip()

                address = address.rstrip(" /").strip()

                if name in segments:
                    segments[name]["address"] = address

            for name in segments:
                if not segments[name]["address"]:
                    parts = addr_text.split(" / ")
                    for part in parts:
                        m = MULTI_ADDRESS_SEGMENT_RE.match(part.strip())
                        if m and (m.group("name").strip().lower() in name.lower() or name.lower() in m.group("name").strip().lower()):
                            segments[name]["address"] = m.group("address").strip()
                            break

    results = []
    for name, data in segments.items():
        results.append(LocationSegment(
            name=name,
            address=data["address"],
            start_time=data["start_time"],
            end_time=data["end_time"],
        ))

    results.sort(key=lambda x: x.start_time)
    return results


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

_EMPTY = "Empty text"
_NO_HEADER = "Could not parse header line"


def parse_shift_text(text: str, reference_date: Optional[datetime] = None, known_buildings: Optional[set[str]] = None) -> tuple[ParsedOffer, list[str]]:
    """
    Parse a shift offer text message into a ParsedOffer.

    Caller must pre-classify the text (parser no longer checks for non-offer patterns).

    Returns:
        (ParsedOffer, list of parse error strings)
    """
    text = text.strip()
    errors: list[str] = []

    lines = text.splitlines()
    if not lines:
        errors.append(_EMPTY)
        return ParsedOffer(raw_text=text), errors

    header = None
    for line in lines:
        header = _parse_header_line(line, reference_date, known_buildings)
        if header:
            break

    if not header:
        errors.append(_NO_HEADER)
        return ParsedOffer(raw_text=text), errors

    building = header["building"]
    title = header["title"]
    start_time = header["start_time"]
    end_time = header["end_time"]

    claim_code = _extract_claim_code(text)
    if not claim_code:
        errors.append("No claim code found")

    shift_note = _extract_shift_note(text, building)
    contact_name, contact_phone = _extract_contact(shift_note)

    cancel_number = ""
    m = CANCEL_NUMBER_RE.search(text)
    if m:
        cancel_number = m.group(1)

    locations: tuple[LocationSegment, ...] = ()
    address = ""
    if building == "Building Lunch Coverage":
        locations = tuple(_extract_multi_site_schedule(text, start_time))
    elif building != "Unknown":
        address = _extract_address(text, header["bracket_text"])

    return ParsedOffer(
        raw_text=text,
        building=building,
        title=title,
        start_time=start_time,
        end_time=end_time,
        claim_code=claim_code,
        cancel_number=cancel_number,
        address=address,
        shift_note=shift_note,
        contact_name=contact_name,
        contact_phone=contact_phone,
        year_inferred=start_time.year,
        locations=locations,
    ), errors


def load_sample_shifts(data_path: Optional[str] = None) -> list[tuple[str, str]]:
    """Load all sample shifts from the markdown file."""
    if data_path is None:
        data_path = str(Path(__file__).parent.parent / "data" / "sample_shifts.md")
    content = Path(data_path).read_text()

    shifts = []
    current_id = None
    current_lines = []

    for line in content.splitlines():
        if line.startswith("## "):
            if current_id is not None and current_lines:
                shifts.append((current_id, "\n".join(current_lines).strip()))
            current_id = line.replace("## ", "").strip()
            current_lines = []
        elif current_id is not None:
            current_lines.append(line)

    if current_id is not None and current_lines:
        shifts.append((current_id, "\n".join(current_lines).strip()))

    return shifts


# ---------------------------------------------------------------------------
# Extensibility: register custom parsers for future formats
# ---------------------------------------------------------------------------

_CUSTOM_PARSERS: List[Callable[[str, Optional[datetime]], Optional[ParsedOffer]]] = []


def register_custom_parser(fn: Callable[[str, Optional[datetime]], Optional[ParsedOffer]]) -> None:
    """Register an additional parser for new shift formats."""
    _CUSTOM_PARSERS.append(fn)


def parse_with_fallback(text: str, reference_date: Optional[datetime] = None, known_buildings: Optional[set[str]] = None) -> tuple[ParsedOffer, list[str]]:
    """
    Try the main parser first, then fall back to registered custom parsers.
    Returns (ParsedOffer, list of parse errors).
    """
    parsed, errors = parse_shift_text(text, reference_date, known_buildings)
    has_header = _EMPTY not in errors and _NO_HEADER not in errors
    if has_header:
        return parsed, errors

    for parser_fn in _CUSTOM_PARSERS:
        try:
            result = parser_fn(text, reference_date)
            if result:
                return result, []
        except Exception:
            continue

    if _NO_HEADER not in errors:
        errors.append("No parser matched header format")
    return parsed, errors
