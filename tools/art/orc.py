"""OpenRouter calls and the shared, project-relative spend ledger (USD)."""

import base64
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
import urllib.error
import urllib.request
from uuid import uuid4

API = "https://openrouter.ai/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def _key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    filename = os.environ.get("OPENROUTER_ENV_FILE")
    if filename:
        for line in Path(filename).read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.startswith("OPENROUTER_API") and value.strip().strip('"'):
                return value.strip().strip('"')
    raise SystemExit("Set OPENROUTER_API_KEY or OPENROUTER_ENV_FILE.")


def _money(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Expected a finite, nonnegative USD amount.") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("Expected a finite, nonnegative USD amount.")
    return amount


def _cap():
    try:
        return _money(os.environ["COLLAGE_SPEND_CAP"])
    except (KeyError, ValueError):
        raise SystemExit("Set COLLAGE_SPEND_CAP to a finite, nonnegative USD cap.") from None


def _request(path, body=None, timeout=600, *, key):
    request = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "HTTP-Referer": "https://localhost/lilypad-art", "X-Title": "lilypad-art"},
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # Provider error bodies can echo request data. Keep credentials out of logs.
        exc.close()
        raise RuntimeError(f"OpenRouter returned HTTP {exc.code}") from None


def _key_data(key):
    with _request("/key", key=key) as response:
        return json.load(response)["data"]


def usage():
    return _key_data(_key())["usage"]


def _spend_file():
    return Path(os.environ.get("LILYPAD_ART_SPEND", ROOT / "work" / "spend.json")).resolve()


@contextmanager
def _lock(path):
    # Lock a stable sibling: the ledger itself is replaced atomically.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield  # closing the handle also releases the lock after an exception


def atomic_write(path, data):
    """Publish a complete file on the same volume, including on Windows."""
    tmp = NamedTemporaryFile(dir=path.parent, delete=False)
    name = Path(tmp.name)
    try:
        with tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        name.replace(path)
    finally:
        name.unlink(missing_ok=True)


def _write(path, state):
    atomic_write(path, json.dumps(state, indent=2, allow_nan=False).encode("utf-8"))


def _check_budget(status, baseline, total, estimate, cap):
    next_total = total + _money(estimate)
    if next_total > cap:
        raise SystemExit(f"SPEND CAP: ${total} used/reserved + ${estimate} exceeds ${cap}.")
    # Estimates control admission. Only the provider can bound the final
    # bill for an arbitrary model if it charges more than the estimate.
    # The ledger cap above is the enforcement. A key-level limit, when the key has one, is only a second fence.
    limit = status.get("limit")
    if limit is not None and baseline + next_total > _money(limit):
        raise SystemExit("SPEND CAP: estimate exceeds the key's unreserved credit.")


def _balance(path, key, estimate=None, reservation=None):
    cap = _cap()
    status = _key_data(key)
    current = _money(status["usage"])
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    with _lock(path):
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
        else:
            state = {"baseline": float(current), "log": []}
        if state.get("key_fingerprint", fingerprint) != fingerprint:
            raise ValueError("The spend ledger belongs to a different OpenRouter key.")
        baseline = _money(state["baseline"])
        delta = current - baseline
        if delta < 0:
            raise ValueError("Key usage is below the ledger baseline. Check the key and ledger.")
        logged = sum(_money(row.get("cost", row["est"])) for row in state["log"])
        # Remember key-wide usage already observed when admitting a call. A
        # delayed /key update must not make an acknowledged charge spendable again.
        floor = max(delta, logged, _money(state.get("settled_floor", 0)))
        pending = state.setdefault("pending", {})
        total = floor + sum(_money(row["est"]) for row in pending.values())
        if estimate is not None:
            _check_budget(status, baseline, total, estimate, cap)
        if reservation is not None:
            token, row = reservation
            state["settled_floor"] = str(floor)
            pending[token] = row
        if reservation is not None or not path.exists():
            state["key_fingerprint"] = fingerprint
            _write(path, state)
    return total


def spent():
    _cap()
    return float(_balance(_spend_file(), _key()))


def guard(estimate=0.0):
    _cap()
    return float(_balance(_spend_file(), _key(), estimate))


def _reserve(kind, model, note, estimate):
    _cap()  # fail before any credential access or network request
    if _money(estimate) <= 0:
        raise ValueError("A paid call needs a positive USD estimate.")
    token = uuid4().hex
    row = {"t": time.strftime("%H:%M:%S"), "kind": kind, "model": model,
           "note": note, "est": float(estimate)}
    path, key = _spend_file(), _key()
    _balance(path, key, estimate, (token, row))
    return path, token, key


def _settle(path, token, cost):
    with _lock(path):
        state = json.loads(path.read_text(encoding="utf-8"))
        row = state["pending"].pop(token)
        if cost is not None:
            row["cost"] = float(_money(cost))
        state["settled_floor"] = str(_money(state["settled_floor"]) + _money(row.get("cost", row["est"])))
        state["log"].append(row)
        _write(path, state)


def chat(model, messages, est=0.05, **kw):
    path, token, key = _reserve("chat", model, kw.pop("_note", ""), est)
    with _request("/chat/completions", {"model": model, "messages": messages, **kw}, 900, key=key) as resp:
        result = json.load(resp)
    _settle(path, token, (result.get("usage") or {}).get("cost"))
    return result


def chat_stream(model, messages, est=0.1, **kw):
    """Return decoded SSE chunks (including streaming audio), in provider order."""
    path, token, key = _reserve("chat_stream", model, kw.pop("_note", ""), est)
    body = {"model": model, "messages": messages, **kw, "stream": True}
    chunks = []
    with _request("/chat/completions", body, 900, key=key) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    chunks.append(json.loads(payload))
    cost = next((c["usage"]["cost"] for c in reversed(chunks)
                 if (c.get("usage") or {}).get("cost") is not None), None)
    _settle(path, token, cost)
    return chunks


def tts(model, text, voice, out, fmt="mp3", instructions=None, price_per_char=0.0001, extra=None):
    body = {"model": model, "input": text, "voice": voice, "response_format": fmt}
    if instructions:
        body["instructions"] = instructions
    body.update(extra or {})
    estimate = len(body["input"]) * _money(price_per_char)
    path, token, key = _reserve("tts", body["model"], f"{voice} {Path(out).name}", estimate)
    with _request("/audio/speech", body, key=key) as resp:
        data, headers = resp.read(), dict(resp.headers)
    _settle(path, token, None)
    Path(out).write_bytes(data)
    return headers


def b64file(path):
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


if __name__ == "__main__":
    print(f"Project spend (including reservations) ${spent():.4f} of ${_cap()}")
