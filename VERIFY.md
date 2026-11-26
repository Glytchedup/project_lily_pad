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
- [ ] Turn the monitor **off**, wait a minute, turn it back on: the playground
      comes back by itself, with no restart of anything.
- If not: `journalctl -u lilypad -e`. `EGL not initialized` → re-run
  `sudo ./install.sh`; display on the second connector → try
  `Environment=SDL_KMSDRM_DEVICE_INDEX=1` in
  `/etc/systemd/system/lilypad.service`, `daemon-reload`, restart.
- `no display yet — waiting; is the monitor on?` in the log means exactly what
  it says: the connector reads `disconnected`. A sleeping monitor often drops
  hot-plug detect, and then nothing can wake it because there's no signal to
  wake it with. Fix that permanently by appending
  `video=<connector>:1920x1080@60D` (the `D` is the part that forces the port on) to the single line in
  `/boot/firmware/cmdline.txt` and rebooting — the Pi then drives that port
  unconditionally. (The app now also forces a port on by itself when the
  monitor still answers over DDC, so a card without the pin recovers too.) Verified on a Pi 5: connector flips to `connected`, the app
  acquires the screen on boot with zero waiting. **Do this before overlayfs.**

## 2. Every key does something (visuals)

- [ ] Letter keys → giant letter + burst; digits → count-along shapes.
- [ ] Space → confetti; Enter → fireworks; arrows shove the frog.
- [ ] Esc, Windows key, F-keys, PrtSc, media keys → each fires an effect
      and **nothing OS-ish happens** (no console, no VT switch, no blanking).
- [ ] **Every letter A–Z brings an animal.** Walk the whole alphabet once and
      confirm each one appears, is recognisable, and isn't cut off at a screen
      edge. C/D/P/S still peek up from the bottom (cow/duck/pig/sheep); the
      other 22 walk, hop, fly or swim right across, facing the way they go.
- [ ] B → its bear **and** bubbles that Pip can pop.
- [ ] **F7–F12 → a dinosaur** thunders across with a roar (six of them:
      T. rex, velociraptor, stegosaurus, triceratops, brachiosaurus,
      pterodactyl — press repeatedly to see different ones). F1–F6 → balloons.
- [ ] Hopping animals (rabbit, monkey, T. rex, velociraptor) squash on landing
      and kick up dust. If they slide instead of hopping, report it.
- [ ] Run a hand along a whole row of letters: at most ~5 animals on screen at
      once, and **every key still shows its giant letter** even when the
      animal is skipped. Watch for stutter here specifically — this is the
      heaviest new load on the Pi's blit path.
- [ ] **Traced outlines, whole cast.** All 26 side-on animals are now drawn
      from a real anatomical outline. Walk A–Z and F7–F12 and check each one:
      - [ ] Instantly recognisable, and facing the way it is travelling.
      - [ ] The eye is on the head — not on an ear, a horn, or thin air. The
            ones worth a second look: **triceratops** (behind the brow horn,
            not out on the frill), **yak** (head hangs low), **brachiosaurus**
            (head is at the very top of the neck), **owl** (upright, so the
            head is near the top rather than the front).
      - [ ] **Unicorn has a gold horn** and **narwhal has a tusk**. Both are
            drawn on separately; without them they are a white horse and a
            small whale. If either is missing or floating detached, that's a bug.
      - [ ] **Zebra has clean parallel stripes** with its legs clearly visible.
            (They used to fan out and merge into black blobs that swallowed the
            legs — if you see that again, it's a regression.)
      - [ ] The **whale** and **alligator** are *long* — the whale is about 60%
            of the screen width. Intended, but say so if they overwhelm the pond.
      - [ ] Weakest of the set, by my own judgement — say if they don't read:
            **monkey**, **koala**, **pterodactyl**.
      - [ ] With `effects.animal_art = "traced"`, `journalctl -u lilypad | grep "animal art"`
            says `traced (26)`. `drawn` means SDL_image here can't rasterise SVG
            and it fell back — harmless, but you'd be judging the old art, so
            check this first. (The shipped default is `painted`: see §7c.)
      - [ ] No stutter on the *first* press of any letter. They're prebuilt at
            boot (`grep prebuilt` shows 156 sprites, ~2–3 s of the boot); if
            that ever regresses it shows up exactly here and nowhere else.
      - [ ] **The real question: does Pip like them more?** They are
            anatomically right but less toy-like — smaller head, smaller eye.
            `effects.silhouettes = false` + restart puts the whole cast back to
            the older drawn art for an A/B.

- [ ] **Pip the frog.** He is cel-shaded now and sits on his own lily pad.
      - [ ] At rest he is **on the pad**, not floating above it or sunk into
            it, and the pad is fully visible above the bottom edge.
      - [ ] Big eyes, wide smile, pink cheeks; he blinks every few seconds.
      - [ ] Arrow keys still shove him; he squashes on landing and rings
            spread from his feet.
      - [ ] Shove him hard into a corner and hold: **the pad drifts over and
            settles under him**, and he never leaves the screen.
- [ ] Hold any letter ~half a second → a rainbow comet wanders and streaks;
      release → it bursts.
- [ ] ~50 presses → mega-celebration (fireworks + confetti + balloons + frog
      party + fanfare).
- [ ] Trails: effects streak smoothly with no permanent ghost silhouettes and
      no fps drop. Test under SUSTAINED two-handed mashing (worst case:
      mash chaos + a milestone celebration + held keys at once), not single
      presses. The engine sheds trails automatically when deeply degraded;
      `effects.trails = false` in `/etc/lilypad/config.toml` forces the
      cheap opaque clear permanently. (On a Pi installed before the visual
      upgrade the `trails` key won't be in that file — add it under
      `[effects]`; the installer keeps existing configs.)
- [ ] Crossing animals leave a short motion blur behind them (~40 px at
      1080p). That is the trail veil doing its job on a big opaque sprite and
      it is intended — but it is new, because the old animals barely moved.
      If you dislike it, `effects.trails = false` removes it everywhere.
      (Checked on the dev box: the anti-ghost pass frequency makes no visible
      difference to it, so don't go hunting in `GHOSTBUST_EVERY`.)
- [ ] Trails on real KMSDRM: confirm streaks fade smoothly with NO
      flicker/strobe. The trail technique reads the previous frame back
      from the display surface, which is verified on the dev SDL path but
      not on the Pi's KMSDRM driver; if it strobes there, set
      `effects.trails = false` and report.
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
- [ ] Every letter's animal makes a sound, and it matches the animal on screen
      (elephant trumpets, owl hoots, whale sings, T. rex roars). The call sits
      **on top of** the spoken letter name, never instead of it.
- [ ] None of the big animal calls are frightening. They are deliberately low,
      short and softly attacked — a convincing T. rex roar is one a 2-year-old
      cries at. If any of them startles her, say so; it's a bug, not taste.
- [ ] Notes: walk the home row `A`→`L`; the pitch climbs step by step. `Z`,
      `A`, `Q` (same column, three rows) climb too.
- [ ] Lay a whole hand across the keyboard — it is a chord, never a clash.
      (If any combination sounds *wrong*, that is a real bug, not taste:
      the mapping is meant to make it impossible.)
- [ ] Two keys together add a warm triad underneath; a five-key mash brings the
      wide open swell.
- [ ] Notes sit **under** the spoken letter name, not over it. If the voice is
      masked, lower the `note_` gain in `audio/engine.py::_GAINS`.
- [ ] Background tunes: leave the keyboard alone for `display.idle_timeout`
      (60 s) — a tune fades in with the attract animation. Touch any key: it
      fades out within ~1 s and the next idle plays the *next* tune.
- [ ] Tunes loop without an audible click at the seam (listen through two full
      loops, ~40 s).
- [ ] `music.tunes = "off"` + restart = no background music, keys unaffected.
- [ ] `audio.mute = true` + restart = fully silent. (Set it back.)

## 7b. Screen sleep

Set `display.sleep_timeout = 20` in `/etc/lilypad/config.toml` and restart, so
you aren't waiting five minutes; put it back to `300.0` afterwards.

- [ ] Leave the keyboard alone. Both timeouts are measured from the **last
      keypress**, so with `idle_timeout = 60` and `sleep_timeout = 20` sleep
      wins and the attract animation never gets a chance — set
      `idle_timeout = 5` too if you want to watch the handover. At
      `sleep_timeout` the screen goes **fully black**, the keyboard LEDs go
      **out**, and the music **stops**. (At the shipped 300 s / 60 s, attract
      runs for four minutes and then sleep takes over.)
- [ ] Press any letter: screen, lights and effects all come back within a
      fraction of a second, and that keypress still does its own thing.
- [ ] Press only **a Shift** (which normally produces no effect): the screen
      still wakes. This matters — the escape combo starts with Shift, and a
      hatch that looks dead in front of a black screen is worse than none.
- [ ] While asleep, `top` over SSH shows the app near-idle (it drops to 10 fps).
- [ ] `sleep_timeout = 0` + restart → never sleeps. (Set it back.)
- Note: the HDMI **output stays on** — the picture is black, the signal isn't
  cut. There is no software way to power the output down on a Pi 5
  (`vcgencmd display_power` → `Command not registered`; the DRM `dpms` node is
  read-only), and cutting it would risk exactly the hot-plug-detect deadlock
  §1 fixes. If you want the monitor's backlight off, use the monitor's own
  power-save setting.

## 7c. Painted pond, parties and narrator

Defaults ship painted (`effects.animal_art = "painted"`, `scene.world = "painted"`,
`audio.voice = "narrator"`, `music.reward_rule = "animals"`). Nothing here has run
on a Pi yet. Where a number is given it is a starting guess, not a measurement:
record the real one and fix this file.

**Startup and memory (Pi 5 with 1 GB)**
- [ ] `journalctl -u lilypad | grep "animal art"` reads
      `animal art: painted (N), traced (M), drawn (K)` with `K = 0` and no
      `Ignoring painted ...` warnings. Any warning means a kit fell back (the app
      still runs, but you are judging the older art).
- [ ] Time from `Started lilypad` to the first frame is under about 15 s
      (journal timestamps). Note the prebuild time; the painted cast prebuilds
      every pose at display size before the first keypress.
- [ ] After a minute of play, `ps -o rss= -p $(systemctl show lilypad -p MainPID --value)`
      leaves comfortable headroom (`free -m` available memory, no swap in use) and
      `journalctl -k | grep -i oom` is empty. Record the RSS.
- [ ] The first press of every letter (A-Z, F7-F12) shows no hitch. Painted
      letters, eyes and storybook cards are the new first-press costs.

**A party triggers on the 8th animal**
- [ ] Press 8 *different* animal letters one after another (e.g. A G O W C B D F):
      the 8th starts fireworks the same moment, then a song plays while Pip dances.
      The top-right bar fills as animals are met and disappears during the party.
- [ ] Press one letter 30 times: no party, the bar does not move past 1/8.
- [ ] The song ends and the party ends with it. Meet 8 new animals straight away:
      nothing starts until two minutes after the song *ended* (`music.reward_min_gap
      = 120`); then the party starts on its own without another keypress.
- [ ] The song is audible near full volume, key cues are ducked under it, and it
      sounds in tune with the keys. With no files in `music/` you hear a bundled
      anthem; drop an MP3 in `music/`, restart, and that plays first.

**Fireworks keep 60 fps**
- [ ] During a party (sky bursts every 0.8 s, a bigger burst each bar) hold a
      few letters and watch for stutter. Stop the service, then
      `sudo /opt/lilypad/venv/bin/python -m lilypad.bench --scenario party --display`
      (also `--scenario heavy` and `--scenario parade`): the report's p95 frame time
      is under 16.7 ms. The dev box measures about 7 ms for `party`.
- [ ] `effects.fx_style = "glow"` and restart if it does not hold, and report.

**Letters do not cover animals**
- [ ] Press `G`, then a letter or two while the giraffe is walking: the giant
      letters sit in the sky and margins, clear of the animal, Pip, Lily and the
      album strip. A crowded screen makes a letter a little smaller instead of
      overlapping. The letter just pressed is always visible.
- [ ] During a party the fireworks do not burst on top of Pip, Lily or an animal.

**Narrator letters A and E**
- [ ] Press `A` and `E` (several times, and mixed with other letters): the narrator
      says the *names* of the letters, "A" as in "ay" and "E" as in "ee", cleanly and
      at normal volume. Walk the alphabet once and listen for any other letter
      that sounds wrong.
- [ ] After a quiet moment "A is for Alligator!" follows the letter; mashing many
      keys speaks only letter names, never over each other.
- [ ] `audio.voice = "espeak"` and restart gives the old robot voice.

**The rest of the new show (quick look)**
- [ ] Three quick presses of one letter open that letter's storybook page; any key
      still draws on top of it.
- [ ] New animals fly a portrait into the strip along the top.
- [ ] Lily appears, moves to a new spot after about 75 s, and sleeps when the screen does.
- [ ] Hold both Shifts + Backspace: a "Today's play" card shows for a few seconds
      and the app still exits at the 5 s mark with no extra wait.
- [ ] Keyboard lights follow walking animals and the party beat.
- [ ] `--config config.legacy.toml` (or `effects.animal_art = "traced"`,
      `scene.world = "drawn"`, `audio.voice = "espeak"`) restores the classic look.

## 8. Escape hatch + service behavior

- [ ] Hold both Shifts + Backspace: progress bar bottom-right; releasing
      early cancels; full 5 s exits to a **blank dead console** (no shell).
- [ ] `systemctl status lilypad` shows `inactive (dead)` — it did **not**
      restart (clean exit stays stopped by design).
- [ ] `sudo systemctl start lilypad` brings it back.
- [ ] Unplug/replug the keyboard mid-play: within a few seconds the app
      restarts (udev replug rule) and keys work again.
- [ ] Kill test: `sudo kill -9 $(systemctl show lilypad -p MainPID --value)`
      → service restarts itself within ~2 s (crash path), and the journal shows
      it re-grabbing both keyboard nodes and re-claiming the Razer device.
      (Don't use `pkill -f "python -m lilypad"`: `-f` matches whole command
      lines, so the shell running that very command matches its own pattern
      and kills your SSH session along with the app.)

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
