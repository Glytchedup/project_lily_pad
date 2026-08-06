# Visual Design Review — 10 Recommendations to Reach "WOW"

A review of the current visual layer (`src/lilypad/effects/`) against the audience: a
2-year-old who cares about *things* (animals, bubbles, big reactions), not abstractions.

## Where the visuals stand today

The foundation is solid — pop-in overshoot on letters, squash-and-stretch on Pip,
graceful degradation, a bright saturated palette. But almost everything on screen is a
**flat, solid-color circle**. `ParticleSystem.draw` is `pygame.draw.circle` with linear
fade; fireworks, bursts, confetti, vacuum, and spirals are all parametrizations of the
same dot. The background is a static near-black fill. Letters are the default pygame
font in one flat color. Count-along counts abstract circles/stars/squares. For an adult
this reads "clean"; for a toddler it reads "less interesting than the remote control."

The gap to WOW is not more particles — it's **recognizable things, light, and scene**.

## The 10 recommendations

Ranked roughly by (toddler impact × feasibility). Each stays inside the existing
constraints: pygame primitives / pre-rendered sprites only, no per-pixel Python loops,
no licensed assets, everything behind the existing `Effect` protocol.

### 1. Interactive glossy bubbles that POP
Bubbles are the single most reliable toddler delight, and today they only exist as dim
outline rings in `AttractMode` that vanish on keypress. Promote bubbles to a
first-class effect: translucent glossy spheres (rim circle + off-center white
highlight + faint body fill on a per-size cached `SRCALPHA` sprite) that drift up with
sway. A dedicated key (e.g. `B`) spawns a flotilla; any *new* effect spawning near a
bubble pops it into 6–8 droplet particles with the existing `pop` audio cue. Pip
popping bubbles he collides with makes the frog and bubbles play together for free.
Upgrade `AttractMode` to use the same glossy sprites so idle mode invites touch.

### 2. A farm-animal cast with peekaboo entrances
Pip proves primitive-drawn characters work (`critter.py`). Give him friends: cow, pig,
duck, sheep — each ~60 lines of ellipses/circles in a new `effects/animals.py`.
Animal letters trigger them (`C`→cow, `D`→duck, `P`→pig, `S`→sheep): the animal slides
up from the bottom edge, blinks twice, does its sound (espeak-ng "moo!" fits the
existing zero-copyright audio pipeline), wiggles, and slides away. "What does the cow
say?" is *the* game at age 2 — this converts the keyboard into that game. Registry
change is one factory per letter in `_SPECIAL_FACTORIES`-style overrides of `_letter`
(letter still shows, animal joins it).

### 3. Additive glow rendering for all particles
Everything currently draws as hard-edged flat circles. Pre-render one radial-gradient
sprite per palette color at 3–4 sizes at startup (~40 tiny surfaces), then blit with
`special_flags=pygame.BLEND_ADD` in `ParticleSystem.draw` instead of
`pygame.draw.circle`. Overlapping particles sum toward white — fireworks and bursts
instantly look luminous instead of confetti-flat. Cost is comparable to `draw.circle`
(it's still one blit per particle) and the degradation ladder in
`EffectEngine.note_frame_time` already protects the Pi if it isn't.

### 4. Motion trails via translucent frame clear
`EffectEngine.draw` does an opaque `surface.fill(BACKGROUND)` every frame, so nothing
leaves a trace. Clear instead with a ~35%-alpha background blit (one cached full-screen
surface): every moving particle grows a comet tail, rockets streak, the frog smears
through hops, spirals become galaxies — one of the highest visual-payoff-per-line
changes available anywhere in the codebase. Needs care with the persistent frog and
text (draw those *after* a small opaque-region cleanup or accept the ghosting as
charm), and a config toggle since it changes the whole feel.

### 5. Multi-stage shaped fireworks
`Fireworks` rockets climb bare and burst into one spherical color. Three upgrades:
(a) sparkle trail while climbing (emit 2–3 tiny short-lived particles per frame from
the rocket position); (b) two-stage crackle — burst particles spawn a micro-burst of
3–5 white glitter sparks when they die; (c) shaped bursts — instead of uniform random
angles, sample velocity directions from point templates (heart, star, smiley) so the
explosion *draws a picture in the sky*. Enter becomes a jackpot key. Combined with the
glow sprites (#3) this is the flagship WOW moment.

### 6. Characterful letters: chunky outlines, rainbow fill, googly eyes
`GiantLetter` renders the default `freesansbold` in one flat color. Bundle a rounded,
toddler-friendly open font (e.g. OFL-licensed Baloo/Fredoka — license-compatible,
checked into `assets/`); render each glyph with a thick white or complementary outline
(cheap: blit the glyph 8× offset in outline color, then once on top); occasionally
(1-in-4) fill with a vertical rainbow gradient via a small per-glyph `BLEND_MULT`
pass at render time (once per keypress, not per frame). Then add life: a pair of
googly eyes (white circle + wandering pupil) parented to the glyph during HOLD, and a
gentle ±3° rocking wobble instead of the current static hold. Letters go from
"typography" to "creature".

### 7. Count-along with real countable things
`CountAlong` pops circles/stars/squares — shapes a 2-year-old can't name. Replace with
primitive-sprite objects from the toddler's world: ducks, apples, frogs, flowers,
stars (reuse the animal-drawing helpers from #2 at small scale). Pop each with the
existing overshoot *plus* a rising pitch step (do-re-mi up the scale — the synth
engine already generates chimes), and when the last one lands, fire a mini
`burst` on each object in sequence as a "counting fanfare". This turns the number row
into an actual count-along ("one duck, two ducks…") instead of an abstract exercise.

### 8. A living pond scene instead of a void
The background is a permanent flat `(6, 8, 12)`. The project is called *Lily Pad* —
show the pond: a dark-blue vertical gradient (one pre-rendered full-screen surface,
zero per-frame cost), 2–3 lily pads floating along the bottom edge (static ellipses
with a notch), a handful of twinkling stars, and a crescent moon. Give Pip ripple
rings (reuse `Rings`, small and blue-white) when he lands after a hop. Optionally
drift the gradient's hue over minutes (swap between 3–4 pre-rendered variants:
night, dusk, aurora) so the world feels alive across a play session. Scene grounding
makes every effect read better and costs almost nothing at runtime.

### 9. Key-hold rainbow comets
Toddlers *hold keys down*, and today key repeat just re-fires the same effect.
Detect held keys in the mapper (key-down without key-up past ~400 ms) and spawn a
persistent comet: a bright head that wanders the screen on a smooth noise path,
shedding rainbow trail particles, growing slightly the longer the key is held, and
finishing with a burst when released. Holding a key becomes an act of *drawing light*
— sustained cause-and-effect, which is precisely the developmental hook of the whole
device. (Trails from #4 amplify this massively.)

### 10. Milestone mega-celebrations
Nothing currently escalates — the 500th keypress looks like the first. Track a simple
press counter in the engine and every ~50 presses trigger a 5-second everything-party:
`Fireworks(rockets=5)` + `confetti_rain` + `Balloons` + Pip doing three autonomous
joy-hops + a short rainbow border pulse (reuse `ChaosOverlay` with a timed stop) +
fanfare audio. Also detect "alphabet complete" (all 26 letters pressed since boot)
for a special letter-parade version. Intermittent jackpot rewards are what make the
toy feel bottomless; cost is one counter and one registry factory.

## Suggested build order

| Phase | Items | Why |
|---|---|---|
| 1 | #3 glow, #4 trails, #8 pond scene | Global look transforms — everything else lands on top |
| 2 | #1 bubbles, #5 fireworks, #6 letters | Upgrades to the three most-hit effect paths |
| 3 | #2 animals, #7 counting | New content: the character/naming layer |
| 4 | #9 hold comets, #10 milestones | New interaction mechanics |

## Performance guardrails (Pi 5, 1080p, 60 fps)

- All new art is pre-rendered once (startup or on-spawn), never per frame; per-frame
  work stays blits and `pygame.draw` primitives, matching the existing budget rules
  in `particles.py`'s header comment.
- Glow/trail/gradient surfaces must be `convert()`/`convert_alpha()`-ed after the
  display exists, or blits silently get ~10× slower.
- Every new effect implements `__len__` honestly so `EffectEngine.particle_count`
  and the degradation ladder keep working.
- Animal/peekaboo sprites are single cached surfaces per pose (2–3 poses each), so a
  full menagerie costs less than one confetti burst.
