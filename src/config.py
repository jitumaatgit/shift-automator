"""Centralized config management. All defaults live here."""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TYPE_CHECKING
from pathlib import Path
import yaml

if TYPE_CHECKING:
    from calendar_client import CalendarClient


@dataclass(frozen=True)
class Config:
    dry_run: bool = True
    auto_decline_threshold: float = -5.0
    active_rules: tuple = (
        "wakefulness_gate",
        "calendar_conflict",
        "day_hours_cap",
        "post_cap_break",
        "rest_gap_sleep",
        "location_preference",
        "shift_type_preference",
        "title_preference",
        "time_of_day",
        "overnight_shift",
    )
    overnight_veto_start_hour: int = 0
    overnight_veto_end_hour: int = 6
    location_preferences: Dict[str, list] = field(
        default_factory=lambda: {"liked": [], "disliked": []}
    )
    location_liked_bonus: float = 3.0
    location_disliked_penalty: float = 3.0
    shift_type_preferences: Dict[str, float] = field(default_factory=dict)
    title_preferences: Dict[str, float] = field(
        default_factory=lambda: {"FD": 3.0, "J1": 1.0, "CBA": 1.0}
    )
    title_keywords: Dict[str, float] = field(default_factory=dict)
    preferred_hours: tuple = ((6, 18),)
    preferred_time_bonus: float = 1.0
    undesired_hours: tuple = ((0, 5), (22, 24))
    undesired_time_penalty: float = 2.0
    veto_undesired_hours: bool = False
    weekly_hours_cap: float = 40.0
    rest_gap_penalty: float = -10.0
    rest_gap_sleep_start: int = 22
    rest_gap_sleep_end: int = 6
    rest_gap_sleep_hours: float = 7.0
    day_hours_cap: float = 16.0
    post_cap_break_hours: float = 8.0
    wakefulness_gate_start: int = 0
    wakefulness_gate_end: int = 6
    wakefulness_gate_current: int = 5
    staffing_number: str = ""
    personal_number: str = ""
    sms_transport: str = "stub"
    work_sim_sub_id: str = "0"
    ntfy_channel: str = ""
    tasker_base_url: str = "http://localhost:8080"
    cancel_warning_seconds: int = 300
    calendar_cache_ttl_seconds: int = 60
    log_file: str = "shift_automator_log.json"
    log_level: str = "INFO"
    calendar_id: str = "primary"
    calendar_credentials_path: str = "credentials.json"
    calendar_timezone: str = "America/Los_Angeles"
    dispatch_number: str = "+15035550101"


@dataclass
class RunState:
    calendar: Optional[CalendarClient] = None
    weekly_hours: float = 0.0


DEFAULTS: Dict[str, Any] = {
    "dry_run": True,
    "auto_decline_threshold": -5.0,
    "active_rules": [
        "wakefulness_gate",
        "calendar_conflict",
        "day_hours_cap",
        "post_cap_break",
        "rest_gap_sleep",
        "location_preference",
        "shift_type_preference",
        "title_preference",
        "time_of_day",
        "overnight_shift",
    ],
    "overnight_veto_start_hour": 0,
    "overnight_veto_end_hour": 6,
    "location_preferences": {"liked": [], "disliked": []},
    "location_liked_bonus": 3.0,
    "location_disliked_penalty": 3.0,
    "shift_type_preferences": {},
    "title_preferences": {"FD": 3.0, "J1": 1.0, "CBA": 1.0},
    "title_keywords": {},
    "preferred_hours": [(6, 18)],
    "preferred_time_bonus": 1.0,
    "undesired_hours": [(0, 5), (22, 24)],
    "undesired_time_penalty": 2.0,
    "veto_undesired_hours": False,
    "weekly_hours_cap": 40.0,
    "rest_gap_penalty": -10.0,
    "rest_gap_sleep_start": 22,
    "rest_gap_sleep_end": 6,
    "rest_gap_sleep_hours": 7.0,
    "day_hours_cap": 16.0,
    "post_cap_break_hours": 8.0,
    "wakefulness_gate_start": 0,
    "wakefulness_gate_end": 6,
    "wakefulness_gate_current": 5,
    "staffing_number": "",
    "personal_number": "",
    "sms_transport": "stub",
    "work_sim_sub_id": "0",
    "ntfy_channel": "",
    "tasker_base_url": "http://localhost:8080",
    "cancel_warning_seconds": 300,
    "calendar_cache_ttl_seconds": 60,
    "log_file": "shift_automator_log.json",
    "log_level": "INFO",
    "calendar_id": "primary",
    "calendar_credentials_path": "credentials.json",
    "calendar_timezone": "America/Los_Angeles",
    "dispatch_number": "+15035550101",
}


def _deep_merge(base: Dict, overlay: Dict) -> Dict:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Optional[str] = None) -> Config:
    """Load YAML config, merged over DEFAULTS. Returns frozen Config dataclass."""
    merged = copy.deepcopy(DEFAULTS)
    if path and Path(path).exists():
        with open(path, "r") as f:
            user = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, user)
    for list_field in ("active_rules", "preferred_hours", "undesired_hours"):
        if list_field in merged and isinstance(merged[list_field], list):
            merged[list_field] = tuple(merged[list_field])
    kwargs = {k: v for k, v in merged.items() if k in Config.__dataclass_fields__}
    return Config(**kwargs)
