# wifi-survey.ps1 — room-by-room WiFi site survey for Windows.
#
# Usage (PowerShell):
#   .\wifi-survey.ps1 scan    # list every AP/BSSID visible right now (channel, signal, band)
#   .\wifi-survey.ps1 walk    # interactive: walk room to room, samples logged to CSV
#   .\wifi-survey.ps1 link    # current connection details (SSID, BSSID, signal %, channel, rates)
#
# Walk-mode output: wifi-survey-<date>.csv in the current directory.

param([Parameter(Position = 0)][string]$Mode = "help")

$SamplesPerRoom = 5
$SampleGapSecs  = 2

function Get-LinkInfo {
    $out = netsh wlan show interfaces
    $info = @{}
    foreach ($line in $out) {
        if ($line -match '^\s*(SSID|BSSID|Signal|Channel|Radio type|Receive rate|Transmit rate|Band)\s*:\s*(.+)$') {
            $info[$Matches[1]] = $Matches[2].Trim()
        }
    }
    return $info
}

switch ($Mode) {
    "link" {
        netsh wlan show interfaces
    }
    "scan" {
        netsh wlan show networks mode=bssid
    }
    "walk" {
        $csv = "wifi-survey-{0:yyyyMMdd-HHmmss}.csv" -f (Get-Date)
        "room,timestamp,sample,signal_pct,channel,bssid,radio,band" | Out-File -Encoding utf8 $csv
        Write-Host "Walk survey started. Results -> $csv"
        Write-Host "Stand in the middle of each room, type its name, wait ~15s. Empty name = finish."
        Write-Host "Cover every room/floor you care about, including the worst corners."
        while ($true) {
            $room = Read-Host "`nRoom name (empty to finish)"
            if ([string]::IsNullOrWhiteSpace($room)) { break }
            for ($i = 1; $i -le $SamplesPerRoom; $i++) {
                $info = Get-LinkInfo
                $ts = Get-Date -Format "HH:mm:ss"
                $row = '"{0}",{1},{2},{3},{4},{5},{6},{7}' -f $room, $ts, $i,
                    $info['Signal'], $info['Channel'], $info['BSSID'], $info['Radio type'], $info['Band']
                Add-Content -Encoding utf8 $csv $row
                Write-Host ("  sample {0}/{1}: {2} ch {3} bssid {4}" -f $i, $SamplesPerRoom, $info['Signal'], $info['Channel'], $info['BSSID'])
                Start-Sleep -Seconds $SampleGapSecs
            }
        }
        Write-Host "`nDone. Now also run:  .\wifi-survey.ps1 scan   (and save its output)"
        Write-Host "Then share $csv + the scan output with Claude for analysis."
    }
    default {
        Get-Content $PSCommandPath | Select-Object -First 9
    }
}
