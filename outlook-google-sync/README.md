# Outlook → Google Calendar Sync

A lightweight, self-hosted tool that mirrors your Microsoft Outlook calendar into
Google Calendar **every minute** — similar to [ShadowCal](https://shadowcal.com/),
but running entirely on your own machine with no third-party service involved.

## How it works

1. Reads events from your Outlook calendar using the **Microsoft Graph API** (delta queries — only changed events are fetched after the first sync).
2. Creates, updates, or deletes the corresponding events in a dedicated Google Calendar (default name: **"Outlook Sync"**).
3. Sleeps for 60 seconds, then repeats indefinitely.

All state (OAuth tokens, event ID mapping, delta bookmark) is stored in a local
`sync_data/` directory so the process can be stopped and restarted safely.

---

## Prerequisites

- Python 3.10+
- A **Microsoft Azure App Registration** (free)
- A **Google Cloud project** with the Calendar API enabled (free)

---

## Setup

### 1 — Clone / download

```bash
cd outlook-google-sync
pip install -r requirements.txt
```

---

### 2 — Microsoft Azure App Registration

You need to register an app so the script can read your Outlook calendar.

1. Go to [portal.azure.com](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**.
2. Give it any name (e.g. "Calendar Sync").
3. Under **Supported account types** choose:
   - *"Accounts in any organizational directory and personal Microsoft accounts"* — if you use a personal Outlook/Hotmail/Live account.
   - Your specific tenant — if you use a work/school Microsoft 365 account.
4. No redirect URI needed (device-code flow is used).
5. Click **Register**.
6. Copy the **Application (client) ID** — you'll need this.
7. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated** → add `Calendars.Read`.
8. Click **Grant admin consent** (or ask your IT admin to do so for work accounts).

---

### 3 — Google Cloud project & credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create or select a project.
2. Enable the **Google Calendar API** (search for it in the API library).
3. Go to **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID**.
4. Application type: **Desktop app**.
5. Download the JSON file and save it as `google_credentials.json` in this directory.
6. On the **OAuth consent screen**, add your Google account as a **test user** (required while the app is in testing mode).

---

### 4 — Configure

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:

```env
OUTLOOK_CLIENT_ID=<your Azure app client ID>
GOOGLE_CREDENTIALS_FILE=google_credentials.json
```

All other values have sensible defaults.

---

### 5 — Run

```bash
python sync.py
```

**First run:** You will be prompted to authenticate with both Microsoft (device-code
flow — visit a URL and enter a code) and Google (browser OAuth flow). Tokens are
cached in `sync_data/` so you only need to do this once.

After authentication the initial full sync runs, then the tool loops every
60 seconds printing a one-line status:

```
2024-03-01 09:00:00 [INFO] Sync: +12 created  ~0 updated  -0 deleted
2024-03-01 09:01:00 [INFO] Sync: no changes
2024-03-01 09:02:00 [INFO] Sync: ~1 updated  -0 deleted
```

---

### Running as a background service (optional)

**macOS / Linux — systemd user service**

Create `~/.config/systemd/user/outlook-sync.service`:

```ini
[Unit]
Description=Outlook → Google Calendar Sync

[Service]
WorkingDirectory=/path/to/outlook-google-sync
ExecStart=/usr/bin/python3 /path/to/outlook-google-sync/sync.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now outlook-sync.service
journalctl --user -fu outlook-sync.service   # view logs
```

**macOS — launchd**

```bash
nohup python sync.py >> sync.log 2>&1 &
```

---

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `OUTLOOK_CLIENT_ID` | *(required)* | Azure app client ID |
| `OUTLOOK_TENANT_ID` | `common` | Azure tenant ID or `common` |
| `GOOGLE_CREDENTIALS_FILE` | `google_credentials.json` | Path to Google OAuth JSON |
| `TARGET_CALENDAR_NAME` | `Outlook Sync` | Google Calendar to write into |
| `SYNC_INTERVAL_SECONDS` | `60` | Seconds between syncs |
| `SYNC_DAYS` | `60` | Days ahead to sync on first run |

---

## Notes

- Events are **read-only mirrored** — changes made in the Google "Outlook Sync" calendar are not written back to Outlook.
- The delta query only fetches events within the `SYNC_DAYS` window set on the first run. To extend the window, delete `sync_data/delta_link.json` to force a fresh full sync.
- Cancellations and deletions in Outlook are propagated to Google.
- `sync_data/` should not be committed to version control — it contains OAuth tokens.
