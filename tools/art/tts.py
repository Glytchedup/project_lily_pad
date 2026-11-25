"""Render paid ElevenLabs takes from a JSON list, with paths relative to the jobs file.

Example job: {"text":"Bee!", "voice":"VOICE_ID", "out":"B.wav", "takes":3}
Multiple takes use B-01.wav, B-02.wav, etc. Each output has a .wav.json/.mp3.json receipt.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

if __package__:
    from . import orc
else:
    import orc

MODEL = "elevenlabs/eleven-v4"


def _jobs(path):
    jobs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise ValueError("Expected a JSON list of speech jobs")
    outputs = {}
    for job in jobs:
        out = (path.parent / job["out"]).resolve()
        fmt = out.suffix.lower().lstrip(".")
        if fmt not in ("wav", "mp3"):
            raise ValueError(f"Expected a .wav or .mp3 output: {out}")
        text, voice = job["text"], job["voice"]
        if not all(isinstance(s, str) and s.strip() for s in (text, voice)):
            raise ValueError("Both text and voice are required")
        takes = job.get("takes", 1)
        if type(takes) is not int or takes < 1:
            raise ValueError("takes must be a positive integer")
        for take in range(1, takes + 1):
            dest = out if takes == 1 else out.with_stem(f"{out.stem}-{take:02}")
            if dest in outputs:
                raise ValueError(f"Duplicate take destination {dest}")
            outputs[dest] = dict(model=MODEL, voice=voice, text=text, format=fmt,
                                 instructions=job.get("instructions"), take=take)
    return outputs


def _render_take(out, spec):
    receipt = Path(str(out) + ".json")
    if out.exists() or receipt.exists():
        if out.exists() and receipt.exists():
            old = json.loads(receipt.read_text(encoding="utf-8"))
            if old.get("request") == spec and old.get("sha256") == hashlib.sha256(out.read_bytes()).hexdigest():
                return
        raise ValueError(f"Existing output differs or is incomplete: {out}. Choose a new output for a new take.")
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as temp:
        tmp = Path(temp) / out.name
        orc.tts(MODEL, spec["text"], spec["voice"], tmp, fmt=spec["format"],
                instructions=spec["instructions"])
        data = tmp.read_bytes()
        if spec["format"] == "wav":
            valid = data.startswith(b"RIFF") and data[8:12] == b"WAVE"
        else:
            valid = data.startswith(b"ID3") or (len(data) > 2 and data[0] == 255 and data[1] & 224 == 224)
        if not valid:
            raise ValueError(f"Expected {spec['format']} speech audio for {out}")
        meta = dict(request=spec, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        orc.atomic_write(receipt, (json.dumps(meta, indent=2) + "\n").encode())
        tmp.replace(out)


def render(path):
    outputs = _jobs(path)
    for out, spec in outputs.items():
        lock_id = hashlib.sha256(os.fsencode(os.path.normcase(str(out)))).hexdigest()
        with orc._lock(Path(gettempdir()) / ("lilypad-tts-" + lock_id)):
            _render_take(out, spec)
    return list(outputs)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("jobs", type=Path)
    for path in render(p.parse_args(argv).jobs):
        print(path)


if __name__ == "__main__":
    main()
