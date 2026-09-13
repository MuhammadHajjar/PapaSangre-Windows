"""Measure how much a transcode actually costs us.

The whole game is sound, so the conversion from the original AAC to whatever the
Windows build ships must be inaudible.  This tool takes a representative sample
of the shipped assets, encodes each one at several candidate settings, decodes
both the original and the candidate, aligns them and reports:

  * added-noise SNR in dB (signal power / power of the difference)
  * peak absolute error
  * error energy restricted to 0-16 kHz, where the source AAC still has content
  * resulting file size

Run:  python tools/codec_trial.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')

# A deliberately awkward cross-section: sharp transients, tonal loops, speech,
# mono monster loops and positioned world sounds.
SAMPLE = [
    'ps1/footsteps/foot_stone_s1_L_a.m4a',        # short transient, stereo
    'ps1/footsteps/foot_brokenglass_s1_L_a.m4a',  # broadband transient
    'ps1/footsteps/foot_icethin_s3_R_a.m4a',      # fast-speed variant
    'ps1/atmos/Atmos_darkrumble_01.m4a',          # low-frequency loop
    'ps1/atmos/atmos_glassgongwind_01.m4a',       # tonal / metallic loop
    'ps1/atmos/atmos_crickets_01.m4a',            # dense high-frequency loop
    'ps1/cutscenes/FINAL_ITD_Intro.m4a',          # 112 s of narration
    'ps1/cutscenes/FINAL_BedofBones_Fail.m4a',    # narration + effects
    'ps1/monsters/monster_hog1_01_dry_chase.m4a',  # mono, spatialised source
    'ps1/monsters/monster_reaper2_01_dry_chase.m4a',
    'ps1/spatialized/door_castle_living.m4a',     # positioned loop
    'ps1/reactions/FINAL_ITD_notecollect_1.m4a',  # musical sting
]

CANDIDATES = [
    ('vorbis-q5', ['-c:a', 'libvorbis', '-q:a', '5']),
    ('vorbis-q6', ['-c:a', 'libvorbis', '-q:a', '6']),
    ('vorbis-q7', ['-c:a', 'libvorbis', '-q:a', '7']),
    ('vorbis-q8', ['-c:a', 'libvorbis', '-q:a', '8']),
    ('vorbis-q10', ['-c:a', 'libvorbis', '-q:a', '10']),
    ('flac', ['-c:a', 'flac', '-compression_level', '8']),
]

FFMPEG = 'ffmpeg'


def decode(path: str) -> tuple[np.ndarray, int]:
    """Decode any input to float64 PCM via ffmpeg (so AAC and Ogg agree)."""
    out = subprocess.run(
        [FFMPEG, '-v', 'error', '-i', path, '-f', 'f32le', '-acodec',
         'pcm_f32le', '-'],
        capture_output=True, check=True).stdout
    info = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries',
         'stream=sample_rate,channels', '-of', 'csv=p=0', path],
        capture_output=True, check=True, text=True).stdout.strip().split(',')
    sr, ch = int(info[0]), int(info[1])
    a = np.frombuffer(out, dtype='<f4').astype(np.float64)
    if ch > 1:
        a = a.reshape(-1, ch)
    return a, sr


def align(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Trim to a common length after correcting any whole-sample offset."""
    am = a if a.ndim == 1 else a.mean(axis=1)
    bm = b if b.ndim == 1 else b.mean(axis=1)
    n = min(len(am), len(bm), 200000)
    # search a small window; codec delay is at most a few thousand samples
    best, best_lag = -1e30, 0
    seg = am[:n]
    for lag in range(-4096, 4097, 1):
        s = max(0, lag)
        e = min(n, n + lag)
        if e - s < n // 2:
            continue
        x = seg[s:e]
        y = bm[s - lag:e - lag]
        c = float(np.dot(x, y))
        if c > best:
            best, best_lag = c, lag
    if best_lag > 0:
        b = b[best_lag:]
    elif best_lag < 0:
        a = a[-best_lag:]
    m = min(len(a), len(b))
    return a[:m], b[:m], best_lag


def band_energy(x: np.ndarray, sr: int, hi: float) -> float:
    if x.ndim > 1:
        x = x.mean(axis=1)
    n = min(len(x), 1 << 20)
    X = np.fft.rfft(x[:n])
    f = np.fft.rfftfreq(n, 1.0 / sr)
    return float(np.sum(np.abs(X[f <= hi]) ** 2))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix='ps_codec_')
    print(f'{"file":<44}{"candidate":<12}{"SNR dB":>8}{"<16k dB":>9}'
          f'{"peak err":>10}{"size %":>8}')
    print('-' * 91)
    totals: dict[str, list[float]] = {name: [] for name, _ in CANDIDATES}
    sizes: dict[str, list[float]] = {name: [] for name, _ in CANDIDATES}

    for rel in SAMPLE:
        src = os.path.join(BUNDLE, rel)
        if not os.path.exists(src):
            print(f'  MISSING {rel}')
            continue
        ref, sr = decode(src)
        src_size = os.path.getsize(src)
        refp = float(np.sum(ref ** 2))
        short = os.path.basename(rel)

        for name, args in CANDIDATES:
            ext = 'flac' if name == 'flac' else 'ogg'
            dst = os.path.join(tmp, f'{short}.{name}.{ext}')
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-i', src, *args, dst],
                           check=True, capture_output=True)
            cand, _ = decode(dst)
            a, b, lag = align(ref, cand)
            err = a - b
            errp = float(np.sum(err ** 2))
            snr = 10 * np.log10(refp / errp) if errp > 0 else float('inf')
            e16 = band_energy(err, sr, 16000.0)
            r16 = band_energy(a, sr, 16000.0)
            snr16 = 10 * np.log10(r16 / e16) if e16 > 0 else float('inf')
            peak = float(np.max(np.abs(err))) if err.size else 0.0
            pct = 100.0 * os.path.getsize(dst) / src_size
            totals[name].append(snr)
            sizes[name].append(pct)
            print(f'{short:<44}{name:<12}{snr:8.1f}{snr16:9.1f}'
                  f'{peak:10.5f}{pct:8.0f}')
        print()

    print('=' * 91)
    print(f'{"candidate":<20}{"median SNR dB":>16}{"worst SNR dB":>15}'
          f'{"median size %":>16}')
    for name, _ in CANDIDATES:
        v = [x for x in totals[name] if np.isfinite(x)]
        s = sizes[name]
        if not v:
            continue
        print(f'{name:<20}{np.median(v):16.1f}{min(v):15.1f}{np.median(s):16.0f}')
    print(f'\nscratch: {tmp}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
