"""Build fixed-tempo, 4/4 .beats.json sidecars for a track or folder of WAV/OGG/MP3 files.

Use --bpm to lock a generated anthem to a known tempo. The first detected beat starts bar one.
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np

if __package__:
    from . import orc
else:
    import orc

EXTENSIONS = {".wav", ".ogg", ".mp3"}


def decode(path):
    try:
        import soundfile
    except ImportError:
        # pygame-ce is already a project dependency. SDL_mixer can decode these
        # formats without an audio device or extra Python codec bindings.
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        import pygame
        started = not pygame.mixer.get_init()
        if started:
            pygame.mixer.init(frequency=22050, size=-16, channels=2)
        try:
            samples = pygame.sndarray.array(pygame.mixer.Sound(str(path))).astype(np.float32)
            rate, bits, _channels = pygame.mixer.get_init()
            samples /= 2 ** (abs(bits)-1)
            if bits > 0:
                samples -= 1
        finally:
            if started:
                pygame.mixer.quit()
    else:
        samples, rate = soundfile.read(path, always_2d=True, dtype="float32")
    return samples.mean(axis=1) if samples.ndim == 2 else samples, rate


def numpy_flux(audio, size, hop):
    """Positive spectral flux, processing bounded batches even for a long parent track."""
    padded = np.pad(audio, (size//2, size//2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, size)[::hop]
    window = np.hanning(size)
    flux = np.empty(len(frames))
    previous = np.zeros(size//2 + 1)
    for start in range(0, len(frames), 256):
        spectrum = np.log1p(np.abs(np.fft.rfft(frames[start:start+256] * window)))
        delta = np.diff(spectrum, axis=0, prepend=previous[None,:])
        flux[start:start+len(spectrum)] = np.maximum(delta, 0).mean(axis=1)
        previous = spectrum[-1]
    return flux


def tempo(flux, fps):
    # FFT autocorrelation avoids a quadratic pass over long tracks. A weak
    # octave preference breaks ties between equally good harmonics.
    centered = flux - flux.mean()
    nfft = 1 << (2*len(flux)-1).bit_length()
    corr = np.fft.irfft(np.abs(np.fft.rfft(centered, nfft))**2, nfft)
    lags = np.arange(int(np.ceil(fps/3)), min(len(flux)//2, int(np.floor(fps)))+1)
    if not len(lags):
        raise ValueError("Track is too short for a tempo estimate")
    scores = corr[lags] / (len(flux)-lags)
    scores *= np.exp(-.1*np.log2(lags/(fps*.5))**2)
    lag = lags[np.argmax(scores)]
    if corr[lag] <= 0:
        raise ValueError("No recurring beat detected")
    left, mid, right = corr[lag-1:lag+2]
    curvature = left - 2*mid + right
    fraction = np.clip(.5*(left-right)/curvature, -.5, .5) if curvature < 0 else 0
    return float(np.clip(60*fps/(lag+fraction), 60, 180))


def analyze(audio, rate, *, bpm=None, backend="auto"):
    if rate <= 0 or len(audio) < rate or not np.isfinite(audio).all():
        raise ValueError("Expected at least one second of finite audio")
    if bpm is not None and not 60 <= bpm <= 180:
        raise ValueError("Expected BPM in [60, 180]")
    hop = max(1, round(rate*.01))
    size = 1 << max(5, round(np.log2(rate*.04)))
    if backend != "numpy":
        try:
            import librosa
        except ImportError:
            backend = "numpy"
    if backend == "numpy":
        flux = numpy_flux(audio, size, hop)
    else:
        flux = librosa.onset.onset_strength(y=audio, sr=rate, hop_length=hop, n_fft=size,
                                            n_mels=40, fmax=rate/2)
    if not np.any(flux > 0):
        raise ValueError("No onsets in track")
    fps = rate/hop
    bpm = tempo(flux, fps) if bpm is None else bpm
    period = 60 / bpm
    # Fold energy attacks onto the tempo grid. Using audio here avoids the
    # STFT window/centering latency of either onset backend.
    blocks = np.pad(audio, (0, -len(audio) % hop)).reshape(-1, hop)
    energy = np.sqrt((blocks**2).mean(axis=1))
    attacks = np.maximum(0, np.diff(energy, prepend=0))
    times = np.arange(len(attacks))/fps
    bins = round(period*fps)
    phases = np.rint(times/period*bins).astype(int) % bins
    folded = np.bincount(phases, weights=attacks, minlength=bins)
    phase = np.argmax(folded + .5*(np.roll(folded, -1) + np.roll(folded, 1))) / bins * period
    first = times[np.flatnonzero(attacks >= .025*attacks.max())[0]]
    offset = max(0., phase + round((first-phase)/period)*period)
    beats = np.arange(offset, len(audio)/rate, period)
    downbeats = beats[::4]
    drops = []
    # A drop is a strong downbeat following a quieter bar; skip the opening bar.
    for downbeat in downbeats[1:]:
        at = round(downbeat*fps)
        prior = energy[max(0, at-round(4*period*fps)):at]
        after = energy[at:at+max(1, round(period*fps))]
        if prior.size and after.size and after.mean() > max(.12*energy.max(), 2.5*prior.mean()):
            drops.append(round(float(downbeat), 6))
    return dict(bpm=round(float(bpm), 5), offset=round(float(offset), 6),
                beats=beats.round(6).tolist(), downbeats=downbeats.round(6).tolist(), drops=drops)


def process(path, bpm=None, backend="auto"):
    tracks = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS
                    ) if path.is_dir() else [path]
    if not tracks:
        raise ValueError(f"No WAV/OGG/MP3 tracks in {path}")
    for track in tracks:
        if track.suffix.lower() not in EXTENSIONS:
            raise ValueError(f"Unsupported track: {track}")
        audio, rate = decode(track)
        result = analyze(audio, rate, bpm=bpm, backend=backend)
        sidecar = Path(str(track) + ".beats.json")
        orc.atomic_write(sidecar, (json.dumps(result, indent=2, allow_nan=False) + "\n").encode())
        print(f"{sidecar}: {result['bpm']} BPM, {len(result['beats'])} beats")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path)
    p.add_argument("--bpm", type=float)
    p.add_argument("--backend", choices=("auto", "numpy"), default="auto")
    args = p.parse_args(argv)
    process(args.path, args.bpm, args.backend)


if __name__ == "__main__":
    main()
