#!/usr/bin/env python3
"""
Calendar Bridge
───────────────
Syncs any ICS calendar feed (Outlook, Apple Calendar, etc.) to Google Calendar.

Works with work/school Outlook accounts WITHOUT Azure app registration or admin
consent. All you need is the ICS publish URL from Outlook Web and a Google Cloud
OAuth credential file.

How to get your Outlook ICS URL (no IT admin needed):
  1. Go to https://outlook.office.com
  2. Settings → View all Outlook settings → Calendar → Shared calendars
  3. Under "Publish a calendar" → choose your calendar → "Can view all details"
  4. Click Publish → copy the ICS link
  5. Paste it as ICS_URL in your .env
"""

import os
import re
import json
import time
import hashlib
import logging
import requests
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import icalendar
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

ICS_URL = os.getenv("ICS_URL", "")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
TARGET_CALENDAR_NAME = os.getenv("TARGET_CALENDAR_NAME", "Outlook (Work)")
SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
DAYS_PAST = int(os.getenv("DAYS_PAST", "30"))
DAYS_FUTURE = int(os.getenv("DAYS_FUTURE", "365"))
DATA_DIR = Path(os.getenv("DATA_DIR", "bridge_data"))

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ── ICS Source ─────────────────────────────────────────────────────────────────

class ICSSource:
    """Fetches and parses an iCalendar (.ics) feed from a URL."""

    def __init__(self, url: str):
        self.url = url

    def fetch_events(self, days_past: int, days_future: int) -> dict:
        """Returns {uid: event_dict} for events within the time window."""
        log.info("Fetching ICS feed …")
        try:
            resp = requests.get(self.url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.error(f"Failed to fetch ICS feed: {e}")
            return {}

        try:
            cal = icalendar.Calendar.from_ical(resp.content)
        except Exception as e:
            log.error(f"Failed to parse ICS content: {e}")
            return {}

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=days_past)
        window_end = now + timedelta(days=days_future)

        events: dict = {}
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            ev = self._parse_component(component)
            if ev is None:
                continue

            # Filter to the configured time window
            ev_start = ev.get("start_dt")
            if ev_start is not None:
                if isinstance(ev_start, date) and not isinstance(ev_start, datetime):
                    ev_start = datetime(ev_start.year, ev_start.month, ev_start.day,
                                        tzinfo=timezone.utc)
                if ev_start.tzinfo is None:
                    ev_start = ev_start.replace(tzinfo=timezone.utc)
                if not (window_start <= ev_start <= window_end):
                    continue

            uid = ev.get("uid", "")
            if uid:
                # Later VEVENT with same UID overrides (recurrence exception)
                events[uid] = ev

        log.info(f"Found {len(events)} events in ICS feed")
        return events

    def _parse_component(self, comp) -> Optional[dict]:
        def get_str(key: str) -> Optional[str]:
            val = comp.get(key)
            return str(val) if val is not None else None

        def get_dt(key: str):
            val = comp.get(key)
            if val is None:
                return None
            return val.dt if hasattr(val, "dt") else val

        uid = get_str("UID")
        if not uid:
            return None

        start_dt = get_dt("DTSTART")
        if start_dt is None:
            return None

        all_day = isinstance(start_dt, date) and not isinstance(start_dt, datetime)

        return {
            "uid": uid,
            "summary": get_str("SUMMARY") or "(No title)",
            "description": _strip_html(get_str("DESCRIPTION") or ""),
            "location": get_str("LOCATION") or "",
            "status": get_str("STATUS") or "CONFIRMED",
            "start_dt": start_dt,
            "end_dt": get_dt("DTEND"),
            "all_day": all_day,
        }


# ── Google Calendar Sink ───────────────────────────────────────────────────────

class GoogleCalendarSink:
    """Writes events to a named Google Calendar."""

    def __init__(self, credentials_file: str, calendar_name: str, data_dir: Path):
        self.credentials_file = credentials_file
        self.calendar_name = calendar_name
        self.token_file = data_dir / "google_token.json"
        self.service = self._authenticate()
        self.calendar_id = self._get_or_create_calendar()

    def _authenticate(self):
        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.token_file), GOOGLE_SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, GOOGLE_SCOPES
                )
                creds = flow.run_local_server(port=0)
            self.token_file.write_text(creds.to_json())
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _get_or_create_calendar(self) -> str:
        calendars = self.service.calendarList().list().execute().get("items", [])
        for cal in calendars:
            if cal.get("summary") == self.calendar_name:
                log.info(f"Using existing Google Calendar: '{self.calendar_name}'")
                return cal["id"]
        new_cal = self.service.calendars().insert(body={
            "summary": self.calendar_name,
            "description": "Synced by Calendar Bridge",
            "timeZone": "UTC",
        }).execute()
        log.info(f"Created Google Calendar: '{self.calendar_name}'")
        return new_cal["id"]

    def upsert_event(self, body: dict, existing_id: Optional[str] = None) -> str:
        """Create or update an event. Returns the Google event ID."""
        if existing_id:
            try:
                ev = self.service.events().update(
                    calendarId=self.calendar_id,
                    eventId=existing_id,
                    body=body,
                ).execute()
                return ev["id"]
            except HttpError as e:
                if e.resp.status != 404:
                    raise
                # Event missing on Google side — fall through to create

        ev = self.service.events().insert(
            calendarId=self.calendar_id,
            body=body,
        ).execute()
        return ev["id"]

    def delete_event(self, google_id: str):
        try:
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=google_id,
            ).execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _dt_to_google(dt, all_day: bool) -> dict:
    """Convert a Python datetime/date to a Google Calendar start/end dict."""
    if all_day:
        d = dt.date() if isinstance(dt, datetime) else dt
        return {"date": d.isoformat()}
    if not isinstance(dt, datetime):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return {"dateTime": dt.isoformat()}


def ics_to_google(ev: dict) -> dict:
    """Convert a parsed ICS event dict to a Google Calendar event body."""
    start = _dt_to_google(ev["start_dt"], ev["all_day"])

    end_dt = ev.get("end_dt")
    if end_dt is None:
        if ev["all_day"]:
            sd = ev["start_dt"]
            d = sd.date() if isinstance(sd, datetime) else sd
            end_dt = d + timedelta(days=1)
        else:
            sd = ev["start_dt"]
            if not isinstance(sd, datetime):
                sd = datetime(sd.year, sd.month, sd.day, tzinfo=timezone.utc)
            if sd.tzinfo is None:
                sd = sd.replace(tzinfo=timezone.utc)
            end_dt = sd + timedelta(hours=1)
    end = _dt_to_google(end_dt, ev["all_day"])

    body: dict = {
        "summary": ev["summary"],
        "location": ev.get("location") or "",
        "description": ev.get("description") or "",
        "start": start,
        "end": end,
        "extendedProperties": {
            "private": {"bridge_uid": ev["uid"]}
        },
    }
    if ev.get("status") == "CANCELLED":
        body["status"] = "cancelled"

    return body


def event_fingerprint(ev: dict) -> str:
    """SHA-256 fingerprint of an event's mutable fields (detects updates)."""
    key = json.dumps({
        "summary": ev.get("summary"),
        "description": ev.get("description"),
        "location": ev.get("location"),
        "start": str(ev.get("start_dt")),
        "end": str(ev.get("end_dt")),
        "status": ev.get("status"),
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ── Calendar Bridge ────────────────────────────────────────────────────────────

class CalendarBridge:
    """
    Coordinates ICS → Google Calendar sync.

    State file (`bridge_data/state.json`) tracks:
        { ics_uid: { "google_id": str, "hash": str } }
    """

    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        self.state_file = DATA_DIR / "state.json"
        self.state: dict = self._load_state()
        self.source = ICSSource(ICS_URL)
        self.sink = GoogleCalendarSink(
            GOOGLE_CREDENTIALS_FILE, TARGET_CALENDAR_NAME, DATA_DIR
        )

    def _load_state(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {}

    def _save_state(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    # ── Sync logic ─────────────────────────────────────────────────────────────

    def sync(self):
        log.info("── Sync start ──────────────────────────────────────────")
        ics_events = self.source.fetch_events(DAYS_PAST, DAYS_FUTURE)
        created = updated = deleted = skipped = 0

        # Upsert events present in the ICS feed
        for uid, ev in ics_events.items():
            fp = event_fingerprint(ev)
            existing = self.state.get(uid, {})

            if existing.get("hash") == fp:
                skipped += 1
                continue  # Nothing changed

            body = ics_to_google(ev)
            google_id = self.sink.upsert_event(body, existing.get("google_id"))

            if existing:
                log.info(f"  updated : {ev['summary'][:60]}")
                updated += 1
            else:
                log.info(f"  created : {ev['summary'][:60]}")
                created += 1

            self.state[uid] = {"google_id": google_id, "hash": fp}

        # Delete events that disappeared from the ICS feed
        ics_uids = set(ics_events.keys())
        for uid in list(self.state.keys()):
            if uid not in ics_uids:
                google_id = self.state[uid].get("google_id")
                if google_id:
                    self.sink.delete_event(google_id)
                    log.info(f"  deleted : {uid[:40]}")
                    deleted += 1
                del self.state[uid]

        self._save_state()
        log.info(
            f"── Done: {created} created, {updated} updated, "
            f"{deleted} deleted, {skipped} unchanged ──"
        )

    # ── Main loop ──────────────────────────────────────────────────────────────

    def run(self):
        log.info("Calendar Bridge started")
        log.info(f"  Source  : ICS feed ({ICS_URL[:60]}…)")
        log.info(f"  Target  : Google Calendar '{TARGET_CALENDAR_NAME}'")
        log.info(f"  Window  : past {DAYS_PAST}d / future {DAYS_FUTURE}d")
        log.info(f"  Interval: every {SYNC_INTERVAL_SECONDS}s")

        while True:
            try:
                self.sync()
            except Exception as e:
                log.error(f"Sync error: {e}", exc_info=True)
            log.info(f"Next sync in {SYNC_INTERVAL_SECONDS}s …")
            time.sleep(SYNC_INTERVAL_SECONDS)


# ── Entry point ────────────────────────────────────────────────────────────────

def _preflight():
    """Validate config and print friendly errors before touching any API."""
    ok = True
    if not ICS_URL:
        print("ERROR: ICS_URL is not set in .env\n")
        print("How to get your Outlook ICS URL (no IT admin needed):")
        print("  1. Open https://outlook.office.com in your browser")
        print("  2. Settings (⚙) → View all Outlook settings")
        print("  3. Calendar → Shared calendars")
        print("  4. Under 'Publish a calendar':")
        print("       • Pick the calendar you want to sync")
        print("       • Choose 'Can view all details'")
        print("       • Click Publish")
        print("  5. Copy the ICS link and set ICS_URL=<that link> in .env\n")
        ok = False
    if not Path(GOOGLE_CREDENTIALS_FILE).exists():
        print(f"ERROR: Google credentials file not found: {GOOGLE_CREDENTIALS_FILE}\n")
        print("How to get it:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create a project → Enable 'Google Calendar API'")
        print("  3. APIs & Services → Credentials → Create OAuth 2.0 Client ID")
        print("       • Application type: Desktop app")
        print("  4. Download JSON → save as google_credentials.json\n")
        ok = False
    return ok


if __name__ == "__main__":
    if not _preflight():
        raise SystemExit(1)
    CalendarBridge().run()
