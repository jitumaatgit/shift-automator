import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any

import requests

from models import ParsedOffer, ShiftDecision, ScoredOffer


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


_LOG_FILE: Optional[str] = None


def init_logging(log_file: str) -> None:
    global _LOG_FILE
    _LOG_FILE = log_file if log_file else None


def log_event(data: dict) -> None:
    if not _LOG_FILE:
        return
    entry = {"timestamp": datetime.now().isoformat(), **data}
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


@dataclass
class SMSConfig:
    staffing_number: str = ""
    personal_number: str = ""
    sms_transport: str = "stub"
    work_sim_sub_id: str = "0"
    ntfy_channel: str = ""
    cancel_warning_seconds: int = 300
    tasker_base_url: str = "http://localhost:8080"
    dry_run: bool = True


class Responder:
    """Base responder — prints actions instead of sending real texts."""

    def __init__(self, config: SMSConfig):
        self.config = config

    def _send_sms(self, to: str, body: str) -> None:
        _stderr(f"[Responder] SMS TO: {to}")
        _stderr(f"[Responder] BODY: {body[:80]}{'...' if len(body) > 80 else ''}")

    def _send_push(self, message: str, priority: str = "default", title: str = "Shift Automator", actions: Optional[List[Dict[str, str]]] = None, message_id: Optional[str] = None) -> bool:
        channel = self.config.ntfy_channel
        if not channel:
            _stderr(f"[Responder] PUSH (no channel): {message[:80]}")
            return False
        # ntfy expects priority as integer: 1=min, 2=low, 3=default, 4=high, 5=max
        priority_map = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5}
        priority_int = priority_map.get(priority, 3)
        payload: Dict[str, Any] = {
            "topic": channel,
            "message": message,
            "priority": priority_int,
            "title": title,
        }
        if actions:
            payload["actions"] = actions
        headers = {}
        if message_id:
            headers["X-Message"] = message_id
        try:
            resp = requests.post(
                "https://ntfy.sh/",
                json=payload,
                headers=headers,
                timeout=5,
            )
            status = resp.status_code
            if isinstance(status, int) and status >= 300:
                log_event({"action": "PUSH_ERROR", "topic": channel, "status": status, "error": resp.text[:200]})
                return False
            else:
                log_event({"action": "PUSH_SENT", "topic": channel, "status": status})
                return True
        except Exception as e:
            log_event({"action": "PUSH_ERROR", "topic": channel, "error": str(e)})
            return False

    def send_accept(self, offer: ParsedOffer) -> None:
        if not offer.claim_code:
            _stderr("[Responder] ERROR: No claim code to accept")
            return
        self._send_sms(self.config.staffing_number, offer.claim_code)

    def send_decline(self, offer: ParsedOffer) -> None:
        _stderr(f"[Responder] Decline for {offer.claim_code}: no-op (non-response = decline)")

    def send_pending_push(self, offer: ParsedOffer, message_id: Optional[str] = None) -> None:
        lines = [
            "\u23f3 CC Shift PENDING",
            f"{offer.title}",
            f"{offer.start_time.strftime('%a %b %d %I:%M%p')} - {offer.end_time.strftime('%I:%M%p')}" if offer.start_time else "Time unknown",
            f"{offer.duration_hours:.1f}h | {offer.display_address[:50]}",
            f"Code: {offer.claim_code}",
        ]
        if offer.cancel_number:
            lines.append(f"Cancel#: {offer.cancel_number}")
        body = "\n".join(lines)
        self._send_push(body, priority="high", message_id=message_id)

    def send_decline_push(self, scored: ScoredOffer, message_id: Optional[str] = None, claimed: bool = False) -> None:
        offer = scored.offer
        lines = [
            "\u274c CC Shift DECLINED",
            f"{offer.title}",
            f"{offer.start_time.strftime('%a %b %d %I:%M%p')} - {offer.end_time.strftime('%I:%M%p')}" if offer.start_time else "Time unknown",
            f"{offer.duration_hours:.1f}h | {offer.display_address[:50]}",
        ]
        if claimed:
            lines.append("\u26a0\ufe0f ALREADY CLAIMED — call dispatch to cancel")
            lines.append(f"Code: {offer.claim_code}")
        body = "\n".join(lines)
        self._send_push(body, priority="high", message_id=message_id)

    def send_booking_push(self, offer: ParsedOffer, booked: bool, message_id: Optional[str] = None) -> None:
        base = self.config.tasker_base_url
        code = offer.claim_code

        if booked:
            emoji = "\u2705"  # ✅
            status = "BOOKED"
            push_actions = [
                {"action": "http", "label": "CALL", "url": f"{base}/call?code={code}"},
                {"action": "http", "label": "KEEP", "url": f"{base}/keep?code={code}"},
            ]
        else:
            emoji = "\u274c"  # ❌
            status = "NOT BOOKED"
            push_actions = None

        lines = [
            f"{emoji} CC Shift {status}",
        ]
        if offer.title:
            lines.append(f"{offer.title}")
        else:
            lines.append(offer.raw_text[:80])
        if offer.start_time:
            lines.append(f"{offer.start_time.strftime('%a %b %d %I:%M%p')} - {offer.end_time.strftime('%I:%M%p')}")
        else:
            lines.append("Time unknown")
        if offer.duration_hours > 0:
            lines.append(f"{offer.duration_hours:.1f}h | {offer.display_address[:50]}")
        else:
            lines.append(offer.display_address[:50] if offer.display_address else "Address unknown")
        body = "\n".join(lines)

        self._send_push(body, priority="high", actions=push_actions, message_id=message_id)


class TermuxResponder(Responder):
    """Sends real SMS via termux-sms-send on Android."""

    def _send_sms(self, to: str, body: str) -> None:
        if self.config.dry_run:
            _stderr(f"[TermuxResponder] DRY-RUN SMS TO: {to}")
            _stderr(f"[TermuxResponder] BODY: {body[:80]}{'...' if len(body) > 80 else ''}")
            return

        cmd = [
            "termux-sms-send",
            "-s", self.config.work_sim_sub_id,
            "-n", to,
        ]
        try:
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            if p.stdin:
                p.stdin.write(body)
                p.stdin.close()
            log_event({"action": "SMS_SENT", "to": to, "via_sim": self.config.work_sim_sub_id})
        except FileNotFoundError:
            _stderr("[TermuxResponder] termux-sms-send not found — are you in Termux?")
        except OSError as e:
            _stderr(f"[TermuxResponder] SMS spawn error: {e}")


class TwilioResponder(Responder):
    """Sends real SMS via Twilio API (cloud number, works anywhere)."""

    def __init__(self, config: SMSConfig, twilio_sid: str = "", twilio_token: str = "", twilio_from: str = ""):
        super().__init__(config)
        self.twilio_sid = twilio_sid
        self.twilio_token = twilio_token
        self.twilio_from = twilio_from

    def _send_sms(self, to: str, body: str) -> None:
        if self.config.dry_run:
            _stderr(f"[TwilioResponder] DRY-RUN SMS TO: {to}")
            _stderr(f"[TwilioResponder] BODY: {body[:80]}{'...' if len(body) > 80 else ''}")
            return

        if not self.twilio_sid:
            _stderr("[TwilioResponder] No Twilio credentials configured")
            return

        try:
            resp = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json",
                auth=(self.twilio_sid, self.twilio_token),
                data={"From": self.twilio_from, "To": to, "Body": body},
                timeout=15,
            )
            if resp.status_code >= 300:
                _stderr(f"[TwilioResponder] SMS FAILED: {resp.status_code} {resp.text[:200]}")
            else:
                log_event({"action": "SMS_SENT", "to": to, "transport": "twilio"})
        except Exception as e:
            _stderr(f"[TwilioResponder] SMS error: {e}")


def create_responder(config: SMSConfig, **kwargs) -> Responder:
    transport = config.sms_transport
    if transport == "termux":
        return TermuxResponder(config)
    elif transport == "twilio":
        return TwilioResponder(config, **kwargs)
    return Responder(config)
