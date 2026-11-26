# Handover: deploy the visual upgrade to the Lily Pad Pi

_Written 2026-11-25 at the end of the visual-upgrade session._

## Goal

Dave asked for a big visual upgrade of the toddler app and to load it onto the Raspberry Pi once he had tested it locally. Done so far:
- painted AI art for the whole cast, Pip, FX, letters and googly eyes
- Lily as a pond character
- storybook cards, a sticker album, a beat-synced party show and the Grand Parade
- a narrator voice and bundled music

He has tested `main` on the dev PC and said "Looks perfect". What remains: **find the Pi on the local network and update it to `main`**, then run the on-device checks.

## State

- `main` is pushed to `origin` (GitHub `Glytchedup/project_lily_pad`).
  - The suite passes: 1772 passed, 5 skipped (`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q`).
  - `python -m lilypad --dev --smoke 6` exits 0.
- Last code commits on `main`:
  - `4d46eaa`: the party fires on the 8th distinct animal, the gap is 120 s counted from the previous party's end, and there are more fireworks.
  - `ee1a8d8`: V is a feathered raptor with a crowned kitten rider in sunglasses.
- Docs (CHANGELOG `[Unreleased]`, CLAUDE.md, PLAN.md decisions, README, VERIFY) were closed out in the `docs:` commit that follows those.
- **The card on the Pi runs `4b43ca6`, which is 88 commits behind `main`.** This comes from the Ground-Zero registry and was not re-verified on the device: the Pi was unreachable at hand-off.
- **The Pi was not reachable on 2026-11-25.** `tools/pi/find_pi.ps1` returned NOT FOUND:
  - mDNS `lilypad.local` did not resolve.
  - No Raspberry Pi MAC address appeared after a ping sweep of `192.168.68.0/22`.
  - The only other SSH host (`.120`, a different device) rejected the Pi key.
  - So the Pi was most likely off or unplugged from Ethernet.
- Ground-Zero registry PR: https://github.com/Glytchedup/Ground-Zero/pull/20 (next steps updated). It needs merging.

## Next step

1. **Find the Pi:** `pwsh -NoProfile -File C:/Github_Repos/project_lily_pad/tools/pi/find_pi.ps1`.
   - It is read-only. It prints `FOUND <ip>` with the model, the root filesystem type (`overlay` means locked), the deployed commit and the service state.
   - If it reports NOT FOUND, ask Dave to power the Pi on and plug in its Ethernet cable (its Wi-Fi config names an old network), then run it again.
2. **Get Dave's explicit go for the deploy.** Changing the Pi is a production change, so name the target (`pi@<ip>`, hostname `lilypad`) and the scope:
   - unlock the overlay
   - pull `main`
   - re-run `install.sh`
   - merge the config
   - relock
3. **Deploy.** Run each step over `ssh -i ~/.ssh/lilypad_ed25519 pi@<ip>`, using Git's `ssh.exe`.
   1. **Check before changing anything:**
      - `findmnt -no SOURCE,FSTYPE /`
      - `cd ~/project_lily_pad && git status --short && git log --oneline -1`
      - `free -m`
      - `df -h /media/root-ro`
   2. **Unlock:** `sudo raspi-config nonint do_overlayfs 1 && sudo reboot`. After the reboot, `findmnt /` must no longer say `overlay`.
   3. **Pull:** `cd ~/project_lily_pad && git fetch && git log --oneline -1 origin/main && git pull --ff-only`. The tip must match `origin/main` on GitHub.
   4. **Boot partition:** it stays read-only even after the unlock. Run `sudo mount -o remount,rw /boot/firmware` so `install.sh` can add the `D` suffix to `video=` in `cmdline.txt`.
   5. **Install:** `sudo ./install.sh`. It is idempotent: apt packages, `pip install .[pi]` into `/opt/lilypad/venv`, regenerated sounds, units and udev. Check that it ends without errors.
   6. **Config merge:** `install.sh` keeps an existing `/etc/lilypad/config.toml`.
      - Diff it against the repo's `config.toml`.
      - Keep Dave's tuned values: volume, brightness, escape combo and timeouts.
      - Make sure it does not pin old settings that switch off the upgrade:
        - `music.tunes` must be `"reward"`
        - `music.reward_rule` `"animals"`
        - `effects.animal_art`, `pip_art` and `fx_style` `"painted"`
        - `effects.silhouettes` not `false`
        - `music.bundled_tracks` and `party_show` `true`
      - Missing keys fall back to these defaults, so deleting a stale line is enough.
   7. **Confirm the display pin:** `grep -o 'video=[^ ]*' /boot/firmware/cmdline.txt` must show `video=HDMI-A-2:1920x1080@60D`. Then `sudo mount -o remount,ro /boot/firmware`.
   8. **Smoke test:** `sudo systemctl stop lilypad && sudo /opt/lilypad/venv/bin/python -m lilypad --kiosk --smoke 15`. It must exit 0. Then `sudo systemctl start lilypad`.
   9. **Relock:** `sudo raspi-config nonint do_overlayfs 0 && sudo reboot`. Verify that `findmnt -no SOURCE,FSTYPE /` prints `overlayroot overlay` and `systemctl is-active lilypad` prints `active`.
4. **On-device checks:** work through the new VERIFY.md items with Dave at the keyboard:
   - startup time and RAM on the 1 GB Pi 5 (painted sprites prebuild at startup)
   - 60 fps during a party
   - a party on the 8th distinct animal
   - music audible on HDMI audio (card 1)
   - letters not covering animals
   - the narrator saying "A" and "E" correctly
   - the RGB keyboard lighting (only ever tested with the mock)
   
   Log the results in VERIFY.md and CHANGELOG.
5. Update the Ground-Zero registry (`registry/projects/project-lily-pad.yaml`): the card's commit, and drop the "Deploy main" next step. Then merge PR #20 or add to it.

## Parked / blocked

- **Pi offline at hand-off:** see above.
- **Letter V art:** the painted letter V still wears the old teal-with-orange-stripes pattern, which no longer matches the new raptor. Dave was offered a repaint (about $0.15, one 6-letter sheet job via `work/prod/make_letters.py` with V's `PAT` entry changed) and has not answered.
- **Party drop markers:** the bundled songs' beat maps (`src/lilypad/assets/music/*.beats.json`) have no drop markers, so the party show's drop flash and firework never fire on the real songs. Whether to hand-author drops is an open decision.
- **Fast key mashing:** `MAX_ANIMALS` (5 on screen) drops extra spawns when the child mashes keys, and a dropped animal does not count toward the party. This was kept deliberately: only animals the child actually sees count.
- **Old unmerged branches:** `art/cast-v1`, `cx/J10`, `cx/J11`, `cx/J12` and `cx/J14` predate this session. They were left alone and need a decision before deleting.

## Environment

- **Pi access:**
  - user `pi`, key `~/.ssh/lilypad_ed25519`, passwordless sudo
  - hostname `lilypad`, Pi 5 with 1 GB RAM, Ethernet only (`end0`)
  - client: Git's `C:\Program Files\Git\usr\bin\ssh.exe`
  - The card is locked read-only (overlayroot). The unlock and relock steps are above; `do_bootro` does not exist.
- The monitor is on **HDMI-A-2 / ALSA card 1**. The `@60D` force suffix in `cmdline.txt` is load-bearing.
- **Dev box:** `C:/Python314/python.exe`. Tests need `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`.
- **Paid generation tools** live in the git-ignored `work/`:
  - `work/art-tools/imgbatch.py`, with `OPENROUTER_ENV_FILE=C:/Users/davek/claude-cloud.env` and `COLLAGE_SPEND_CAP=35`
  - pose sheets: `work/prod/make_sheets.py`
  - letters: `make_letters.py`
  - cutter: `work/prod/sticker_cut.py`
  - cast builder: `tools/art/stage_build.py`
  - Run paid batches one at a time, because the ledger `work/spend.json` is not concurrency-safe.
- **Spend:** OpenRouter about $17.18 of the run's $40 cap. That cap was granted for that session only, so re-confirm it before any paid generation.
- **Ground-Zero:** clone at `C:/Github_Repos/Ground-Zero`, branch `lily-pad/visual-upgrade-2026-11-25`. Its git identity is set repo-locally.

## Decisions

These are settled; don't reopen them.
- The party rule is **8 distinct animals since the last party**, with at least **120 s between parties counted from the previous party's end**. The first party has no gap. `config.legacy.toml` keeps the old `play` rule.
- Letters are placed clear of animals, Pip and Lily (the sky band and side margins) through `ctx.occupied()`.
- Painted googly eyes on letters and on Pip's look-around eyes are wanted; the larger letter eyes were approved.
- V is a feathered turquoise raptor with an original orange kitten rider in a gold crown and sunglasses, and has **no claws or teeth**: the cast rule stands.
- The narrator says the letter names "A" and "E" (not "Ay" or "Ee").
- Lily's likeness is in the public repo by Dave's choice.
- Painted AI art is committed with a per-file `CREDITS.md` row. The asset budget is 1.5 MB per file and 2.5 MB per music `.ogg`.
- The Pi deploy always needs Dave's explicit go in the session that does it.

## Files touched this session (since the last handover)

- `src/lilypad/assets/{painted,letters,eyes,storybook,fx,music,album}/`: painted art, music, manifests and CREDITS
- `src/lilypad/effects/{letters,eyes,numbers,engine,critter,album,...}.py`: painted route, placement, eyes, party fireworks
- `src/lilypad/audio/{engine,voice}.py`: reward rule and gap, narrator letter names
- `src/lilypad/__main__.py`: startup art setters
- `src/lilypad/config.py`, `config.toml`: new defaults
- `tests/`: about 80 new tests across the art, placement, eye, reward, asset-budget, storybook and album suites
- `tools/pi/find_pi.ps1`: Pi discovery, new
- `CHANGELOG.md`, `CLAUDE.md`, `PLAN.md`, `README.md`, `VERIFY.md`, `docs/fragments/`, `docs/HANDOVER.md`: docs

## Retro candidates

- The first narrator speech-recognition check left out letter names, so "Ay" being heard as "I" shipped and Dave caught it. Voice checks must cover every line, including the single letters.
- The image model drew claws on V despite "no claws" in the prompt. Describe the wanted shape positively ("stubby toes ending in soft round tips") and look at every sheet before cutting it.
- `git commit` failed in a fresh Ground-Zero clone because there is no global git identity on this machine; it was set repo-locally.
- A subagent reported that Bash hung on simple commands in this environment and switched to PowerShell.
