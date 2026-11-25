# Lily Pad art bible: "Moonlit Gouache" (direction A)

Chosen by Dave on 2026-11-25 from in-app trial boards (A: Moonlit Gouache, B: Felt & Paper, C: Paper Lantern).
This file is binding for every painted asset: the cast, Pip, the pond worlds, storybook cards and the effects kit.

## Pinned style string

The exact text sent with every cast prompt lives in `tools/art/styles/A.txt`. In short: a premium hand-painted
picture book in opaque gouache, with chunky rounded toddler forms, big glossy eyes with two catchlights, a closed-mouth
smile, a dark plum keyline (#2A1E2C), a cool moonlight rim (#BFD8FF) along the top and a warm bounce (#F2C46B)
underneath. It must not look 3D, vector, cel-shaded, photoreal or plastic.

Every cast image also gets the two approved trial images (giraffe, bear) as **style references**. This is the
promo-film ref-chaining technique, used here to hold a style across different characters rather than one
character's identity.

## Scene palette

| Token | Hex | Use |
|---|---|---|
| night-sky | #0A0F1E | sky plate base |
| deep-water | #0E1A2C | water band, QA backdrop |
| moon | #E8E8D6 | moon, brightest world pixel |
| rim | #BFD8FF | character rim light |
| bounce | #F2C46B | character underside |
| keyline | #2A1E2C | character outline |
| lily | #2C7840 | pads |
| lotus | #DB7093 | flowers |

World layers keep their max channel at or below 70, except the moon, glints and fireflies. Storybook cards may go up
to 90 outside the animal and the moon.

## Figure rules

- Side-on animals are drawn in strict side view, facing **right**. The runtime mirrors them, so there is no
  directional key light and no cast shadow. The farm four (cow, duck, pig, sheep) and Pip are drawn front view.
- The feet sit on an implied flat baseline. There is no ground, grass or water under the figure.
- Each animal has one visible eye, drawn large with two catchlights.
- **Never** draw teeth, claws, blood or angry brows. T. rex, velociraptor and alligator get a friendly closed smile.
- The body's mean L* is at least 45, or a rim light covers at least 30% of the top contour. Dark animals rely on
  the rim.
- The keyline runs continuously around the outer silhouette, at 2.5–3.5% of figure height.
- Proportion: the bounding-box aspect stays within ±25% of the traced PhyloPic outline. Proportion is identity
  (PLAN D21).
- Banned: text or letters in the art, frames, glitter, lens flare, photoreal fur, 3D sheen, extra limbs, and eyes on
  both sides of a side-view head.

## Production method

Each animal is one 2K pose sheet. The panels, left to right:

- idle, blink, step, for walk, hop and fly gaits;
- idle, blink, for swim, float and the front-view farm four.

The background is flat white, or flat #00C853 green for pale subjects. The pipeline then runs
`cutout_sprite.py --split`, then `pack.py`, which registers the panels, shares one canvas and anchor, and scales to
1080p-native height. It finishes with `qa_sprite.py` and `judge.py` (see `tools/art/README.md`). Assets ship as WebP
at 1080p size, and nothing is generated at 4K.

## Verification

The automated thresholds are listed in the run plan's §2.7 and enforced by `qa_sprite.py`. A person also reads the
per-animal strips and the in-app frames at 1920×1080 and 1280×720 before any batch is committed. A batch is accepted
only when one round shows zero defects.
