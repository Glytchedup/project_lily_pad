# Lily Pad art tools

Use Python 3.11 or later with Pillow, NumPy and SciPy. The commands below start in the repository root. The generator and batch runner incur OpenRouter charges. The cutout, splice and sheet commands run offline.

## Generate

Set `COLLAGE_SPEND_CAP` in USD. The run plan uses `35`. Supply the key through `OPENROUTER_API_KEY` or set `OPENROUTER_ENV_FILE` to an absolute path containing its assignment. The default ledger is `work/spend.json` under this checkout. Set `LILYPAD_ART_SPEND` to one shared absolute path when running from multiple worktrees.

The ledger records cumulative key usage at project start. Before a paid request, the client reserves its estimate under an interprocess lock. For a hard ceiling on the actual bill, the key must also report a non-resetting OpenRouter credit limit at or below its starting usage plus the project cap. A fresh key with a $35 lifetime credit limit fits a $35 run. The client only reads this setting. It also counts other usage on a shared key and can conservatively count overlap when billing updates arrive during a request.

Image calls reserve $0.15 each. Successful calls settle at the reported cost when available. A lost response leaves its reservation in `pending`. The client sends each paid request once. After an interruption, stop workers using that ledger and reconcile the reservation against provider billing before retrying or editing the ledger.

```powershell
python tools/art/imggen.py work/giraffe.png "very long neck, long thin legs, two rounded ossicones" --animal giraffe --size 1K
python tools/art/imggen.py work/cow.png "white coat with black patches" --animal cow --front --bg "#00C853" --style-file tools/art/styles/B.txt --ref work/giraffe.png
python tools/art/imggen.py work/poses.png "long legs and patch spots" --animal giraffe --sheet --gait walk --ar 3:1
python tools/art/imggen.py work/blink.png "Gently close only the eye." --edit work/giraffe.png
python tools/art/imggen.py work/stride.png --edit work/giraffe.png --edit-pose step --gait walk
```

With `--animal`, the positional text supplies the identifying cues. Without it, give the whole subject line. Direction A, side view, white background, square aspect and 2K are the defaults. `--style-file` replaces direction A. `--sheet` takes `--gait walk|hop|fly`. `--raw` sends the prompt verbatim. In edit mode the master image comes first, followed by the exact prompt and any references. Omit the prompt with `--edit-pose blink|step` to use the pinned edit text.

```powershell
python tools/art/imggen.py work/pond.png "starry night with a crescent moon" --scene world_plate
python tools/art/imggen.py work/reeds.png --scene far_shore --ref work/pond.png
python tools/art/imggen.py work/lip.png --scene near_water --ref work/pond.png
python tools/art/imggen.py work/card.png "a quiet savanna" --scene storybook --animal giraffe --ref work/giraffe.png
```

The scene templates default to 16:9. Use `--ar` to override, `--model` to select a model, and `--size 1K|2K` to select the size. Each PNG has an adjacent receipt, for example `giraffe.png.json`, with the model, provider-reported `usage.cost` (null if absent) and `prompt_sha256` over the UTF-8 text actually sent.

## Batch

Run `python tools/art/imgbatch.py work/jobs.json`. A manifest can contain the following entries.

```json
[
  {"out": "cast/bear.png", "prompt": "round ears and a broad brown muzzle", "args": ["--animal", "bear"]},
  {"out": "cast/owl.png", "prompt": "two large eyes and rounded wings", "args": ["--animal", "owl", "--bg", "#00C853"]}
]
```

Output and input paths in jobs resolve from the manifest directory. Absolute paths work too. Existing PNGs are skipped. Set `PAR` for concurrency (default 2). A failed child gives the batch a nonzero exit code. Run dependent edits in a later batch, after their masters exist.

## Cut, register and inspect

```powershell
python tools/art/cutout_sprite.py work/giraffe.png work/cast/idle.png
python tools/art/cutout_sprite.py work/blink.png work/cuts/blink.png
python tools/art/cutout_sprite.py work/poses.png work/panels --split 3
python tools/art/splice.py work/cast/idle.png work/cuts/blink.png work/cast/blink.png --mode blink --eye 148,42 --eye-r 8
python tools/art/splice.py work/panels/item0.png work/panels/item2.png work/cast/step.png --mode step
python tools/art/sheet.py work/cast work/cast-review.png 3 320 --bg "#0E1A2C" "#808080"
```

Cut against a flat background. Use green for pale animals and white for green animals. The cutout samples the border and uses a Euclidean RGB tolerance of 24 (`--tol`). Border-connected background and enclosed matching regions larger than 0.15% of a panel are cleared. Detached parts larger than 2% of their sprite survive. Output has straight RGBA and two transparent pixels of padding. Sheet panels are named `item0.png`, `item1.png` and so on, left to right.

Register cut PNGs at the same scale. The shift printed by `splice.py` moves the edit onto the master. The upper 55% of the visible master supplies registration features. The residual is the larger of the two directed 95th-percentile edge distances after translation, measured in pixels. A residual above 2% of the visible master height rejects the frame before writing. A correctable rigid shift can exceed that distance.

Blink coordinates are in master pixels. The disc radius is 1.6 times the eye radius. Omit `--eye-r` to measure a dark, isolated iris at the centre. Step replaces the lower 45% and feathers the first 12 pixels of the join. If a stride extends past the trimmed master, the output grows to contain it. The command prints the master's origin in that canvas.

The review sheet shows each PNG on pond navy and mid-grey by default. Pass one `--bg` colour for a single view. The two optional numbers set the sprites per row and the width of each background in pixels. Sprites retain their aspect ratio in both views.
