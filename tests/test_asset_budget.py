"""Repository-wide disk, attribution and reference checks for the new media."""

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from lilypad.effects.animal_specs import STENCILS

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "lilypad" / "assets"
MEDIA = {".webp", ".png", ".jpg", ".jpeg", ".svg", ".wav", ".ogg", ".mp3", ".json"}
LEGACY = {Path("silhouettes") / spec.file for spec in STENCILS.values()}
LEGACY.add(Path("silhouettes/CREDITS.md"))


def _files(root):
    return [p for p in root.rglob("*") if p.is_file() and p.relative_to(root) not in LEGACY]


def test_new_asset_bytes():
    sizes = {p.relative_to(ASSETS): p.stat().st_size for p in _files(ASSETS)}
    assert sum(sizes.values()) <= 40_000_000, sum(sizes.values())
    # Bundled anthems stream through mixer.music (never decoded into RAM), so they get a larger per-file cap.
    assert not {p: size for p, size in sizes.items()
                if size > (2_500_000 if p.parts[0] == "music" and p.suffix == ".ogg" else 1_500_000)}


def _uncredited(root):
    files = _files(root)
    credited = set()
    for credits in (p for p in files if p.name == "CREDITS.md"):
        for line in credits.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("|"):
                cells = line.strip().strip("|").split("|")
                if len(cells) >= 2 and all(cell.strip() for cell in cells):
                    credited.add(credits.parent / cells[0].strip().strip("`"))
    return sorted(p.relative_to(root) for p in files
                  if p.name not in ("manifest.toml", "CREDITS.md") and p not in credited)


def test_every_new_asset_has_a_credits_row():
    assert not _uncredited(ASSETS)


def _references(value, field=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _references(child, "file" if field == "frames" else key)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child, field)
    elif isinstance(value, str) and (field == "file" or Path(value).suffix.lower() in MEDIA):
        yield value


def _missing_references(root):
    missing = []
    for manifest in (p for p in _files(root) if p.name == "manifest.toml"):
        with manifest.open("rb") as stream:
            for filename in _references(tomllib.load(stream)):
                path = (manifest.parent / filename).resolve()
                if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file():
                    missing.append((manifest.relative_to(root), filename))
    return missing


def test_every_manifest_reference_exists():
    assert not _missing_references(ASSETS)


def test_asset_checks_use_relative_paths_and_exact_credits_rows(tmp_path):
    painted = tmp_path / "painted"
    painted.mkdir()
    for name in ("giraffe", "whale"):
        (painted / name).mkdir()
        (painted / name / "idle.png").touch()
    (painted / "CREDITS.md").write_text(
        "| `giraffe/idle.png` | A |\nwhale/idle.png appears only in prose.\n", encoding="utf-8"
    )
    (painted / "manifest.toml").write_text(
        '[animals.giraffe.frames]\nidle="giraffe/idle.png"\nblink="giraffe/blink.webp"\n'
        '[pip.frames]\ncheer="pip/cheer.png"\n[pad]\nfile="pip/pad.webp"\n'
        '[minis.duck]\nfile="minis/duck.png"\n', encoding="utf-8",
    )
    assert _uncredited(tmp_path) == [Path("painted/whale/idle.png")]
    assert {name for _, name in _missing_references(tmp_path)} == {
        "giraffe/blink.webp", "pip/cheer.png", "pip/pad.webp", "minis/duck.png",
    }


def test_root_music_is_untracked():
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is unavailable")
    tracked = subprocess.check_output([git, "ls-files", "-z", "--", "music/"], cwd=ROOT)
    assert not tracked, tracked
