# VERIFY.md — On-device verification checklist

Development happened with **no Pi attached**: everything hardware-facing sits
behind interfaces that were exercised with mocks and unit tests. This
checklist is the final verification on real hardware. Run it top-to-bottom
once after `install.sh` + reboot; ~15 minutes. Keep an SSH session open from
your PC (`ssh pi@lilypad.local`) — the Pi's console is intentionally dead.

## 1. Boot-to-app

- [ ] Power on → within ~30 s the screen shows the near-black playground
      (no login prompt, no desktop, no cursor, minimal boot text).
- [ ] `systemctl status lilypad` over SSH shows `active (running)`.
- If not: `journalctl -u lilypad -e`. `EGL not initialized` → re-run
  `sudo ./install.sh`; display on the second connector → try
  `Environment=SDL_KMSDRM_DEVICE_INDEX=1` in
  `/etc/systemd/system/lilypad.service`, `daemon-reload`, restart.

## 2. Every key does something (visuals)

- [ ] Letter keys → giant letter + burst; digits → count-along shapes.
- [ ] Space → confetti; Enter → fireworks; arrows shove the frog.
- [ ] Esc, Windows key, F-keys, PrtSc, media keys → each fires an effect
      and **nothing OS-ish happens** (no console, no VT switch, no blanking).
- [ ] Two keys at once → chord supernova; palm-mash 5+ keys → rainbow chaos
      mode, calming down when released.
- Note: the left-edge M1–M5 macro keys may do nothing at all — the lighting
  driver owns their USB interface (RESEARCH.md §1), so they can't emit
  events. That's expected and harmless; every standard key must work.

## 3. Exclusive capture (the security property)

- [ ] Hold **Ctrl+Alt+F2** (and F1–F6): screen must not switch to a console.
- [ ] **Ctrl+Alt+Del**: nothing (no reboot).
- [ ] Over SSH run `cat /dev/tty1` for a few seconds while mashing: no
      characters appear.
- [ ] `journalctl -u lilypad | grep grabbed` lists **at least two** event
      devices (main keys + media/macro interface of the BlackWidow).

## 4. Keyboard RGB

- [ ] `journalctl -u lilypad | grep "lighting backend"` says `razer_hid`
      (not `mock` — mock means both hardware backends failed; see README
      troubleshooting).
- [ ] Idle: slow breathing color wash. Each press: key flashes + ripple
      spreads outward from that key. Mash: strobing rainbow.
- [ ] Ripple origin roughly matches the pressed key (the 6×22 position map
      in `src/lilypad/lighting/keymap.py` was written from documentation —
      if a region is offset, adjust there; positions only affect ripples).

## 5. Power draw stress

- [ ] `lighting.brightness = 1.0` in `/etc/lilypad/config.toml`, restart,
      then hold 6+ keys through several chaos strobes for ~2 minutes.
- [ ] No keyboard disconnect/reconnect, no `under-voltage` in
      `journalctl -k | grep -i volt`, no flicker.
- If it fails: verify the 27 W PSU is negotiating (`vcgencmd pmic_read_adc`
  / check `usb_max_current_enable`), or add the BOM contingency powered hub.

## 6. Performance

- [ ] Effects feel fluid during heavy mashing (target 60 fps with graceful
      degradation — brief particle thinning is fine, stutter is not).
- [ ] Optional measurement: stop the service and run the self-test
      `sudo /opt/lilypad/venv/bin/python -m lilypad --kiosk --smoke 20`
      — it exits 0 and the journal shows no frame-budget errors.

## 7. Audio

- [ ] Letters are spoken, numbers counted, effects have cues, volume sane.
- [ ] `audio.mute = true` + restart = fully silent. (Set it back.)

## 8. Escape hatch + service behavior

- [ ] Hold both Shifts + Backspace: progress bar bottom-right; releasing
      early cancels; full 5 s exits to a **blank dead console** (no shell).
- [ ] `systemctl status lilypad` shows `inactive (dead)` — it did **not**
      restart (clean exit stays stopped by design).
- [ ] `sudo systemctl start lilypad` brings it back.
- [ ] Unplug/replug the keyboard mid-play: within a few seconds the app
      restarts (udev replug rule) and keys work again.
- [ ] Kill test: `sudo pkill -9 -f "python -m lilypad"` → service restarts
      itself within ~2 s (crash path).

## 9. Power-pull resilience

- [ ] Yank the power cord mid-play, wait 5 s, power back: boots to the
      playground with no fsck drama.
- [ ] Then enable the overlay (`sudo raspi-config nonint do_overlayfs 0`,
      reboot) and yank power twice more: still boots clean every time.
- [ ] `mount | grep overlay` confirms the root overlay is active.

## 10. Sign-off

- [ ] Toddler test: hand over the keyboard, observe delight.

Anything that failed → README troubleshooting, or open an issue on the repo
with the relevant `journalctl -u lilypad` output.
