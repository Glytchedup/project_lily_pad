# BOM.md — Hardware shopping list

Already owned (not listed below): **Razer BlackWidow Chroma** (original, USB) and an
**HDMI monitor**. Prices are approximate US street prices (2026); everything is stock
Raspberry Pi ecosystem gear.

## Recommended build (~$100)

| Item | Exact recommendation | Why | ~Price |
|---|---|---|---|
| Board | **Raspberry Pi 5, 4 GB** | Comfortable 1080p60 headroom for particle-heavy scenes; current board = longest support. 8 GB buys nothing for this app. | $60 |
| Power supply | **Official Raspberry Pi 27 W USB-C PD supply** | **Required, not optional**: only a negotiated 5 V/5 A supply raises the Pi 5's USB port budget from 600 mA to 1.6 A — the keyboard's ~500 mA lighting draw needs that headroom (RESEARCH.md §5). | $12 |
| microSD | **SanDisk (or Samsung) 32 GB, A2/U3** (e.g. SanDisk Extreme 32 GB) | OS + app + sounds use <4 GB; A2 rating helps boot time; bigger cards add nothing. | $9 |
| Video cable | **micro-HDMI → HDMI, 1–2 m** (official or Amazon Basics) | Pi 5/4 use micro-HDMI (port HDMI0, nearest USB-C). | $8 |
| Case + cooling | **Official Pi 5 case (fan included)** — or any case + **Official Active Cooler** | Sustained GPU load in a closed room; also keeps toddler fingers off the board. | $10 |
| **Total** | | | **~$99** |

## Budget alternative (~$70) — Raspberry Pi 4

| Item | Recommendation | ~Price |
|---|---|---|
| Raspberry Pi 4 Model B, 2 GB | Fine at 1080p60 with default particle caps | $35–45 |
| Official 15 W USB-C supply | Pi 4's USB budget is a fixed 1.2 A — keyboard fits easily | $8 |
| Same microSD, micro-HDMI cable, case w/ fan | | ~$25 |

Software/config is identical on both boards.

## Contingency (buy only if needed)

| Item | Trigger | ~Price |
|---|---|---|
| Powered USB 3 hub (e.g. Anker 4-port with 5 V adapter) | Only if VERIFY.md's full-brightness stress test shows keyboard disconnects/flicker | $15–20 |

## Explicitly not needed

- No USB hub in the base build (see PSU note above)
- No HDMI audio extractor — sound plays through the monitor's speakers; if your monitor is
  speakerless, any powered 3.5 mm PC speaker into the monitor or a USB audio dongle works
  (config `mute = true` if you'd rather have silence)
- No heatsink beyond the case fan / active cooler
