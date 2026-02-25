# Calendar Bridge

Syncs any ICS calendar feed (Outlook, Apple Calendar, etc.) → Google Calendar,
running automatically every 15 minutes via GitHub Actions.

No Azure app registration or IT admin approval needed — just an ICS publish URL
from Outlook Web and a Google Cloud OAuth credential file.

---

## Prerequisites

- A GitHub account (the repo is already here)
- A Google account (the target calendar)
- An Outlook account (work/school or personal)

---

## Step 1 — Get your Outlook ICS URL

1. Open [outlook.office.com](https://outlook.office.com) in your browser
2. Click **Settings (⚙)** → **View all Outlook settings**
3. Go to **Calendar → Shared calendars**
4. Under **Publish a calendar**:
   - Pick the calendar you want to sync
   - Set permission to **"Can view all details"**
   - Click **Publish**
5. Copy the **ICS** link (not the HTML one)

---

## Step 2 — Create Google OAuth credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable the **Google Calendar API**:
   - APIs & Services → Library → search "Google Calendar API" → Enable
4. Create credentials:
   - APIs & Services → Credentials → **Create Credentials** → OAuth 2.0 Client ID
   - Application type: **Desktop app**
   - Click **Create**
5. Download the JSON file → save it as `google_credentials.json`

---

## Step 3 — Get the initial Google OAuth token (run locally once)

You need to authenticate with Google once to generate a token. Do this on your
local machine:

```bash
cd calendar-bridge
pip install -r requirements.txt

# Copy your downloaded credentials file here
cp ~/Downloads/google_credentials.json .

# Set your ICS URL
export ICS_URL="<paste your ICS URL here>"

python bridge.py --once
```

A browser window will open — sign in and grant access. This creates
`bridge_data/google_token.json`.

---

## Step 4 — Add GitHub Secrets

Go to your repo on GitHub → **Settings → Secrets and variables → Actions → New repository secret**.

Add these secrets:

| Secret name              | Value                                                  |
|--------------------------|--------------------------------------------------------|
| `ICS_URL`                | The ICS URL from Step 1                                |
| `GOOGLE_CREDENTIALS_JSON`| Full contents of `google_credentials.json`             |
| `GOOGLE_TOKEN_JSON`      | Full contents of `bridge_data/google_token.json`       |
| `GH_PAT`                 | A GitHub Personal Access Token (see below)             |

### Creating the `GH_PAT`

The workflow needs a PAT to update the `GOOGLE_TOKEN_JSON` secret after each
run (so the token stays fresh).

1. Go to GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Set **Repository access** to this repo only
4. Under **Permissions → Repository permissions**, enable:
   - **Secrets** → Read and write
5. Click **Generate token** → copy and save as the `GH_PAT` secret

---

## Step 5 — Enable the workflow

The workflow file is already at `.github/workflows/calendar-bridge.yml`. It
runs automatically every 15 minutes once the secrets are in place.

To trigger it immediately:
- Go to **Actions → Calendar Bridge Sync → Run workflow**

---

## Optional configuration

Set these as **Actions variables** (Settings → Secrets and variables → Variables)
to override the defaults:

| Variable              | Default          | Description                          |
|-----------------------|------------------|--------------------------------------|
| `TARGET_CALENDAR_NAME`| `Outlook (Work)` | Name of the Google Calendar to sync into |
| `DAYS_PAST`           | `30`             | How many past days to sync           |
| `DAYS_FUTURE`         | `365`            | How many future days to sync         |

---

## How it works

```
Every 15 min
    │
    ▼
GitHub Actions
    │
    ├── Fetches ICS feed from Outlook URL
    ├── Compares events against last known state (cached)
    ├── Creates / updates / deletes events in Google Calendar
    └── Persists refreshed OAuth token back to GitHub Secrets
```

State is cached between runs so only changed events are processed.
