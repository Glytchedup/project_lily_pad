# BOM.md — Hardware shopping list

Already owned (not listed below): **Razer BlackWidow Chroma** (original, USB) and an
**HDMI monitor**. Everything is stock Raspberry Pi ecosystem gear.

> **2026 price-shock note (checked 2026-08):** the LPDDR4 shortage pushed official
> prices up twice (Dec 2025, Feb 2026) and street prices further — 4 GB Pi 5 boards
> now run $110–130 at resellers. The **1 GB ($45) and 2 GB ($65) Pi 5** kept official
> pricing and are in stock at PiShop.us. Lily Pad uses well under 500 MB, so the
> **2 GB is now the recommended board** (1 GB works if you want the absolute floor).
> If prices normalize, 4 GB at ~$70–85 is a fine choice again.

## Recommended build (~$104 + shipping, 2026 market)

| Item | Exact recommendation | Why | ~Price |
|---|---|---|---|
| Board | **Raspberry Pi 5, 2 GB** (PiShop.us, at MSRP) | Same CPU/GPU as every Pi 5; this app needs <500 MB. 4 GB variants are scalped to $110+ in 2026. | $65 |
| Power supply | **Official Raspberry Pi 27 W USB-C PD supply** | **Required, not optional**: only a negotiated 5 V/5 A supply raises the Pi 5's USB port budget from 600 mA to 1.6 A — the keyboard's ~500 mA lighting draw needs that headroom (RESEARCH.md §5). | $12 |
| microSD | **SanDisk (or Samsung) 32 GB, A2/U3** (e.g. SanDisk Extreme 32 GB) | OS + app + sounds use <4 GB; A2 rating helps boot time; bigger cards add nothing. | $9 |
| Video cable | **micro-HDMI → HDMI, 1–2 m** (official or Amazon Basics) | Pi 5/4 use micro-HDMI (port HDMI0, nearest USB-C). | $8 |
| Case + cooling | **Official Pi 5 case (fan included)** — or any case + **Official Active Cooler** | Sustained GPU load in a closed room; also keeps toddler fingers off the board. | $11 |
| **Total** | | | **~$104** |

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
