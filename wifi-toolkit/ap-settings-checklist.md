# AP Settings Checklist

Apply per access point once the survey data says where the problems are.
These are the settings that account for nearly all real-world WiFi problems.

## Placement (fix this before any setting)
- [ ] APs central and high (shelf/ceiling), not in a closet, cabinet, or floor corner.
- [ ] Not directly behind/next to: TVs, mirrors, fish tanks, refrigerators, metal racks, microwave.
- [ ] Multi-AP: aim for cell edges around −67 dBm where cells meet, not full overlap.
- [ ] Mesh nodes: wired (Ethernet/MoCA) backhaul wherever possible; wireless backhaul halves throughput per hop and each node must hear its parent at better than −65 dBm.

## Radio — 2.4 GHz
- [ ] Channel: **1, 6, or 11 only** (never 3, 8, "auto" that lands elsewhere). Pick the least occupied per the scan.
- [ ] Width: **20 MHz** (40 MHz on 2.4 GHz causes more interference than it adds speed).
- [ ] Transmit power: **medium/50–75%**, not max — max power creates one-way links (client can hear AP, AP can't hear client) and breaks roaming.
- [ ] Legacy rates disabled: set minimum/basic rate to 12 or 24 Mbps (drops 802.11b beacons, shrinks airtime waste).

## Radio — 5 GHz / 6 GHz
- [ ] Channel: static, non-overlapping per AP (e.g. 36 / 52 / 149 for three APs). DFS channels (52–144) are fine unless near an airport/weather radar — if the survey shows random dropouts, move off DFS.
- [ ] Width: **80 MHz** houses, **40 MHz** dense apartments; 160 MHz only if the scan shows a quiet spectrum.
- [ ] Transmit power: high is OK on 5 GHz single-AP; **medium** on multi-AP so clients roam instead of clinging.

## SSID / roaming
- [ ] One SSID for all APs and both bands (band steering on), unless a specific IoT device needs a 2.4-only SSID.
- [ ] 802.11k and 802.11v enabled; 802.11r if all clients are modern (some old IoT breaks with r).
- [ ] Minimum RSSI / "smart roam" ~ −75 dBm on multi-AP setups so sticky clients get nudged.
- [ ] Same security everywhere: WPA2/WPA3 transitional (WPA3-only still breaks some devices).

## Features to disable (common harm, rare benefit)
- [ ] "Smart Connect" variants that are just DNS-level traffic shaping.
- [ ] WMM power-save if you see IoT dropouts.
- [ ] Extenders/repeaters that rebroadcast the SSID with WDS — replace with wired APs or proper mesh.
- [ ] Any leftover old router still broadcasting (double-NAT + interference).

## Verify after changes
- Re-run the walk survey; every room should hit the targets in README.md.
- Test roaming: start a continuous ping, walk between AP zones, expect < 1 s of loss.
- Speed test in the worst room, wired baseline first, expect ≥ 50% of wired in the worst spot on 5 GHz.
