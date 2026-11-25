import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
from threading import Event
import tomllib

import pytest

pytest.importorskip("PIL")
from PIL import Image

from tools.art import imgbatch, imggen, orc


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail("Unexpected network access")
    monkeypatch.setattr(orc.urllib.request, "urlopen", deny)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_ENV_FILE", raising=False)


def png(color):
    stream = BytesIO()
    Image.new("RGBA", (5, 7), color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def generator(tmp_path, monkeypatch):
    frames = {}
    for name, color in (("ref", "red"), ("master", "green")):
        path = tmp_path / (name + ".png")
        path.write_bytes(png(color))
        frames[name] = path
    style = tmp_path / "style.txt"
    style.write_text("Custom gouache.\n", encoding="utf-8")
    received = []
    blob = png("blue")

    def fake_chat(model, messages, **kwargs):
        received.append((model, messages[0]["content"], kwargs))
        return {"choices": [{"message": {"images": [{"image_url": {
            "url": "data:image/png;base64," + base64.b64encode(blob).decode()}}]}}],
                "usage": {"cost": 0.123}}
    monkeypatch.setattr(orc, "chat", fake_chat)
    return frames, style, blob, received


@pytest.mark.parametrize("mode", ["side", "front", "sheet", "edit", "raw", "blink_edit", "step_edit",
                                   "world_plate", "far_shore", "near_water", "storybook"])
def test_exact_prompt_payload_and_receipt(tmp_path, generator, mode):
    frames, style, blob, received = generator
    table = tomllib.loads((imggen.ART / "prompts.toml").read_text(encoding="utf-8"))
    out = tmp_path / "nested" / "asset.png"
    text = "soft ears"
    animal, bg = "rabbit", "#00C853"
    args = ["--style-file", str(style), "--bg", bg, "--animal", animal,
            "--ref", str(frames["ref"]), "--size", "1K", "--ar", "2:3", "--model", "test-model"]
    reference = table["style_ref"].format(animal=animal)
    if mode in ("side", "front", "sheet"):
        parts = ["Custom gouache.", table["subject"].format(animal=animal, cues=text), reference]
        if mode == "sheet":
            args += ["--sheet", "--gait", "hop"]
            parts.append(table["sheet"].format(animal=animal, step=table["steps"]["hop"]))
        if mode == "front":
            args += ["--front"]
        parts.append(table["front" if mode == "front" else "side"].format(bg=bg))
        expected = " ".join(parts)
    elif mode in ("raw", "edit"):
        text = "  Keep {bg} and the\noriginal punctuation!  "
        args += ["--raw"] if mode == "raw" else ["--edit", str(frames["master"])]
        expected = text
    elif mode in ("blink_edit", "step_edit"):
        text = None
        args += ["--edit", str(frames["master"]), "--gait", "fly", "--edit-pose", mode.split("_")[0]]
        expected = table[mode].format(step=table["steps"]["fly"])
    else:
        args += ["--scene", mode]
        if mode in ("far_shore", "near_water"):
            text = None
        template = table[mode].format(mood=text, habitat=text, animal=animal, bg=bg)
        expected = " ".join(["Custom gouache.", *([reference] if mode == "storybook" else []), template])
    imggen.main([str(out), *([text] if text is not None else []), *args])
    (model, content, options), = received
    edited = mode in ("edit", "blink_edit", "step_edit")
    if edited:
        assert base64.b64decode(content[0]["image_url"]["url"].split(",")[1]) == frames["master"].read_bytes()
    assert content[int(edited)] == {"type": "text", "text": expected}
    assert base64.b64decode(content[-1]["image_url"]["url"].split(",")[1]) == frames["ref"].read_bytes()
    assert model == "test-model" and options["image_config"] == {"image_size": "1K", "aspect_ratio": "2:3"}
    assert out.read_bytes() == blob
    receipt = json.loads(Path(str(out) + ".json").read_text())
    assert receipt["usage"]["cost"] == 0.123
    assert receipt["prompt_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_default_white_side_and_4k_rejection(tmp_path, generator):
    table = tomllib.loads((imggen.ART / "prompts.toml").read_text(encoding="utf-8"))
    style = (imggen.ART / "styles" / "A.txt").read_text(encoding="utf-8").strip()
    assert imggen.compose(imggen.arguments(["out.png", "A frog."])) == (
        f"{style} A frog. " + table["side"].format(bg="#FFFFFF"))
    with pytest.raises(SystemExit) as err:
        imggen.main([str(tmp_path / "out.png"), "A frog.", "--size", "4K"])
    assert err.value.code == 2 and not generator[-1]


@pytest.mark.parametrize("cap", [None, "NaN", "Infinity", "-1", ""])
def test_all_paid_entry_points_require_explicit_finite_cap(monkeypatch, tmp_path, cap):
    if cap is None:
        monkeypatch.delenv("COLLAGE_SPEND_CAP", raising=False)
    else:
        monkeypatch.setenv("COLLAGE_SPEND_CAP", cap)
    for call in (lambda: orc.chat("m", []), lambda: orc.chat_stream("m", []),
                 lambda: orc.tts("m", "text", "v", tmp_path / "out.mp3")):
        with pytest.raises(SystemExit, match="COLLAGE_SPEND_CAP"):
            call()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "books" / "spend.json"
    monkeypatch.setenv("LILYPAD_ART_SPEND", str(path))
    monkeypatch.setenv("COLLAGE_SPEND_CAP", "0.25")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-fixture")
    monkeypatch.setattr(orc, "_key_data", lambda key: {"usage": 20, "limit": 20.25, "limit_reset": None})
    return path


def test_parallel_calls_cannot_spend_same_balance(monkeypatch, ledger):
    sent, release = Event(), Event()

    def response(*args, **kwargs):
        sent.set()
        assert release.wait(5)
        return BytesIO(b'{"usage":{"cost":0.12}}')
    monkeypatch.setattr(orc, "_request", response)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(orc.chat, "m", [], est=0.15)
        try:
            assert sent.wait(5)
            with pytest.raises(SystemExit, match="SPEND CAP"):
                orc.chat("m", [], est=0.15)
        finally:
            release.set()
        assert first.result()["usage"]["cost"] == 0.12
    state = json.loads(ledger.read_text())
    assert not state["pending"] and len(state["log"]) == 1
    assert orc.spent() == 0.12
    with pytest.raises(SystemExit, match="SPEND CAP"):
        orc.chat("m", [], est=0.14)  # provider usage is still stale
    orc.chat("m", [], est=0.13)  # exact cap boundary


def test_uncertain_post_keeps_its_reservation_and_is_not_replayed(monkeypatch, ledger):
    calls = []
    def lost(*args, **kwargs):
        calls.append(args[0])
        raise TimeoutError("no response")
    monkeypatch.setattr(orc, "_request", lost)
    with pytest.raises(TimeoutError):
        orc.chat("m", [], est=0.20)
    with pytest.raises(SystemExit, match="SPEND CAP"):
        orc.chat("m", [], est=0.10)
    assert len(json.loads(ledger.read_text())["pending"]) == 1
    assert calls == ["/chat/completions"]


def test_legacy_ledger_shared_key_delta_and_headers(monkeypatch, ledger, tmp_path):
    ledger.parent.mkdir()
    ledger.write_text('{"baseline":19.81, "log":[]}')
    monkeypatch.setattr(orc, "_key_data", lambda key: {"usage": 20, "limit": 20.06, "limit_reset": None})
    with pytest.raises(SystemExit, match="SPEND CAP"):
        orc.chat("m", [], est=0.07)
    env = tmp_path / "test.env"
    env.write_text('OPENROUTER_API_KEY="synthetic-from-file"\n')
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENROUTER_ENV_FILE", str(env))
    requests = []
    def open_local(request, timeout):
        requests.append(request)
        return BytesIO(b'{"usage":{"cost":0.04}}')
    monkeypatch.setattr(orc.urllib.request, "urlopen", open_local)
    orc.chat("m", [], est=0.06)
    with pytest.raises(SystemExit, match="SPEND CAP"):
        orc.chat("m", [], est=0.03)  # $0.19 external + $0.04 ours despite delayed /key update
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-direct")
    assert orc._key() == "synthetic-direct"
    req, = requests
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["authorization"] == "Bearer synthetic-from-file"
    assert headers["http-referer"] == "https://localhost/lilypad-art"
    assert headers["x-title"] == "lilypad-art" and "synthetic" not in ledger.read_text()
    with pytest.raises(ValueError, match="different OpenRouter key"):
        orc.chat("m", [], est=0.01)


def test_key_without_limit_is_allowed_and_key_limit_is_a_second_fence(monkeypatch, ledger):
    """Lead ruling 2026-11-25: the ledger cap is the enforcement; a key limit, if any, only fences further."""
    monkeypatch.setattr(orc, "_key_data", lambda key: {"usage": 20, "limit": 20.005, "limit_reset": None})
    with pytest.raises(SystemExit, match="unreserved credit"):
        orc.chat("m", [], est=0.01)


def test_mocked_audio_and_stream_settle_in_shared_ledger(monkeypatch, ledger, tmp_path):
    def respond(route, body, timeout=600, *, key):
        if route == "/audio/speech":
            assert body["instructions"] == "gently" and body["response_format"] == "mp3"
            reply = BytesIO(b"synthetic audio")
            reply.headers = {"Content-Type": "audio/mpeg"}
            return reply
        assert route == "/chat/completions" and body["stream"] is True
        return BytesIO(b': ping\n\ndata: {"choices":[]}\n\ndata: {"usage":{"cost":0.02}}\n\ndata: [DONE]\n')
    monkeypatch.setattr(orc, "_request", respond)
    out = tmp_path / "voice.mp3"
    assert orc.tts("m", "hello", "v", out, instructions="gently") == {"Content-Type": "audio/mpeg"}
    assert out.read_bytes() == b"synthetic audio"
    assert orc.chat_stream("m", []) == [{"choices": []}, {"usage": {"cost": 0.02}}]
    assert orc.spent() == pytest.approx(0.0205)
    rows = json.loads(ledger.read_text())["log"]
    assert [row["kind"] for row in rows] == ["tts", "chat_stream"]


def test_batch_paths_and_per_job_args_from_unrelated_cwd(monkeypatch, tmp_path):
    jobs_dir = tmp_path / "project" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "ready.png").write_bytes(png("red"))
    outside = tmp_path / "absolute.png"
    extra = ["--style-file", "B.txt", "--front", "--size", "1K"]
    jobs = [{"out": "ready.png", "prompt": "skip"}, {"out": "new/pig.png", "prompt": "pig", "args": extra},
            {"out": str(outside), "prompt": "duck"}]
    manifest = jobs_dir / "jobs.json"
    manifest.write_text(json.dumps(jobs))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAR", raising=False)
    monkeypatch.setenv("LILYPAD_ART_SPEND", "shared/spend.json")
    calls = {}
    def run(command, cwd, env):
        assert cwd == jobs_dir and Path(command[1]) == imggen.ART / "imggen.py"
        assert Path(env["LILYPAD_ART_SPEND"]) == tmp_path / "shared/spend.json"
        calls[Path(command[2])] = command[3:]
        return imgbatch.subprocess.CompletedProcess(command, int(command[3] == "duck"))
    monkeypatch.setattr(imgbatch.subprocess, "run", run)
    assert imgbatch.main([str(manifest)]) == 1
    assert calls == {jobs_dir / "new/pig.png": ["pig", *extra], outside: ["duck"]}
