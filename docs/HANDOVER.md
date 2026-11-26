# Handover: Lily Pad after the 2026-11-26 Pi deploy

_Written 2026-11-26 at the end of the deploy session._

## Goal

Dave wanted a big visual upgrade of the toddler app on the Raspberry Pi: painted art, Lily, storybook cards, the album, parties, the parade and the narrator. He then asked for the Pi to start correctly however it gets power-cycled or reset. Both are done and deployed. What remains is optional follow-up work: performance tuning, porting features from the August branch, the letter V repaint and a tagged release.

## State

- **The Pi runs `71dbbd1` (main) and is locked.**
  - It shows `overlayroot overlay` and `/boot/firmware` is `ro`, and `lilypad` is active.
  - Dave played it hands-on and reported "everything is working good".
  - Cold boot passed with the monitor unplugged and the Pi powered on first.
  - `main` is ahead of the card by docs and CI commits only. Nothing needs a redeploy.
- **Boot robustness (`1f1de52`).** `install.sh` saves the attached monitor's EDID to `/lib/firmware/edid/lilypad-HDMI-A-2.bin` and adds `drm.edid_firmware=HDMI-A-2:edid/lilypad-HDMI-A-2.bin` to `cmdline.txt`.
  - Without the pin, a Pi that boots before the monitor invents a CVT 1080p timing (172.8 MHz). The ASUS VE276 shows that as "out of range", and HDMI audio fails with error 524.
  - The card already had the overlay, `fsck.repair=yes`, `video=...@60D`, getty off, sysrq 0 and `Restart=on-failure`.
- **Remote screen view (`fd73bc6`).** `sudo kill -USR1 $(systemctl show lilypad -p MainPID --value)` writes `/run/lilypad/frame.png`, which lives in RAM, so nothing touches the card. Verified live on the Pi.
- **Tools.** `tools/pi/find_pi.ps1` finds the Pi. `tools/pi/pi_run.ps1` covers the rest:
  - `-Script` / `-Command` run a script on the Pi.
  - `-Restart` always ends with the app running.
  - `-Fetch` copies a file off the Pi with scp.
- **Installer.** `install.sh` now runs `apt-get install --no-upgrade` (`750c836`), so a deploy never moves system packages again.
- **CI (`0a9dad1`).** GitHub Actions runs pytest and `--smoke 6` on Python 3.11 and 3.13, plus `bash -n` and `shellcheck -S error` on `install.sh`. It is green as of `603ba90`.
- **Tests.** The local suite has 1780 passed, 6 skipped.
- **Bench on the Pi at 1080p (VERIFY §7c).** All three scenarios miss the 16.7 ms p95 target:
  - party: 58.6 fps, p95 17.1 ms
  - heavy: 54.2 fps, p95 20.5 ms
  - parade: 55.9 fps, p95 24.9 ms

  The engine's `min_scale` hit its 0.25 floor in all three. There is no on-device baseline for the old build.
- **Ground-Zero.** PR https://github.com/Glytchedup/Ground-Zero/pull/20 (branch `lily-pad/visual-upgrade-2026-11-25`) carries the registry updates. It is open and needs merging.

## Next step

1. **Ask Dave which follow-up he wants first.** Nothing is broken. The candidates are:
   - **Frame rate:** an A/B of `effects.fx_style = "glow"` on the Pi.
     - Use `python -m lilypad.bench --scenario party --display --config <temp copy>`, so `/etc` stays untouched.
     - It stops the app, so ask Dave first, and use `pi_run.ps1 -Restart`.
   - **Port features from `worktree-improvements-and-testing` (PR #4).** Do them one feature at a time with tests, in this order:
     1. `--doctor`
     2. HDMI audio
     3. punctuation shapes
     4. backend tests

     Skip what `main` already covers (screen sleep, Pip's gaze). Close PR #4 when done.
   - **Letter V repaint** (about $0.15): see Parked.
   - **First tagged release:** everything is still under `[Unreleased]`.
2. Merge Ground-Zero PR #20, or update it when the next steps change.

**Deploy recipe**, for the next time code must reach the Pi. Production rules apply: name the target and scope and get Dave's go in that session. Steps marked **(stops app)** take the kiosk down, so the go must cover them.

1. Read-only checks: `pwsh tools/pi/find_pi.ps1`, then `pi_run.ps1 -Command 'findmnt -no SOURCE,FSTYPE /; cd ~/project_lily_pad && git status --short && git log --oneline -1; free -m'`.
2. **(stops app)** Unlock: `sudo systemctl stop lilypad; sudo raspi-config nonint do_overlayfs 1; sudo systemctl reboot`. Afterwards root must be `ext4`.
3. **(stops app)** Pull and install, as one `pi_run.ps1 -Script ... -Restart`:
   - `git pull --ff-only`
   - `sudo mount -o remount,rw /boot/firmware`
   - `sudo ./install.sh`, which must end with `==> Done`
   - check `/etc/lilypad/config.toml` against the repo for new keys; `install.sh` keeps the existing file
   - `sudo mount -o remount,ro /boot/firmware`
4. **(stops app)** Optional smoke test: `sudo /opt/lilypad/venv/bin/python -m lilypad --kiosk --smoke 15 --config /etc/lilypad/config.toml`. Run it with the service stopped and `-Restart`.
5. **(stops app)** Relock: `sync; sudo raspi-config nonint do_overlayfs 0; sudo systemctl reboot`. Then check:
   - root is `overlayroot overlay`
   - the service is `active`
   - `tmds_char_rate=148500000` in `/sys/kernel/debug/dri/1/state`
   - a `kill -USR1` frame dump looks right
6. **(stops app)** Bench (`lilypad.bench --display`) and any red-screen display test.

## Parked / blocked

- **Letter V art.** The painted letter V still has the old teal-with-orange-stripes pattern, which doesn't match the new raptor.
  - The fix is one 6-letter sheet job via `work/prod/make_letters.py`, with V's `PAT` entry changed.
  - It's paid generation, so re-confirm the spend cap with Dave first.
- **Party drop markers.** The bundled songs' beat maps have no drop markers, so the drop flash never fires on real songs. Whether to hand-author them is an open decision.
- **Personal music plays first.** `/opt/lilypad/music` holds Dave's 11 OneRepublic instrumentals. With `reward_source = "folder_first"`, parties play those before the bundled anthems. Dave knows; no change has been asked for.
- **The earlier black screen.** The monitor once showed a lit black screen with no "No signal" message, while the Pi was driving a healthy 148.5 MHz signal. Even solid red and green test fills didn't appear. Power-cycling the monitor fixed it. The cause was monitor state; nothing on the Pi needs changing.
- **Stale file on the Pi.** `/etc/lilypad/config.toml.real` (Aug 29) and `config.toml.4b43ca6` are unused backups. Both are harmless.

## Environment

- **Pi access:**
  - `lilypad.local`, which resolves over IPv6 mDNS; Ethernet `end0` is `192.168.0.131/24`, a different subnet from the dev PC's Wi-Fi.
  - user `pi`, key `~/.ssh/lilypad_ed25519`, passwordless sudo
  - Git's `ssh.exe`/`scp.exe` in `C:\Program Files\Git\usr\bin`
- **Monitor:** ASUS VE276 on DRM `HDMI-A-2`, which is the board's HDMI1 port, the micro-HDMI socket farther from USB-C. Its ALSA card is card 1.
- **Dev box:**
  - Python is `C:/Python314/python.exe`.
  - Tests need `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`.
  - There's no `shellcheck` locally; CI runs it.
- **Paid art tools** are in the git-ignored `work/`. See `CLAUDE.md` and the [[visual-upgrade-run-2026-11-25]] memory. The earlier $40 cap was for that run only.
- **Ground-Zero clone:** `C:/Github_Repos/Ground-Zero`, branch `lily-pad/visual-upgrade-2026-11-25`, with its git identity set repo-locally.

## Decisions

These are settled; don't reopen them.
- `main` is the only official branch. Features from the August branch are ported one at a time; it is never merged.
- Party rule: 8 distinct animals; 120 s gap from the last party's end; the first party has no gap.
- The EDID pin is the fix for boot order. Re-run `install.sh` after changing monitors.
- Deploys never upgrade system packages (`--no-upgrade`). Upgrades are a separate, deliberate step.
- Remote diagnosis of the screen uses the SIGUSR1 frame dump before anyone is asked to look at the monitor.
- Idle timings stay at the defaults: attract mode at 60 s, screen sleep at 300 s.
- V is a feathered raptor with an orange kitten rider, with no claws or teeth. The narrator says "A" and "E". Lily's likeness is public by Dave's choice.

## Files touched this session

- `install.sh`: EDID pin, `--no-upgrade`, SC1087 brace fix
- `src/lilypad/frame_dump.py`, `src/lilypad/__main__.py`, `tests/test_frame_dump.py`: SIGUSR1 frame dump
- `deploy/lilypad.service`: `RuntimeDirectory=lilypad`
- `tools/pi/pi_run.ps1`: remote run, restart and fetch helper (new)
- `.github/workflows/ci.yml`: CI (new)
- `CLAUDE.md`, `CHANGELOG.md`, `VERIFY.md`, `docs/HANDOVER.md`: docs
- Ground-Zero `registry/projects/project-lily-pad.yaml`: deploy recorded, next steps
