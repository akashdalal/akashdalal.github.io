#!/usr/bin/env python3
"""
Outlook -> Google Calendar Sync Tool
Syncs Microsoft Outlook calendar events to Google Calendar every minute.
Similar to ShadowCal — runs continuously and keeps your Google Calendar
as a read-only mirror of your Outlook calendar.

Usage:
    python sync.py

On first run, you will be prompted to authenticate with both Microsoft and Google.
Tokens are cached locally so subsequent runs are automatic.
"""

import json
import os
import re
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import msal
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Persistent storage ──────────────────────────────────────────────────────
DATA_DIR = Path("sync_data")
OUTLOOK_TOKEN_FILE = DATA_DIR / "outlook_token.json"
GOOGLE_TOKEN_FILE = DATA_DIR / "google_token.json"
EVENT_MAP_FILE = DATA_DIR / "event_map.json"       # outlook_id -> google_id
DELTA_LINK_FILE = DATA_DIR / "delta_link.json"     # incremental-sync bookmark

# ── API scopes ───────────────────────────────────────────────────────────────
GRAPH_SCOPES = ["https://graph.microsoft.com/Calendars.Read"]
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ────────────────────────────────────────────────────────────────────────────
# Microsoft Outlook (Graph API) client
# ────────────────────────────────────────────────────────────────────────────

class OutlookClient:
    """Reads calendar events from Microsoft Outlook via the Graph API."""

    def __init__(self, client_id: str, tenant_id: str):
        self.client_id = client_id
        self.tenant_id = tenant_id
        self._cache = msal.SerializableTokenCache()
        self._load_cache()
        self._app = self._make_app()

    # ── internal helpers ──────────────────────────────────────────────────

    def _make_app(self) -> msal.PublicClientApplication:
        return msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=self._cache,
        )

    def _load_cache(self):
        if OUTLOOK_TOKEN_FILE.exists():
            self._cache.deserialize(OUTLOOK_TOKEN_FILE.read_text())

    def _persist_cache(self):
        if self._cache.has_state_changed:
            OUTLOOK_TOKEN_FILE.write_text(self._cache.serialize())

    def _get_token(self) -> str:
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._persist_cache()
                return result["access_token"]

        # Device-code flow (works headlessly / in SSH sessions)
        flow = self._app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(
                f"Could not start device flow: {flow.get('error_description', flow)}"
            )
        print("\n" + "=" * 60)
        print("  OUTLOOK AUTHENTICATION REQUIRED")
        print("=" * 60)
        print(f"  1. Open:  {flow['verification_uri']}")
        print(f"  2. Enter: {flow['user_code']}")
        print("=" * 60 + "\n")

        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(
                f"Outlook auth failed: {result.get('error_description', result)}"
            )
        self._persist_cache()
        logger.info("Outlook: authenticated successfully")
        return result["access_token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    # ── public API ────────────────────────────────────────────────────────

    def get_events_delta(
        self, delta_link: Optional[str] = None
    ) -> tuple[list[dict], str]:
        """
        Fetch changed/new/deleted events via Graph delta query.

        Returns:
            (events, new_delta_link)

        On the first call (delta_link=None) a full sync of the next
        SYNC_DAYS days is performed.  Every subsequent call uses the
        delta link so only changes are returned.
        """
        sync_days = int(os.getenv("SYNC_DAYS", "60"))

        if delta_link:
            url: Optional[str] = delta_link
        else:
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=sync_days)
            params = (
                f"?startDateTime={now:%Y-%m-%dT%H:%M:%SZ}"
                f"&endDateTime={end:%Y-%m-%dT%H:%M:%SZ}"
                "&$select=id,subject,body,start,end,location,"
                "isAllDay,isCancelled,organizer,attendees,type,seriesMasterId"
            )
            url = f"{GRAPH_BASE}/me/calendarView/delta{params}"

        events: list[dict] = []
        new_delta_link = ""

        while url:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            events.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            if not url:
                new_delta_link = data.get("@odata.deltaLink", "")

        return events, new_delta_link


# ────────────────────────────────────────────────────────────────────────────
# Google Calendar client
# ────────────────────────────────────────────────────────────────────────────

class GoogleCalendarClient:
    """Writes/updates/deletes calendar events in Google Calendar."""

    def __init__(self, credentials_file: str, calendar_id: str = "primary"):
        self.credentials_file = credentials_file
        self.calendar_id = calendar_id
        self.service = None

    def authenticate(self):
        creds: Optional[Credentials] = None
        if GOOGLE_TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(
                str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Google: refreshing access token…")
                creds.refresh(Request())
            else:
                print("\n" + "=" * 60)
                print("  GOOGLE CALENDAR AUTHENTICATION REQUIRED")
                print("=" * 60)
                print("  A browser window will open. Sign in and grant access.")
                print("=" * 60 + "\n")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, GOOGLE_SCOPES
                )
                creds = flow.run_local_server(port=0)

            GOOGLE_TOKEN_FILE.write_text(creds.to_json())
            logger.info("Google: authenticated successfully")

        self.service = build("calendar", "v3", credentials=creds)

    def get_or_create_calendar(self, name: str) -> str:
        """Return calendar ID for *name*, creating it if it doesn't exist."""
        items = self.service.calendarList().list().execute().get("items", [])
        for cal in items:
            if cal["summary"] == name:
                logger.info(f"Google: using existing calendar '{name}' ({cal['id']})")
                return cal["id"]

        new = self.service.calendars().insert(body={
            "summary": name,
            "description": "Read-only mirror of Microsoft Outlook (auto-synced)",
            "timeZone": "UTC",
        }).execute()
        logger.info(f"Google: created calendar '{name}' ({new['id']})")
        return new["id"]

    def create_event(self, body: dict) -> str:
        result = self.service.events().insert(
            calendarId=self.calendar_id, body=body
        ).execute()
        return result["id"]

    def update_event(self, google_id: str, body: dict):
        self.service.events().update(
            calendarId=self.calendar_id, eventId=google_id, body=body
        ).execute()

    def delete_event(self, google_id: str):
        try:
            self.service.events().delete(
                calendarId=self.calendar_id, eventId=google_id
            ).execute()
        except HttpError as e:
            if e.resp.status != 410:  # 410 = already deleted — ignore
                raise


# ────────────────────────────────────────────────────────────────────────────
# Event conversion helpers
# ────────────────────────────────────────────────────────────────────────────

_HTML_TAG = re.compile(r"<[^>]+>")
_MULTI_BLANK = re.compile(r"\n{3,}")


def _strip_html(text: str) -> str:
    return _MULTI_BLANK.sub("\n\n", _HTML_TAG.sub("", text)).strip()


def _build_description(ev: dict) -> str:
    parts: list[str] = []

    body_content = ev.get("body", {}).get("content", "").strip()
    if body_content:
        if ev.get("body", {}).get("contentType") == "html":
            body_content = _strip_html(body_content)
        if body_content:
            parts.append(body_content)

    organizer = ev.get("organizer", {}).get("emailAddress", {})
    if organizer.get("name"):
        parts.append(
            f"\nOrganizer: {organizer['name']} <{organizer.get('address', '')}>"
        )

    attendees = ev.get("attendees", [])
    if attendees:
        lines = [
            f"  - {a['emailAddress'].get('name', a['emailAddress']['address'])} "
            f"({a.get('status', {}).get('response', 'none')})"
            for a in attendees
        ]
        parts.append("\nAttendees:\n" + "\n".join(lines))

    parts.append("\n[Synced from Microsoft Outlook]")
    return "\n".join(parts)


def _normalize_dt(dt: str) -> str:
    """Ensure datetime strings end with Z if no offset is present."""
    if dt and not dt.endswith("Z") and "+" not in dt and (len(dt) < 6 or dt[-6] not in ("+", "-")):
        return dt + "Z"
    return dt


def outlook_to_google(ev: dict) -> dict:
    """Convert a Graph API event dict to a Google Calendar event body."""
    is_all_day = ev.get("isAllDay", False)

    if is_all_day:
        # Graph returns full datetime even for all-day; truncate to date
        start_date = ev["start"]["dateTime"][:10]
        end_date = ev["end"]["dateTime"][:10]
        time_part = {
            "start": {"date": start_date},
            "end": {"date": end_date},
        }
    else:
        s_dt = _normalize_dt(ev["start"]["dateTime"])
        e_dt = _normalize_dt(ev["end"]["dateTime"])
        time_part = {
            "start": {"dateTime": s_dt, "timeZone": ev["start"].get("timeZone", "UTC")},
            "end": {"dateTime": e_dt, "timeZone": ev["end"].get("timeZone", "UTC")},
        }

    google_ev: dict = {
        "summary": ev.get("subject") or "(No Title)",
        "description": _build_description(ev),
        "status": "cancelled" if ev.get("isCancelled") else "confirmed",
        **time_part,
    }

    loc = ev.get("location", {}).get("displayName", "")
    if loc:
        google_ev["location"] = loc

    return google_ev


# ────────────────────────────────────────────────────────────────────────────
# Main sync coordinator
# ────────────────────────────────────────────────────────────────────────────

class CalendarSyncer:

    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)

        client_id = os.getenv("OUTLOOK_CLIENT_ID")
        tenant_id = os.getenv("OUTLOOK_TENANT_ID", "common")
        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
        self.calendar_name = os.getenv("TARGET_CALENDAR_NAME", "Outlook Sync")
        self.sync_interval = int(os.getenv("SYNC_INTERVAL_SECONDS", "60"))

        if not client_id:
            raise ValueError(
                "OUTLOOK_CLIENT_ID is not set. "
                "Copy .env.example to .env and fill in your values."
            )
        if not Path(creds_file).exists():
            raise FileNotFoundError(
                f"Google credentials file not found: {creds_file}\n"
                "Download it from the Google Cloud Console (OAuth 2.0 Client ID → Desktop)."
            )

        self.outlook = OutlookClient(client_id, tenant_id)
        self.google = GoogleCalendarClient(creds_file)

        self._event_map: dict[str, str] = self._load_json(EVENT_MAP_FILE, {})
        self._delta_link: Optional[str] = self._load_json(DELTA_LINK_FILE, {}).get("link")

    # ── persistence helpers ───────────────────────────────────────────────

    @staticmethod
    def _load_json(path: Path, default):
        return json.loads(path.read_text()) if path.exists() else default

    def _save_event_map(self):
        EVENT_MAP_FILE.write_text(json.dumps(self._event_map, indent=2))

    def _save_delta_link(self, link: str):
        DELTA_LINK_FILE.write_text(
            json.dumps({"link": link, "saved_at": datetime.now().isoformat()}, indent=2)
        )
        self._delta_link = link

    # ── lifecycle ─────────────────────────────────────────────────────────

    def setup(self):
        """Authenticate with both services (interactive on first run)."""
        logger.info("Authenticating with Microsoft Outlook…")
        # Force a token fetch to trigger auth if needed
        self.outlook._get_token()

        logger.info("Authenticating with Google Calendar…")
        self.google.authenticate()

        cal_id = self.google.get_or_create_calendar(self.calendar_name)
        self.google.calendar_id = cal_id
        logger.info("Setup complete.")

    # ── sync logic ────────────────────────────────────────────────────────

    def sync_once(self) -> tuple[int, int, int]:
        """
        Run a single sync pass.
        Returns (created, updated, deleted) counts.
        """
        try:
            events, new_delta = self.outlook.get_events_delta(self._delta_link)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 410:
                # Delta link expired; fall back to full sync
                logger.warning("Delta link expired — running full sync…")
                self._delta_link = None
                events, new_delta = self.outlook.get_events_delta(None)
            else:
                raise

        created = updated = deleted = 0

        for ev in events:
            oid = ev["id"]
            is_removed = "@removed" in ev or ev.get("isCancelled", False)

            if is_removed:
                if oid in self._event_map:
                    try:
                        self.google.delete_event(self._event_map.pop(oid))
                        deleted += 1
                        logger.debug(f"Deleted: {ev.get('subject', oid)}")
                    except Exception as exc:
                        logger.error(f"Delete failed for {oid}: {exc}")
            else:
                body = outlook_to_google(ev)
                if oid in self._event_map:
                    try:
                        self.google.update_event(self._event_map[oid], body)
                        updated += 1
                        logger.debug(f"Updated: {ev.get('subject', oid)}")
                    except HttpError as exc:
                        if exc.resp.status == 404:
                            # Was deleted on Google side; recreate
                            gid = self.google.create_event(body)
                            self._event_map[oid] = gid
                            created += 1
                        else:
                            logger.error(f"Update failed for {oid}: {exc}")
                else:
                    try:
                        gid = self.google.create_event(body)
                        self._event_map[oid] = gid
                        created += 1
                        logger.debug(f"Created: {ev.get('subject', oid)}")
                    except Exception as exc:
                        logger.error(f"Create failed for {oid}: {exc}")

        self._save_event_map()
        if new_delta:
            self._save_delta_link(new_delta)

        return created, updated, deleted

    # ── main loop ─────────────────────────────────────────────────────────

    def run(self):
        """Run the sync loop indefinitely."""
        logger.info(
            f"Outlook → Google Calendar sync started "
            f"(interval: {self.sync_interval}s, target: '{self.calendar_name}')"
        )
        while True:
            try:
                c, u, d = self.sync_once()
                if c or u or d:
                    logger.info(f"Sync: +{c} created  ~{u} updated  -{d} deleted")
                else:
                    logger.info("Sync: no changes")
            except Exception as exc:
                logger.error(f"Sync error: {exc}", exc_info=True)

            logger.debug(f"Sleeping {self.sync_interval}s…")
            time.sleep(self.sync_interval)


# ────────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Outlook → Google Calendar Sync")
    print("=" * 60)
    syncer = CalendarSyncer()
    syncer.setup()
    syncer.run()


if __name__ == "__main__":
    main()
