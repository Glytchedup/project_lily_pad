# Changelog

All notable changes to Project Lily Pad (Toddler Keyboard Playground) are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
pre-1.0, so everything lands under Unreleased until first on-device verification.

## [Unreleased]

### Added — the bring-up faults became code, and the card can now move (2026-08-13)
The four faults from the 2026-08-12 bring-up were written up but only as prose,
which helps exactly once. They are now checks that run.

- **`--doctor`** (`src/lilypad/doctor.py`, `python -m lilypad --doctor`). One
  command, eleven checks, each printing the remedy next to the finding: board
  model, card swap, HDMI EDID per connector, the ALSA card the live port maps
  to, the `video=` pin, the Wi-Fi regulatory domain, `authorized_keys`, the root
  overlay, under-voltage, the service, and the generated sounds. Exit 1 on any
  failure. Touches neither the display nor the keyboard, so it is safe to run
  while the playground is up, and `install.sh` finishes by running it.
  Every filesystem root and command runner is injected, which is why 59 tests
  cover it on a dev box with no Pi attached.
- **`lilypad-audio.service`** (`src/lilypad/hdmi_audio.py`) re-derives
  `/etc/asound.conf` at **every boot** from whichever connector returned EDID,
  rather than install.sh baking an index in once. This fixes the second half of
  fault 2 without a manual step, follows the cable if it moves ports, and
  composes with `overlayroot` for free — the write lands in tmpfs and is
  regenerated next boot. It refuses to touch a hand-written `asound.conf`, and
  writes atomically via a temp file so a power pull can't leave half a config.
- **The SD card is expected to move between Pis** — tested on one board, then
  swapped into the Pi 5. Two settings are properties of the board rather than
  the card: the HDMI ALSA index (now self-correcting, above) and the `video=`
  pin, which can name a connector the new board hasn't got. That failure is a
  black screen with nothing in any log, so `install.sh` stamps the board it ran
  on and `--doctor` compares. A 32-bit-only board (Pi 1/2/Zero W) is reported
  as such rather than looking like a bad flash.
- `install.sh` gained phase 7: disable `NetworkManager-wait-online` (the app is
  fully offline and the wait can stall boot for a minute), set the HDMI audio
  card, write the hardware stamp, and self-check.

### Changed
- **README and VERIFY no longer say "use HDMI0" unconditionally.** That advice
  is what sent the bring-up down fault 2 — on that board HDMI0 is the port with
  dead DDC lines. Both now say to check EDID first and name the connector the
  monitor is actually on. Troubleshooting gained rows for all four faults, and
  VERIFY gained §10 (diagnostics) and §11 (card swap, test Pi → Pi 5).

### Verified on real hardware — first full on-device bring-up (2026-08-12)
Installed and run end-to-end on the actual Pi 5 (1 GB, Rev 1.1) with the
BlackWidow attached. Everything below is measured, not inferred. Four faults
cost most of the session; each is written up with the one command that
identifies it, so the next occurrence takes minutes instead of hours.

**What passed.** `install.sh` clean in all 6 phases on Raspberry Pi OS Lite 64-bit
Trixie (Debian 13, kernel 6.18.34, Python 3.13.5, pygame-ce 2.5.8 / SDL 2.32.10).
`--kiosk --smoke 15` exits 0. `razer_hid` claims the keyboard directly — the
OpenRazer fallback was never needed. Exclusive `EVIOCGRAB` takes all four Razer
event nodes. 156 traced-outline sprites prebuilt at boot; `animal art` reports
`traced outlines`, not the `drawn` fallback. Power is clean under load:
`throttled=0x0`, zero under-voltage events on the official 27 W PSU. The §8 kill
test (`kill -9` the MainPID) recovers in ~3 s with `NRestarts` 0→1, re-grabbing
both keyboard nodes and re-claiming the RGB device. Cold boot to playground is
**7.1 s** (1.5 s kernel + 5.6 s userspace). Resident set ~217 MB of 990 MB.

**SDL picks the right DRM card unaided.** The Pi 5 exposes `card0` = `v3d`
(render-only, no CRTCs) and `card1` = `vc4-drm` (all connectors). SDL 2.32.10
enumerates past v3d correctly, so `SDL_KMSDRM_DEVICE_INDEX=1` — offered in
README troubleshooting and VERIFY.md §1 — was **not** required. Leave it unset
unless the log actually says `kmsdrm not available`.

**Fault 1 — Pi 5 bootloader offers net install ("Configure this Raspberry Pi").**
Means the bootloader found no bootable OS. Not an OS-level problem; the app is
irrelevant here. Cause was a corrupt FAT32 `bootfs` partition — Windows reported
`HealthStatus=Warning` and refused to mount it. *Diagnose:* put the card in a PC
and look at the boot partition; 0-byte or unmountable is conclusive. *Fix:*
reflash. *With no PC to hand:* the bootloader's own network install (hold SHIFT
at that screen) reflashes the card using only the Pi, a USB keyboard and **wired
Ethernet** — the bootloader cannot use Wi-Fi. Cheap oversized microSDs are a
counterfeit risk; `BOM.md` specifies 32 GB A2/U3 for a reason.

**Fault 2 — no audio, and resolution stuck at 1024x768.** Both symptoms, one
cause: the HDMI link read **0 bytes of EDID**. Without a CEA extension block the
sink advertises no audio capability, `vc4-hdmi` refuses to open a PCM, and ALSA
returns **error 524 (ENOTSUPP)**; `dmesg` repeats `HDMI: Unknown ELD version 0`.
The connector still reports `connected` because hot-plug detect is a separate
pin from the DDC lines, so video works at the generic fallback modes and nothing
looks obviously broken. *Diagnose in one command:*
`wc -c < /sys/class/drm/card1-HDMI-A-1/edid` — zero means EDID, not ALSA.
*On this board the near HDMI port (HDMI-A-1, closest to USB-C) has dead DDC
lines*; the same cable in the far port returned a full 256 bytes and identified
the display. This contradicts `README.md`'s advice to use HDMI0, which remains
correct in general — try the other port before suspecting the cable or the TV.
Consequences once on the far port: it is ALSA **card 1**, not the default card 0,
so `/etc/asound.conf` needs `defaults.pcm.card 1` / `defaults.ctl.card 1`, and
the mode must be pinned with `video=HDMI-A-2:1920x1080@60D` in `cmdline.txt`
(VERIFY.md §1's fix, retargeted). Restarting the service alone will **not** lift
the app off 1024x768 — SDL inherits whatever mode the CRTC negotiated at boot, so
only a reboot re-negotiates. Confirmed the forced mode does not break audio.
Note `/proc/asound/card*/eld` keeps a **stale** ELD after unplugging, so a
populated `monitor_name` there is not proof the port is live.

**Fault 3 — Wi-Fi fails with `ssid-not-found` and an empty scan list.** Looks
exactly like a wrong password and is not one: NetworkManager logs
`has security, and secrets exist. No new secrets needed.` before failing, and
`nmcli device wifi list` returns nothing at all — not even neighbours' networks.
Cause is a regulatory-domain split: `iw reg get` showed `global country US` but
**`phy#0 country 00: DFS-UNSET`**, and regdom `00` makes 5 GHz unusable. A Wi-Fi
6E router living on 5 GHz + 6 GHz then has no band the Pi 5 radio can reach (it
does 2.4/5 GHz only, never 6 GHz). *Fix is a reboot, not a command* — the
self-managed `brcmfmac` driver reads its country at load time, so
`iw phy phy0 set country US` on a running system achieves nothing. Imager already
writes `cfg80211.ieee80211_regdom=US` into `cmdline.txt`; a cold boot applies it
and the radio associates immediately. *Diagnose:* check `iw reg get` for a
global/phy0 mismatch before touching credentials.

**Fault 4 — `authorized_keys` silently ends up 0 bytes.** Pushing a public key
over a pipe from PowerShell created the file with correct 600/700 permissions and
no content, so key auth failed while every permission check looked right. Verify
with `ssh-keygen -lf ~/.ssh/authorized_keys` and compare the fingerprint rather
than trusting `ls`. Note `/home/pi` at `700` is fine for sshd's `StrictModes`.

### Changed (deployment notes from the same bring-up — 2026-08-12)
- **The read-only overlay on Trixie is `overlayroot`, not `boot=overlay`.**
  `raspi-config nonint do_overlayfs 0` installs the Debian `overlayroot` package,
  regenerates both initramfs images and prepends `overlayroot=tmpfs` to
  `cmdline.txt`; `/` then mounts as `overlay` with `lowerdir=/media/root-ro`.
  Detect it with `mount | grep -i overlay` — grepping for `boot=overlay` gives a
  **false negative**. `/boot/firmware` stays `rw`, so it remains reversible.
  README's update dance (`do_overlayfs 1` → reboot → change → re-enable → reboot)
  is unchanged and still required for config edits and app updates.
- **`NetworkManager-wait-online` is worth disabling on an appliance.** The Imager
  image enables it and cloud-init pulls in `network-online.target`, which can
  stall boot for up to a minute when the network is absent. `lilypad.service` has
  no network dependency of any kind and the app is fully offline — all cues are
  generated to disk at install time. Disabling the wait contributed to the 7.1 s
  boot, and the playground was verified running on Wi-Fi alone with the Ethernet
  cable unplugged.

### Changed (the whole side-on cast is traced, and Pip got a makeover — 2026-08-10)
- **All 26 side-on creatures now use traced outlines**, up from three. Every
  letter animal and every dinosaur is built from a public-domain silhouette
  instead of stacked ellipses. The four front-on farm animals (cow, duck, pig,
  sheep) are deliberately unchanged — they peek up from the bottom rather than
  crossing, so there is no side view to trace.
- **A horn and a tusk are drawn procedurally**, because the outline cannot
  supply them: there is no unicorn to photograph, and every public-domain
  narwhal is either tuskless or drawn from above. Without them the two are a
  white horse and a small whale, and the cast already has both.
- Each outline was chosen from up to eight candidates rather than taking the
  first hit — a top-down pterosaur reads as a paper kite, and the default
  monkey reads as a blob. Notes on the awkward picks are in
  `assets/silhouettes/CREDITS.md`.
- Startup pre-warm now builds 156 sprites (~1 s at 1080p on a dev box).

### Changed (Pip the frog — 2026-08-10)
- **Pip is cel-shaded and sits on his own lily pad.** Flat colour with
  hard-edged shadow and highlight bands and a single heavy keyline, which is
  what reads from across a room where a soft gradient turns to mush. Bigger
  eyes, a full-width smile, rosy cheeks, and a proper closed-lid blink.
- His sprite is now **cached by (radius, pose)** instead of being redrawn from
  a dozen primitives every frame. Squash stays continuous and is applied as a
  cheap scale at draw time.
- **His resting height moved up** (`Frog.floor_y`). He used to settle with his
  feet on the very bottom row of pixels, which left nowhere to draw what he was
  sitting on. The pad drifts along under him — it floats, so following him
  reads as natural, and it means he is *always* on his pad even after a toddler
  has shoved him into a corner.
- The engine's splash-ripple check now asks the frog where its floor is instead
  of assuming the bottom of the screen.

### Fixed
- **Zebra stripes merged into solid black.** Each stripe got its own random
  tilt, so they fanned out toward the bottom of the sprite, overlapped and
  swallowed the legs entirely. Stripes are now parallel under a single shear.
- **The frog's mouth never rendered.** `pygame.draw.arc` is unreliable on a
  wide, flat rect with a thick stroke and silently drew nothing; it is an
  explicit sampled curve now.
- **The unicorn's horn and the narwhal's tusk were cropped to stubs.** Sprites
  are cut tight to the traced outline — that is what puts an animal's feet on
  the ground line — so both accessories, which by definition stick out past the
  outline, lost roughly a third of their length including the tip. The sprite
  surface now reserves the room they need, derived from the same constants the
  drawing uses so the two cannot drift apart again. The tusk also got slightly
  thicker with a pair of spiral ridges, which is what makes it read as a tusk
  rather than a hairline at the size it actually appears.
- **Pip's lily pad hung a few pixels off the bottom of the screen.** His
  resting height was a guessed multiple of his radius; it is now measured from
  the pad sprite itself, including the bob, so the front notch stays on screen
  at any resolution.

### Added (traced animal outlines, a three-creature trial — 2026-08-10)
- **Giraffe, triceratops and whale are now drawn from a real anatomical
  outline** instead of being assembled from ellipses. The shape comes from a
  public-domain [PhyloPic](https://www.phylopic.org/) silhouette; everything
  else — body colour, belly shading, coat markings, the oversized cartoon eye,
  the dark keyline, and every bit of movement — is still generated by
  `effects/animal_stencil.py`. The outline is used as a *stencil*, not a
  picture: filling it with `BLEND_RGB_MAX` swaps the colour and leaves the
  anti-aliased edge intact at any size.
- `effects.silhouettes` (default `true`) turns the trial off, putting those
  three back to the drawn version. That is the point of it — it is how you
  compare them.
- All three sprites are **prebuilt at startup** (~150 ms), so the first press
  of G, W or a triceratops key never drops frames.
- The three outlines ship in `src/lilypad/assets/silhouettes/` with a
  `CREDITS.md` naming the artist and licence of each. Every one is CC0.

### Fixed
- **`pytest` inside a git worktree was testing the wrong checkout.**
  `pip install -e` records one absolute path, so `import lilypad` resolved to
  the main checkout and the suite silently validated code that was not being
  edited. `tests/conftest.py` now puts this checkout's `src/` first.
- Package data was not declared, so a non-editable install would have shipped
  without the silhouettes and quietly fallen back to the drawn animals.

### Added (the whole alphabet is a zoo — 2026-08-10)
- **An animal for every letter, A–Z.** Twenty-six creatures where there were
  four: alligator, bear, cow, duck, elephant, fox, giraffe, horse, iguana,
  jellyfish, koala, lion, monkey, narwhal, owl, pig, quail, rabbit, sheep,
  T. rex, unicorn, velociraptor, whale, x-ray fish, yak, zebra. The four
  originals (cow, duck, pig, sheep) keep their hand-drawn front-on art
  untouched.
- **Dinosaurs.** Six of them: T. rex (T) and velociraptor (V) have their own
  letters; stegosaurus, triceratops, brachiosaurus and pterodactyl arrive on
  **F7–F12**, which previously all did the same balloon effect as F1–F6.
  Stegosaurus and triceratops also joined the countable objects, so counting
  to five can now mean five little stegosauruses.
- **Animals move.** The new cast is drawn side-on and *crosses the screen*
  rather than popping up and fading: quadrupeds walk with a two-beat bob,
  rabbit/monkey/T. rex/velociraptor hop in parabolic arcs, owl/quail/
  pterodactyl/jellyfish fly, whale/narwhal/x-ray fish swim. Direction is
  random and sprites are mirrored to face the way they are going. Landings
  squash and kick up dust. The front-on originals now take two little jumps
  during their peekaboo, with the same squash and dust.
- **Eleven new animal calls** (`roar`, `growl`, `screech`, `trumpet`, `neigh`,
  `hoot`, `chirp`, `squeak`, `whalesong`, `bloop`, `stomp`), all procedurally
  generated like the rest. Deliberately un-scary: the "big" calls are low,
  short and soft-attacked, because a convincing T. rex roar is one a
  two-year-old cries at. `CUE_VERSION` → 4, so devices regenerate on start.
- **Screen sleep.** After `display.sleep_timeout` (default **300 s**) with no
  keypresses the screen goes fully black, the keyboard LEDs go out, background
  music stops and the render loop drops to 10 fps. Any key — including one
  that produces no effect, like a lone Shift — brings it straight back.
  `sleep_timeout = 0` disables it.

### Changed
- `effects/animals.py` split three ways: `animal_specs.py` (the cast list, one
  data row per creature), `animal_art.py` (drawing and sprite caches), and
  `animals.py` (who appears for which key, what they sound like, how they
  move). Twenty-six bespoke drawing functions would have been a thousand lines
  nobody could keep consistent.
- The audio engine now reads `ANIMAL_VOICES` from the visual cast instead of
  keeping its own copy, so a creature can never end up with art and no sound.
- At most **5** animals are on screen at once (`MAX_ANIMALS`). With every
  letter carrying a creature, a two-handed run along the keyboard otherwise
  stacked a dozen full-height alpha blits per frame. The surplus animal is
  dropped; the letter and its burst still fire.

### Fixed
- Peekaboo animals stopped blinking when the jumps were added — the jump
  windows completely covered both blink windows, so the blink pose could never
  be reached. Blinks now sit between the jumps.
- Flying animals could sail off the top of the screen: the band a flyer starts
  in now leaves room for half a sprite *plus* the full wave amplitude.
- Sprites were being sliced by their own surface bounds — alligator and iguana
  tails, rabbit ears, the unicorn's horn, the triceratops' beak and the whale's
  spout all ran past the edge. Tails are clamped, head placement scales with
  head size, and the head's vertical clamp leaves headroom for whatever sits on
  top of it. `tests/test_animals.py` now asserts no sprite touches its own
  left, right or top edge.

### Not done, and why
- **Powering the HDMI output down during sleep.** Both routes are dead on a
  Pi 5, verified on the device: `vcgencmd display_power` returns `Command not
  registered`, and `/sys/class/drm/card1-HDMI-A-1/dpms` is read-only. Blanking
  the output would also risk the monitor dropping hot-plug detect — the exact
  deadlock that forced `video=HDMI-A-1:1920x1080@60D` into cmdline.txt. Sleep
  is therefore a black picture on a live output; use the monitor's own power
  saving if you want the backlight off too.

### Fixed (first on-device run — Raspberry Pi 5, 2026-08-10)
- **A monitor that was off at boot put the app in a permanent restart storm.**
  Both HDMI connectors read `disconnected`, the kernel logged `Cannot find any
  crtc or sizes`, SDL raised `kmsdrm not available`, and the app exited — so
  systemd restarted it every ~2.5 s, indefinitely. `--kiosk` now *waits* for a
  display (`_wait_for_display`) instead of exiting: the moment the monitor
  comes back the app starts, with no manual intervention. A monitor being
  switched off is an ordinary event in a child's room, not an error.
- **The unit could latch into `failed` and never recover.** `lilypad.service`
  never set `StartLimitIntervalSec`, so systemd's default 5-starts-per-10 s
  applied; the observed storm sat just under it by luck of timing. Any
  faster-failing crash would have tripped it and left a black screen that
  stayed black even after the cause cleared. Now `StartLimitIntervalSec=0`.
  `Restart=on-failure` is unchanged, so the parent escape hatch's clean exit
  still stays stopped.
- `VERIFY.md` kill test used `pkill -9 -f "python -m lilypad"`, which matches
  whole command lines — the shell running that very command matched its own
  pattern and killed the SSH session along with the app. Now targets MainPID.

### Added (musical audio — keys are notes, chords, and background tunes)
- `audio/music.py`: the theory core. Every key maps to a note of the **C major
  pentatonic** scale, derived from `lighting/keymap.py`'s LED matrix so the
  musical and lighting layouts cannot drift apart — lower physical rows are
  lower notes, left to right climbs the scale, everything folded into MIDI
  48–88 (C3–E6). That scale contains no minor 2nd, tritone or major 7th in any
  inversion, so **any** combination of keys pressed together is consonant by
  construction; `tests/test_music.py::test_no_two_keys_can_clash` asserts it
  directly. Also: diatonic triad tables and `chord_for_keys()`.
- `audio/tunes.py`: four original instrumental loops (`sunrise`, `counting`,
  `boats`, `party`) in an anthemic pop-piano style — four-chord loops, an
  eighth-note piano ostinato, soft stomp-clap backbeat and a singable melody.
  Rendered at build time into seamless ~20 s WAVs (the reverb tail is wrapped
  back over the loop start, so repeats have no click). All in C major, the same
  key as the keys, so playing over a tune lands in tune.
- Background music: `AudioEngine.set_idle()`, driven from the frame loop by
  `engine.attract is not None`. Tunes fade in with the attract animation and
  fade straight out on the next keypress, round-robining through the four.
  Played via `pygame.mixer.music` so cues never steal the music's channel.
- `[music]` config section: `key_notes` (default `true`), `tunes`
  (`idle` | `always` | `off`, default `idle`), `tune_volume` (default `0.45`,
  independent of `audio.volume`). An invalid `tunes` value raises at load.

### Changed (audio)
- `audio/synth.py` grew a real instrument model: a `Voice` dataclass with
  **per-harmonic exponential decay** (upper partials die faster — the ear's main
  cue for "struck/plucked" rather than "beep"), a gentle attack ramp, a detuned
  chorus layer, pitch-dependent brightness rolloff so the top of the keyboard
  sparkles instead of piercing, and a short lowpassed reverb tail. Voices:
  `BELL` (letters), `MARIMBA` (counting), `PAD` (chords), `PIANO`/`PLUCK`/`BASS`
  (tunes).
- Keypresses now sound their note: letters play the note **and** the spoken
  letter name (previously name-*or*-chime), with a per-family gain table
  keeping the note under the voice. Space/enter/arrows/specials/sparkles layer
  a note under their character cue. Numbers keep the counting ladder, now a
  marimba.
- Two-key chords play the diatonic triad their lower note roots (was a single
  static three-note stab); mash storms get a wide open add9 swell.
  `celebration` is recomposed as a I–V–vi–IV cadence.
- Synth plumbing rewritten for the ~100× more samples the tunes need: a `Mixer`
  class (slice + `zip` listcomp) replaces the O(n·layers) indexed loop, WAV
  writing goes through `array('h').tobytes()`, and oscillators use a fixed-point
  wavetable. A full cue build (56 files, 6 MB, including four tunes) takes ~6 s.
- `build_cues(dest, tunes=False)` skips the slow tune render for tests.
- Character cues (whoosh, boom, drum, boing, animal calls) stay caricatures
  rather than instruments, but were retuned to sit *under* the notes and the
  spoken letter name — see the gentler-audio entry below.

### Changed (gentler audio — cues were hard on the ears)
Carried over from the `worktree-softer-sounds` branch and re-pointed at the new
synth. The parts of that branch which retuned the old beep-style musical cues
(`_tone` defaults, chime, count_note, celebration) are superseded: those cues no
longer exist, and the `Voice` renderer shapes brightness by pitch instead.
- Character cues softened: slower attacks (no clicky onsets), tamer harmonic
  stacks (duck/pig buzz reduced), quieter noise layers (whoosh/boom/drum),
  lower sparkle/pop pitch ranges, per-cue gains trimmed. `_mix` headroom
  dropped from 0.9 to 0.72 — at full scale the animal calls buried both the
  letter name and the key note.
- New `_soften()` finishing pass — gentle one-pole ~3 kHz lowpass plus
  downward-only peak normalisation — applied to the character cues **only**.
  The musical cues are deliberately excluded: `Voice` already rolls off high
  partials by pitch and adds a reverb tail, and a lowpass on top of that just
  makes the bells sound underwater.
- `CUE_VERSION` stamp (`cues.version`, now at 3) written by `build_cues()`;
  the audio engine regenerates any sounds dir with a missing or stale stamp.
  Without this a device with WAVs already on disk would keep playing the old
  cues forever and no retune would ever reach it. A `tunes=False` build is
  deliberately left unstamped — that set really is incomplete.
- Cue regeneration failure (read-only dir — `/opt` under the Pi's overlayfs)
  now degrades to the existing cues with a warning instead of crashing.
- `_tone()` deleted: dead code once every caller moved to `render_note`.

### Added (visual WOW upgrade — implements all 10 VISUAL_REVIEW.md recommendations)
- Pond scene (`effects/scenery.py`): pre-rendered night/dusk/aurora gradient
  skies with baked moon, stars, and drifting lily pads; slow crossfade between
  variants every 5 minutes; twinkling star overlay.
- Additive glow rendering (`effects/glow.py`): cached radial-gradient sprites
  blitted with `BLEND_ADD` replace flat circles in `ParticleSystem.draw` —
  overlapping particles now sum toward white.
- Motion trails: the engine clears each frame with a translucent scene veil
  (plus a subtract/max-snap pass that defeats pygame's integer-blend ghosting)
  so lights streak and fade; `effects.trails` config toggle.
- Glossy interactive bubbles (`effects/bubbles.py`): letter B blows a flotilla
  of specular-highlight bubbles that Pip pops on contact (droplet spray);
  attract mode now uses the same glossy sprites.
- Farm-animal peekaboo cast (`effects/animals.py`): C/D/P/S slide a
  primitive-drawn cow/duck/pig/sheep up from the bottom edge — blink, wiggle,
  and a procedural moo/quack/oink/baa — then slide away.
- Fireworks upgrade: glitter trails on climbing rockets, white crackle
  micro-pops partway through each burst, and 50% shaped explosions that draw a
  heart, star, or smiley in the sky.
- Characterful letters: thick contrasting outline, 1-in-4 rainbow-gradient
  fill, gentle bob/sway wobble, and googly eyes during the hold phase.
- Count-along with real things: digits now count ducks/apples/frogs/flowers/
  stars (one kind per press), with a left-to-right mini-burst fanfare and an
  ascending pentatonic count note per press.
- Key-hold rainbow comets (`effects/comet.py`): any key held ~0.4 s becomes a
  wandering hue-cycling comet (max 4) that grows while held and bursts on
  release; `KeyMapper.poll_holds` drives hold_start/hold_end actions.
- Milestone mega-celebrations: every 50th press (configurable via
  `effects.milestone_every`) fires fireworks + confetti + balloons + a timed
  rainbow border pulse + frog joy-hops + a celebration fanfare; completing all
  26 letters adds a heart-shaped burst.
- Frog splash-down ripples (water rings at his feet on real impacts).
- Audio: new procedural cues (moo/quack/oink/baa, count_0..9 pentatonic
  ladder, celebration fanfare) and `AudioEngine.on_celebration()`.
- Tests: 171 (was 52) — new coverage for animals, bubbles, comet, glow,
  scenery, synth cues, hold detection, engine integration, and regression
  tests from both adversarial review rounds.

### Fixed (visual WOW upgrade)
- A resting frog re-triggered its floor bounce every frame (sub-pixel gravity
  re-entry), which kept him permanently squashed and would have rained
  ripples; bounces now require a real impact.

### Fixed (adversarial review round 3 — Fable deep semantic + product/edge
### reviewers, briefed to find what the previous six missed)
- Rate-triggered rainbow-chaos latched ON permanently when 3-4 keys were
  merely resting (a toy on the keyboard): both mash exits required fewer
  than 3 held keys, a floor designed for the 5-keys-held entry path the
  rate trigger never took. Mash now tracks WHY it engaged — the held-count
  hysteresis only applies when the held path justified it, so rate-mash
  exits on rate decay regardless of resting keys.
- Sustained fast play violated the "every key does something visible"
  invariant with no chaos involved: ordinary spawns self-saturated the
  particle budget and 28-39% of presses were silently dropped by the spawn
  gate (measured at 6 space presses/s, default config). A gated press now
  always spawns a small guaranteed-affordable burst instead of nothing.
- Idle attract mode ("nobody's here" bubbles) activated while a child was
  actively holding a key with a live comet — a held key emits exactly one
  action, so the idle clock ran; live comets now count as activity.
- Engine scene and chaos-wash surfaces are convert()ed to the display
  format when possible (avoids potential per-frame pixel-format conversion
  on the Pi's software blit path).
- SHIP-BLOCKER: the count-along fade restored the shared cached object
  sprite with `set_alpha(None)`, which in pygame disables per-pixel alpha
  entirely — after the very first number press faded, every later count
  rendered opaque black squares instead of objects for the rest of the
  session. Restore is now `set_alpha(255)`.
- Comet was resolution-blind (fixed 10-26 px head, fixed px/s speed): a
  marquee effect at 720p, a crawling speck on a 4K TV. Head, speed, trail
  and edge-clamp now scale with screen height.
- Anti-ghost pass strengthened (SUB 6→9/step) to clear the grey "ghost
  ladder" large peekaboo sprites left when rising through the trail veil.
- Known cosmetic (documented, not fixed): the aurora pond variant reads
  as a flat band rather than a curtain; balloons spawn just below the
  bottom edge so the F-key reaction takes ~0.3 s to become obvious at
  800x480.

### Fixed (adversarial review round 2 — three fresh independent reviewers:
### whole-branch, fix-regression hunt, and rendered-frame visual QA)
- Glow sprites pushed every core ~92% toward white, erasing the particle
  palette (71% of burst pixels measured colorless) and flattening the fade
  curve; the core now keeps ~half its saturation, so single particles read
  as their color and true white only appears where glows overlap.
- Googly eyes were placed glyph-blind and punched pupil-holes through
  letter strokes (white ball invisible on the white outline); they now
  perch on top of the glyph with a dark rim — every letter reads as a
  creature and legibility is untouched.
- The count-along digit lived a fixed 1.9 s and was gone before the 8th,
  9th and 10th objects even appeared; it now holds until the count (and
  fanfare) finish. Fanfare bursts are bigger and fire above each object.
- Alphabet completion during the celebration cooldown silently destroyed
  both the party and the 26-letter progress (97% of completions eaten at
  mash speeds); the big party now bypasses cooldown and budget, and
  progress is only consumed when it actually fires. A budget-blocked
  ordinary milestone no longer arms the cooldown either.
- Round-1's "honest" overlay budget weight starved mash mode of its own
  bursts (72% fewer at default config; zero below max_particles=250) —
  the engine-owned mash overlay no longer taxes the spawn gates
  (CelebrationPulse, which lives in the effects list, still does).
- Trails now pause while mash chaos is active: the veil re-blended the
  full-screen hue wash every frame into a solid saturated screen.
- Space bar's drawn Rings stacked into a full-screen bullseye moiré under
  trails; replaced with expanding rings made of fading glow particles.
- Pond variants each baked their own moon and starfield, so crossfades
  showed two moons; all variants now share one sky layout. Lily pads sat
  almost entirely below the bottom edge; raised into view.
- Comet: inward steering strengthened and the clamp inset by the head
  size (heads/bursts pinned half-clipped into edges); stuck-hold auto-
  release raised 30 s → 120 s so a toddler leaning on a key keeps their
  comet; wash surface re-created on size mismatch.
- Audio: count-cue fallback removed (it double-fired "pop" at 2x amplitude
  on pre-upgrade sound dirs — the voice line already falls back);
  ANIMAL_LETTERS now imported from effects.animals instead of duplicated.
- Rainbow letter gradient now spans the full glyph (violet end previously
  fell past the ink); mini duck's stick-bill replaced with a rounded one;
  registry docstring corrected; celebration pulse draws at the same depth
  as the mash overlay it subclasses; dead `rising_balloons` removed.

### Fixed (adversarial review round 1 — three independent reviewers)
- `ChaosOverlay.draw` allocated and filled a full-screen surface every frame
  (~12 MB/frame of churn, ~1.9 ms/overlay); the wash surface is now
  persistent. Worst-case frame time dropped ~32% (17.4 → 11.8 ms mean on the
  dev box), p95 ~37%.
- Milestone celebrations now respect the particle-budget gate and a 10 s
  cooldown — under a mash storm the mega-party recurred every ~1.7 s,
  stacked up to 3 full-screen overlays, and made 3.5% of presses visually
  dead by saturating the budget.
- The degradation ladder can now shed the trail veil (off below scale 0.4,
  back above 0.6): its cost is fixed per frame, so particle scaling alone
  measurably could not recover the budget. The anti-ghost SUB/MAX pass also
  runs every 4th frame instead of every frame (~2 ms → ~0.5 ms).
- Comet trail shedding is now dt-based (was per-tick: doubled at 120 fps,
  starved at 30), and a comet whose key-release never arrives (USB unplug
  mid-hold) auto-releases after 30 s instead of living forever.
- Rate-triggered mash mode no longer strobes on/off ~19x/s under fast
  tapping (it now stays on while the press rate holds, and exits via the
  per-frame poll once tapping slows — previously it could also wedge ON
  forever, since exit only ran on a release event).
- Chaos overlay now counts toward the particle budget (its wash measured
  ~880 particle-equivalents but reported 30, blinding the spawn gates).
- Count-along pop-in scale curve was discontinuous (26% single-frame size
  snap at the overshoot boundary); digit glyph now uses the clamped count;
  fade no longer rescales sprites to an identical size every frame.
- Giant letters: a white fill could draw a white outline (~1% of letters
  became a flat glyph); the fade phase copied a ~1 MB surface per frame
  (now set_alpha in place).
- New audio cues (animal sounds, count notes) now fall back to pre-upgrade
  cues on a sounds dir generated before this change.
- `poll_holds` iterates a snapshot of held keys (latent
  dictionary-changed-during-iteration hazard for future callers).

### Added
- `VISUAL_REVIEW.md`: visual-design review of the effects layer with 10 ranked
  recommendations (glossy bubbles, farm-animal cast, additive glow, motion
  trails, shaped fireworks, characterful letters, countable objects, pond
  scene, key-hold comets, milestone celebrations) plus build order and Pi
  performance guardrails.
- Repo bootstrap: `.gitignore`, `.gitattributes` (LF for Pi-executed files),
  `CLAUDE.md` project context, this changelog.
- `RESEARCH.md`: verified findings + citations for RGB control (direct-HID
  primary / OpenRazer fallback), EVIOCGRAB capture, KMSDRM rendering, boot
  hardening, USB power budget, prior art. Target OS bumped to Raspberry Pi
  OS Lite 64-bit **Trixie** (current stable; spec assumed Bookworm).
- `PLAN.md` (architecture, module map, decision log D1–D10) and `BOM.md`
  (Pi 5 + mandatory 27 W PSU; Pi 4 budget alternative; hub as contingency).
- Core app:
  - TOML config (`lilypad.config`) with defaults, clamping, validation.
  - Input: `KeyEvent`/backend interface; SDL dev backend; evdev Pi backend
    grabbing **all** keyboard nodes exclusively; synthetic smoke backend.
  - Mapper: total keycode→action mapping (letters, numbers, space, arrows,
    enter, named specials, sparkle fallback), 2-key chords, mash-storm
    detection (5+ held or 8 presses/s).
  - Effects: particle primitives (burst, confetti, balloons, rings,
    fireworks, vacuum, spirals), giant pop-in letters, count-along numbers,
    idle attract mode, rainbow-chaos overlay, Pip the frog (arrow-key
    critter), frame-budget graceful degradation.
  - Lighting: host-side 6×22 frame math (breathing, ripples, key flash,
    mash strobe); backends: direct-USB `razer_hid` (OpenRazer wire
    protocol via pyusb), `openrazer` daemon fallback, `mock`; auto-fallback
    factory; BlackWidow Chroma key-position map.
  - Audio: pure-stdlib procedural cues (chimes, pop, whoosh, boom, drum,
    boing, chord fanfare), espeak-ng voice generation, mute flag,
    silence-on-failure mixer engine.
  - Parent escape hatch (both Shifts + Backspace, 5 s hold) with on-screen
    progress cue; clean exit stays stopped under systemd.
  - `--smoke N` self-test mode exercising the full pipeline with synthetic
    toddler input.
- Deployment: idempotent `install.sh` (apt deps, `/opt/lilypad` venv, sound
  generation, config, quiet-boot cmdline, getty@tty1 off), systemd unit
  (boot-to-app, restart-on-failure), udev keyboard-replug restart rule,
  SysRq-off sysctl.
- Tests: 47 pytest cases (mapper, chords, mash, escape timing, config,
  registry totality, lighting math, keymap bounds, synth WAVs, razer report
  layout/CRC) — all green on Windows/Python 3.14.
- Docs: `README.md` (flash-to-playing walkthrough, config table,
  troubleshooting), `VERIFY.md` (on-device checklist), MIT `LICENSE`.

### Changed (post-build quality audit)
- Hardware lighting backends now run behind a threaded latest-wins wrapper:
  razer_hid's ~7 USB control transfers per frame no longer block the render
  loop (they cost ~300 ms/s at 30 lighting fps — guaranteed stutter).
- `install.sh` no longer requests `libasound2` explicitly (Debian 13 t64
  package rename hazard); `alsa-utils` pulls the correct ALSA lib.
- Tests: 52 (added threaded-wrapper coverage: async delivery, frame
  collapsing, non-blocking apply, exception survival, clean shutdown).

### Fixed
- Lighting engine dropped its first frame when ticked at t=0 (`_last_frame`
  now starts at −∞).
- Frame-time measurement included `clock.tick`'s fps-cap sleep, so the
  graceful-degradation *recovery* path could never trigger; now measures
  work time only.
- `install.sh` was committed without its executable bit (authored on
  Windows) — `sudo ./install.sh` would have failed on the Pi.
- README license link pointed at pyproject.toml instead of LICENSE.
