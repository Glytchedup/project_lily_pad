"""Run an array of {out, prompt, args} jobs, relative to the jobs JSON file."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

IMGGEN = Path(__file__).resolve().with_name("imggen.py")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", type=Path)
    args = parser.parse_args(argv)
    manifest = args.jobs.resolve()
    jobs = json.loads(manifest.read_text(encoding="utf-8"))
    workers = int(os.environ.get("PAR", "2"))
    if workers < 1:
        parser.error("PAR must be positive")
    env = os.environ.copy()
    for name in ("LILYPAD_ART_SPEND", "OPENROUTER_ENV_FILE"):
        if env.get(name):
            env[name] = str(Path(env[name]).resolve())
    commands = {}
    for job in jobs:
        out = (manifest.parent / job["out"]).resolve()
        if out in commands:
            parser.error(f"duplicate output: {out}")
        prompt = [job["prompt"]] if job.get("prompt") is not None else []
        commands[out] = [sys.executable, str(IMGGEN), str(out), *prompt, *job.get("args", [])]

    def run(out):
        if out.is_file():
            print(f"Skipping existing {out}", flush=True)
            return 0
        return subprocess.run(commands[out], cwd=manifest.parent, env=env).returncode

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(run, commands))
    return int(any(results))


if __name__ == "__main__":
    sys.exit(main())
