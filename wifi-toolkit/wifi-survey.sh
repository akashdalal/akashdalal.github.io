#!/usr/bin/env bash
#
# wifi-survey.sh — room-by-room WiFi site survey for macOS and Linux.
#
# Usage:
#   ./wifi-survey.sh scan            # one-shot: list every AP/BSSID visible right now
#   ./wifi-survey.sh walk            # interactive: walk room to room, samples logged to CSV
#   ./wifi-survey.sh link            # show current connection details (RSSI, noise, channel, PHY rate)
#
# Output: wifi-survey-<date>.csv in the current directory (walk mode).
# On macOS, scan/link need sudo for full detail (wdutil).

set -u

OS="$(uname -s)"
CSV="wifi-survey-$(date +%Y%m%d-%H%M%S).csv"
SAMPLES_PER_ROOM=5
SAMPLE_GAP_SECS=2

# ---------- platform helpers ----------

macos_link() {
  # wdutil gives RSSI/noise/channel/txrate; needs sudo on modern macOS
  if command -v wdutil >/dev/null 2>&1; then
    sudo wdutil info 2>/dev/null | grep -E 'SSID|BSSID|RSSI|Noise|Channel|Tx Rate|PHY Mode|MCS' | sed 's/^ *//'
  else
    system_profiler SPAirPortDataType 2>/dev/null | sed -n '/Current Network Information/,/Other Local/p'
  fi
}

macos_scan() {
  # system_profiler lists other visible networks with channel + signal/noise
  system_profiler SPAirPortDataType -detailLevel full 2>/dev/null \
    | sed -n '/Other Local Wi-Fi Networks/,$p'
  echo
  echo "(Tip: for BSSID-level scans on macOS 14+, Apple removed the airport CLI."
  echo " Hold Option and click the WiFi menu bar icon for live BSSID/RSSI/channel,"
  echo " or install 'wifi-explorer'/'WiFi Signal' for full scans.)"
}

macos_rssi_sample() {
  sudo wdutil info 2>/dev/null | awk '
    /RSSI/    {rssi=$NF}
    /Noise/   {noise=$NF}
    /^ *Channel/ {ch=$NF}
    /Tx Rate/ {rate=$NF}
    /BSSID/   {bssid=$NF}
    END {printf "%s,%s,%s,%s,%s", rssi, noise, ch, rate, bssid}'
}

linux_iface() {
  iw dev 2>/dev/null | awk '/Interface/ {print $2; exit}'
}

linux_link() {
  local ifc; ifc="$(linux_iface)"
  if command -v iw >/dev/null 2>&1 && [ -n "$ifc" ]; then
    iw dev "$ifc" link
  else
    nmcli -f GENERAL.CONNECTION,WIFI-PROPERTIES device show 2>/dev/null
  fi
}

linux_scan() {
  if command -v nmcli >/dev/null 2>&1; then
    nmcli -f SSID,BSSID,CHAN,FREQ,SIGNAL,BARS,SECURITY dev wifi list --rescan yes
  else
    local ifc; ifc="$(linux_iface)"
    sudo iw dev "$ifc" scan | grep -E '^BSS|SSID:|signal:|primary channel|freq:'
  fi
}

linux_rssi_sample() {
  local ifc; ifc="$(linux_iface)"
  iw dev "$ifc" link 2>/dev/null | awk '
    /signal:/  {rssi=$2}
    /freq:/    {freq=$2}
    /tx bitrate:/ {rate=$3}
    /Connected to/ {bssid=$3}
    END {printf "%s,,%s,%s,%s", rssi, freq, rate, bssid}'
}

# ---------- commands ----------

do_link() {
  case "$OS" in
    Darwin) macos_link ;;
    Linux)  linux_link ;;
    *) echo "Unsupported OS: $OS" >&2; exit 1 ;;
  esac
}

do_scan() {
  case "$OS" in
    Darwin) macos_scan ;;
    Linux)  linux_scan ;;
    *) echo "Unsupported OS: $OS" >&2; exit 1 ;;
  esac
}

do_walk() {
  echo "room,timestamp,sample,rssi_dbm,noise_dbm,channel_or_freq,tx_rate,bssid" > "$CSV"
  echo "Walk survey started. Results -> $CSV"
  echo "Stand in the middle of each room, type its name, wait ~15s. Empty name = finish."
  echo "Cover every room/floor you care about, including the worst corners (bathroom, garage, patio)."
  while true; do
    printf "\nRoom name (empty to finish): "
    read -r room
    [ -z "$room" ] && break
    for i in $(seq 1 "$SAMPLES_PER_ROOM"); do
      case "$OS" in
        Darwin) sample="$(macos_rssi_sample)" ;;
        Linux)  sample="$(linux_rssi_sample)" ;;
      esac
      ts="$(date +%H:%M:%S)"
      echo "\"$room\",$ts,$i,$sample" >> "$CSV"
      printf "  sample %d/%d: %s\n" "$i" "$SAMPLES_PER_ROOM" "$sample"
      sleep "$SAMPLE_GAP_SECS"
    done
  done
  echo
  echo "Done. Rooms surveyed:"
  tail -n +2 "$CSV" | cut -d, -f1 | sort -u
  echo
  echo "Now also run: $0 scan   (and save its output)"
  echo "Then share $CSV + the scan output with Claude for analysis."
}

case "${1:-}" in
  scan) do_scan ;;
  walk) do_walk ;;
  link) do_link ;;
  *) grep '^#' "$0" | head -12; exit 1 ;;
esac
