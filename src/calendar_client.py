from __future__ import annotations

import os
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from models import ParsedOffer, ShiftContext

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CC_EVENT_PREFIX = "[CC]"
DEFAULT_CACHE_TTL_SECONDS = 60


def _parse_event_dt(event: Dict[str, Any], key: str, timezone: str) -> Optional[datetime]:
    dt_info = event.get(key, {})
    dt_str = dt_info.get("dateTime") or dt_info.get("date")
    if not dt_str:
        return None
    if "T" in dt_str:
        parsed = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            local_tz = ZoneInfo(timezone)
            parsed = parsed.astimezone(local_tz).replace(tzinfo=None)
        return parsed
    else:
        return datetime.strptime(dt_str, "%Y-%m-%d")


def _filter_cc_events(
    events: List[Dict[str, Any]], timezone: str
) -> List[Tuple[datetime, datetime, Dict[str, Any]]]:
    result: List[Tuple[datetime, datetime, Dict[str, Any]]] = []
    for event in events:
        summary = event.get("summary", "")
        if not summary.startswith(CC_EVENT_PREFIX):
            continue
        start = _parse_event_dt(event, "start", timezone)
        end = _parse_event_dt(event, "end", timezone)
        if start is None or end is None:
            continue
        if end <= start:
            continue
        result.append((start, end, event))
    return result


def _sum_cc_hours(
    events: List[Dict[str, Any]], timezone: str
) -> Tuple[float, Optional[datetime]]:
    total = 0.0
    last_end: Optional[datetime] = None
    for start, end, _event in _filter_cc_events(events, timezone):
        total += (end - start).total_seconds() / 3600.0
        if last_end is None or end > last_end:
            last_end = end
    return total, last_end


def _overlaps(
    event: Dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    timezone: str,
) -> bool:
    s = _parse_event_dt(event, "start", timezone)
    e = _parse_event_dt(event, "end", timezone)
    if s is None or e is None:
        return False
    return s < window_end and e > window_start


def compute_shift_context(
    offer: ParsedOffer,
    calendar: Optional[CalendarProtocol],
) -> Optional[ShiftContext]:
    if not calendar or not offer.start_time or offer.start_time.year <= 2000:
        return None

    wide_start = offer.start_time - timedelta(days=7)
    wide_end = offer.start_time + timedelta(days=7)
    all_events = calendar.get_events_between(wide_start, wide_end)

    conflicts = calendar.check_conflict(offer, cc_only=True)

    day_start = offer.start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    prev_day_start = day_start - timedelta(days=1)
    prev_day_end = day_start
    week_start = (offer.start_time - timedelta(days=offer.start_time.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)

    tz = calendar.timezone

    day_hours, _ = _sum_cc_hours(
        [e for e in all_events if _overlaps(e, day_start, day_end, tz)], tz
    )

    prev_day_hours, prev_day_last_end = _sum_cc_hours(
        [e for e in all_events if _overlaps(e, prev_day_start, prev_day_end, tz)], tz
    )

    weekly_hours, _ = _sum_cc_hours(
        [e for e in all_events if _overlaps(e, week_start, week_end, tz)], tz
    )

    adjacent_start = offer.start_time - timedelta(hours=12)
    adjacent_end = offer.end_time + timedelta(hours=12)
    adjacent = [e for e in all_events if _overlaps(e, adjacent_start, adjacent_end, tz)]

    return ShiftContext(
        timezone=tz,
        day_hours=day_hours,
        prev_day_hours=prev_day_hours,
        prev_day_last_end=prev_day_last_end,
        adjacent_events=adjacent,
        weekly_hours=weekly_hours,
        conflicts=conflicts,
    )


@runtime_checkable
class CalendarProtocol(Protocol):
    """Protocol declaring the calendar interface that rules engine needs."""
    timezone: str

    def get_events_between(self, start: datetime, end: datetime) -> List[Dict[str, Any]]: ...
    def get_adjacent_events(self, offer: "ParsedOffer", lookback_hours: float = 12, lookahead_hours: float = 12) -> List[Dict[str, Any]]: ...
    def get_weekly_hours(self, week_start: Optional[datetime] = None) -> float: ...
    def check_conflict(self, offer: "ParsedOffer", buffer_minutes: int = 30, cc_only: bool = False) -> Optional[Dict[str, Any]]: ...
    def _parse_event_dt(self, event: Dict[str, Any], key: str) -> Optional[datetime]: ...


class FakeCalendar:
    """Stub calendar with configurable return values for testing rules."""

    def __init__(
        self,
        timezone: str = "America/Los_Angeles",
        weekly_hours: float = 0.0,
        conflict: Optional[Dict[str, Any]] = None,
        adjacent_events: Optional[List[Dict[str, Any]]] = None,
        events_between: Optional[List[Dict[str, Any]]] = None,
    ):
        self.timezone = timezone
        self._weekly_hours = weekly_hours
        self._conflict = conflict
        self._adjacent_events = adjacent_events or []
        self._events_between = events_between or []

    def get_events_between(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        if callable(self._events_between):
            return self._events_between(start, end)
        return self._events_between

    def get_weekly_hours(self, week_start: Optional[datetime] = None) -> float:
        return self._weekly_hours

    def check_conflict(self, offer: "ParsedOffer", buffer_minutes: int = 30, cc_only: bool = False) -> Optional[Dict[str, Any]]:
        if callable(self._conflict):
            return self._conflict(offer, buffer_minutes, cc_only)
        return self._conflict

    def get_adjacent_events(self, offer: "ParsedOffer", lookback_hours: float = 12, lookahead_hours: float = 12) -> List[Dict[str, Any]]:
        if callable(self._adjacent_events):
            return self._adjacent_events(offer, lookback_hours, lookahead_hours)
        return self._adjacent_events

    def _parse_event_dt(self, event: Dict[str, Any], key: str) -> Optional[datetime]:
        return _parse_event_dt(event, key, self.timezone)


class CalendarError(Exception):
    """Raised when a calendar API call fails."""
    pass


class CalendarClient:

    def __init__(
        self,
        calendar_id: str = "primary",
        credentials_path: Optional[str] = None,
        timezone: str = "America/Los_Angeles",
        dry_run: bool = True,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        cache_file: str = "calendar_cache.json",
    ):
        self.calendar_id = calendar_id
        self.credentials_path = credentials_path or "credentials.json"
        self.timezone = timezone
        self.dry_run = dry_run
        self._service = None
        self._authed = False
        self._cached_events: Optional[List[Dict[str, Any]]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_window_start: Optional[datetime] = None
        self._cache_window_end: Optional[datetime] = None
        self._cache_file = cache_file
        self._cache_ttl = cache_ttl_seconds

    def authenticate(self) -> bool:
        if self._service is not None:
            return True
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES
            )
            self._service = build("calendar", "v3", credentials=creds)
            self._authed = True
            return True
        except Exception as e:
            raise CalendarError(f"Auth failed: {e}")

    def _ensure_service(self):
        if self._service is None:
            self.authenticate()
        return self._service

    @staticmethod
    def _dt_to_rfc3339(dt: datetime, tz: str) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        return dt.isoformat()

    def invalidate_cache(self) -> None:
        self._invalidate()

    def get_events_between(
        self, start: datetime, end: datetime
    ) -> List[Dict[str, Any]]:
        return self._get_cached_events(start, end)

    def check_conflict(
        self, offer: ParsedOffer, buffer_minutes: int = 30, cc_only: bool = False
    ) -> Optional[Dict[str, Any]]:
        if not offer.start_time or not offer.end_time:
            return None

        query_start = offer.start_time - timedelta(minutes=buffer_minutes)
        query_end = offer.end_time + timedelta(minutes=buffer_minutes)
        events = self.get_events_between(query_start, query_end)

        for event in events:
            if cc_only and not event.get("summary", "").startswith(CC_EVENT_PREFIX):
                continue
            event_start = self._parse_event_dt(event, "start")
            event_end = self._parse_event_dt(event, "end")
            if event_start is None or event_end is None:
                continue

            if offer.start_time < event_end and offer.end_time > event_start:
                return event

        return None

    def _parse_event_dt(
        self, event: Dict[str, Any], key: str
    ) -> Optional[datetime]:
        return _parse_event_dt(event, key, self.timezone)

    def _fetch_all_events(
        self, window_start: datetime, window_end: datetime
    ) -> List[Dict[str, Any]]:
        if self.dry_run or not self._service:
            return []
        time_min = self._dt_to_rfc3339(window_start, self.timezone)
        time_max = self._dt_to_rfc3339(window_end, self.timezone)
        all_events: List[Dict[str, Any]] = []
        page_token: Optional[str] = None

        try:
            while True:
                result = (
                    self._service.events()
                    .list(
                        calendarId=self.calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                        pageToken=page_token,
                    )
                    .execute()
                )
                all_events.extend(result.get("items", []))
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            return all_events
        except HttpError as e:
            raise CalendarError(f"_fetch_all_events failed: {e}")

    def _get_cached_events(
        self,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        if window_start is None:
            now = datetime.now()
            window_start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if window_end is None:
            window_end = window_start + timedelta(days=35)

        now = datetime.now()
        cache_valid = (
            self._cached_events is not None
            and self._cache_time is not None
            and self._cache_window_start == window_start
            and self._cache_window_end == window_end
            and (now - self._cache_time).total_seconds() < self._cache_ttl
        )
        if cache_valid:
            return self._cached_events

        if (
            self._cached_events is not None
            and self._cache_window_start is not None
            and self._cache_window_end is not None
            and self._cache_window_start <= window_start
            and self._cache_window_end >= window_end
            and self._cache_time is not None
            and (now - self._cache_time).total_seconds() < self._cache_ttl
        ):
            return self._filter_by_window(self._cached_events, window_start, window_end)

        file_cache = self._load_cache_file()
        if file_cache is not None:
            file_fetched_str = file_cache.get("fetched_at", now.isoformat())
            cache_age = (now - datetime.fromisoformat(file_fetched_str)).total_seconds()
            fresh = cache_age < self._cache_ttl

            file_win_start = file_cache.get("window_start")
            file_win_end = file_cache.get("window_end")

            if (
                file_win_start == window_start.isoformat()
                and file_win_end == window_end.isoformat()
                and fresh
            ):
                self._cached_events = file_cache.get("events", [])
                self._cache_time = now
                self._cache_window_start = window_start
                self._cache_window_end = window_end
                return self._cached_events

        events = self._fetch_all_events(window_start, window_end)
        self._cached_events = events
        self._cache_time = now
        self._cache_window_start = window_start
        self._cache_window_end = window_end

        self._save_cache_file({
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "fetched_at": now.isoformat(),
            "events": events,
        })

        return events

    def _invalidate(self) -> None:
        try:
            os.remove(self._cache_file)
        except FileNotFoundError:
            pass
        self._cached_events = None
        self._cache_time = None
        self._cache_window_start = None
        self._cache_window_end = None

    def _load_cache_file(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self._cache_file):
            return None
        try:
            with open(self._cache_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _save_cache_file(self, data: Dict[str, Any]) -> None:
        try:
            tmp_file = self._cache_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(data, f)
            os.replace(tmp_file, self._cache_file)
        except IOError as e:
            print(f"[CalendarClient] Warning: could not write cache file: {e}")

    def _filter_by_window(
        self, events: List[Dict[str, Any]],
        window_start: datetime, window_end: datetime,
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for e in events:
            s = _parse_event_dt(e, "start", self.timezone)
            e_end = _parse_event_dt(e, "end", self.timezone)
            if s is None or e_end is None:
                result.append(e)
            elif s < window_end and e_end > window_start:
                result.append(e)
        return result

    def add_shift_event(self, offer: ParsedOffer) -> Optional[str]:
        if not offer.start_time or not offer.end_time:
            return None

        event_body = {
            "summary": offer.to_calendar_summary(),
            "description": offer.to_calendar_description(),
            "start": {
                "dateTime": offer.start_time.isoformat(),
                "timeZone": self.timezone,
            },
            "end": {
                "dateTime": offer.end_time.isoformat(),
                "timeZone": self.timezone,
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60},
                ],
            },
        }

        if self.dry_run or not self._service:
            print(f"[CalendarClient] Would create event: {event_body['summary']}")
            return "dry-run-event-id"

        try:
            event = (
                self._service.events()
                .insert(calendarId=self.calendar_id, body=event_body)
                .execute()
            )
            event_id = event.get("id")
            print(f"[CalendarClient] Created event: {event_id} - {event_body['summary']}")
            self.invalidate_cache()
            return event_id
        except HttpError as e:
            raise CalendarError(f"add_shift_event failed: {e}")

    def delete_shift_event(self, event_id: str) -> bool:
        if self.dry_run or not self._service:
            print(f"[CalendarClient] Would delete event: {event_id}")
            return True

        try:
            self._service.events().delete(
                calendarId=self.calendar_id, eventId=event_id
            ).execute()
            print(f"[CalendarClient] Deleted event: {event_id}")
            self.invalidate_cache()
            return True
        except HttpError as e:
            raise CalendarError(f"delete_shift_event failed: {e}")

    def get_weekly_hours(
        self, week_start: Optional[datetime] = None
    ) -> float:
        if week_start is None:
            now = datetime.now()
            week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)

        if not self._authed:
            print("[CalendarClient] Warning: not authenticated — weekly hours unknown, assuming 0.0", file=sys.stderr)
            return 0.0

        events = self._get_cached_events(week_start, week_end)
        total_hours, _last_end = _sum_cc_hours(events, self.timezone)
        return total_hours

    def get_adjacent_events(
        self,
        offer: ParsedOffer,
        lookback_hours: float = 12,
        lookahead_hours: float = 12,
    ) -> List[Dict[str, Any]]:
        if not offer.start_time or not offer.end_time:
            return []

        query_start = offer.start_time - timedelta(hours=lookback_hours)
        query_end = offer.end_time + timedelta(hours=lookahead_hours)
        return self._get_cached_events(query_start, query_end)