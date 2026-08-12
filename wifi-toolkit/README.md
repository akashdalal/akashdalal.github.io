# WiFi Coverage Survey Toolkit

Claude Code sessions started from the web run in a cloud container with no
wireless hardware and no access to your home network, so signal measurement
has to happen on a machine that is actually on your WiFi. This toolkit turns
your laptop into the survey instrument.

## Fastest path (recommended)

Run Claude Code **locally on your laptop** and give it the same goal:

```
cd ~ && claude
/goal make my WiFi coverage the best it can possibly be ...
```

A local session can run the scans itself, read live RSSI while you walk, and
iterate with you in real time.

## Manual path (use this toolkit)

1. **Walk survey** — measures your real coverage room by room:
   - macOS / Linux: `./wifi-survey.sh walk`
   - Windows (PowerShell): `.\wifi-survey.ps1 walk`

   Stand in the middle of each room (and the worst corners — far bathroom,
   garage, patio), type the room name, wait ~15 seconds. Include which floor
   in the name, e.g. `upstairs-bedroom`. Repeat once per band if your SSIDs
   are split (connect to the 5 GHz SSID, walk; then 2.4 GHz, walk again).

2. **Neighborhood scan** — captures every AP/BSSID visible, yours and your
   neighbors', with channels:
   - macOS / Linux: `./wifi-survey.sh scan > scan.txt`
   - Windows: `.\wifi-survey.ps1 scan > scan.txt`

3. **AP inventory** — for each access point / router / mesh node, note:
   model, firmware version, physical location, wired or wireless backhaul,
   and current settings (channel, channel width, transmit power, band
   steering, roaming features enabled).

4. **Send it back** — paste or attach `wifi-survey-*.csv`, `scan.txt`, and
   the AP inventory into the Claude session. From that data Claude can build
   the coverage map, spot dead zones / channel conflicts / roaming problems,
   and give you an exact per-AP settings plan.

## What "good" looks like (targets for the analysis)

| Metric | Target |
|---|---|
| RSSI in every room you use | better than −67 dBm (5/6 GHz) |
| RSSI worst-case (hallways, patio) | better than −72 dBm |
| SNR (RSSI − noise) | > 25 dB |
| 2.4 GHz channels | only 1, 6, or 11; 20 MHz width |
| 5 GHz channel width | 80 MHz typical; 40 MHz in dense apartments |
| Same-channel overlap with neighbors | minimized per scan data |
| Roaming between APs | 802.11k/v (+r if supported) enabled, same SSID everywhere |

See `ap-settings-checklist.md` for the full per-AP tuning checklist.
