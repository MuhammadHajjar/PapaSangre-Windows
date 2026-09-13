"""Recover the original HRTF from the iOS binary and emit a makemhr data set.

Papa Engine embeds its default HRTF inside the executable and loads it through
an in-memory ``MemFile`` (log line: *"Using the builtin, embedded default HRTF
instead."*).  ``tools/embedded_hrtf.dat`` is that blob, lifted verbatim from
offset 0x100142c54 (length word at 0x1002bb188).

Layout, from ``MemFile``-based loader at 0x1000cad04:

    line 1            "HRTF <name>\\t<dirs>\\t<total>\\t<perEar>\\t<channels>"
    next <dirs> lines "<azimuth>\\t<elevation>"   (IRCAM LISTEN convention:
                                                   azimuth counter-clockwise)
    blank line
    per direction     4 blocks, each fread(size=8, count=perEar)
                      = 4 x 256 interleaved complex float32 (re, im)
                      order: A[0] B[0] A[1] B[1]
    trailer           "HRTF\\n"

Blocks A[1]/B[1] (the third and fourth) are the left- and right-ear transfer
functions.  The bins are stored **conjugated** relative to the usual DFT sign
convention: reading them as (re + i*im) gives the right magnitude response but
time-reverses the impulse, which shows up as an interaural delay of the correct
size and the wrong sign.  Reading them as (re - i*im) yields causal impulse
responses whose ITD and ILD agree and match a real head (see ``validate``).
Blocks A[0]/B[0] are a second, much lower-energy pair whose purpose is not yet
established; they are not used.

Outputs (under ``build/hrtf/``):
    wav/az###_el###.wav   one stereo WAV per direction (left ear, right ear)
    papa_ircam_1050.def   makemhr definition file
Then run makemhr to produce the .mhr that OpenAL Soft loads.
"""

from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOB = os.path.join(ROOT, 'tools', 'embedded_hrtf.dat')
OUT = os.path.join(ROOT, 'build', 'hrtf')

SAMPLE_RATE = 44100          # CSL ran at 44.1 kHz; the IRCAM sets are 44.1 kHz
HEAD_RADIUS = 0.09           # metres, the value openal-soft's IRCAM def uses
DISTANCE = 1.95              # metres, IRCAM LISTEN measurement radius

#: makemhr's elevation grid: 13 rings, -90 to +90 in 15 degree steps.
MHR_ELEVATIONS = [-90 + 15 * i for i in range(13)]
MHR_AZIMUTH_COUNTS = [1, 6, 12, 24, 24, 24, 24, 24, 24, 24, 12, 6, 1]


def load_blob(path: str = BLOB):
    raw = open(path, 'rb').read()
    nl = raw.index(b'\n')
    header = raw[:nl].decode()
    fields = header.split('\t')
    name = fields[0].split(' ', 1)[1]
    ndirs, total, per_ear, channels = (int(x) for x in fields[1:5])

    pos = nl + 1
    dirs: list[tuple[int, int]] = []
    for _ in range(ndirs):
        e = raw.index(b'\n', pos)
        az, el = raw[pos:e].decode().split('\t')
        dirs.append((int(az), int(el)))
        pos = e + 1
    if raw[pos:pos + 1] == b'\n':        # blank separator line
        pos += 1

    need = ndirs * 4 * per_ear * 2       # 4 blocks x per_ear complex float32
    data = np.frombuffer(raw[pos:pos + need * 4], dtype='<f4')
    if data.size != need:
        raise ValueError(f'expected {need} floats, found {data.size}')
    if raw[pos + need * 4:] not in (b'HRTF\n', b''):
        raise ValueError(f'unexpected trailer {raw[pos + need * 4:][:16]!r}')
    blocks = data.astype(np.float64).reshape(ndirs, 4, per_ear * 2)
    return name, dirs, per_ear, blocks


def spectrum_to_ir(block: np.ndarray) -> np.ndarray:
    """One block of interleaved (re, im) bins -> real impulse response.

    ``n`` bins describe the lower half of a ``2n``-point real spectrum; the
    upper half is the conjugate mirror.  The stored bins are conjugated (see
    the module docstring), so the imaginary part is negated before transforming.
    The result is already causal - the response starts within the first few
    samples - so no rolling is needed.
    """
    n = block.size // 2
    bins = block[0::2] - 1j * block[1::2]
    full = np.concatenate([bins, [0.0], np.conj(bins[1:][::-1])])
    return np.fft.irfft(full, 2 * n)


def energy_centroid(ir: np.ndarray) -> float:
    """Circular energy centroid, in samples.

    Robust where a plain onset threshold is not: the responses are short and
    can sit right against the window boundary, so the centroid is computed on
    the unit circle and mapped back.
    """
    n = ir.size
    a = ir ** 2
    th = 2.0 * np.pi * np.arange(n) / n
    z = complex(np.sum(a * np.exp(1j * th)))
    return float(np.angle(z) % (2.0 * np.pi)) * n / (2.0 * np.pi)


def validate(dirs, irs) -> None:
    """Check the reconstruction against the physics of a real head.

    A correct HRIR set must have interaural time and level differences that
    agree with each other and with the source direction: the near ear is both
    louder and earlier, the effect peaks at +/-90 degrees and vanishes front
    and back, and the delay stays within what a head-sized path difference can
    produce (the Woodworth bound for r = 9 cm is about 0.67 ms, ~30 samples).
    """
    n = irs.shape[2]
    woodworth = HEAD_RADIUS * (np.pi / 2 + 1.0) / 343.0 * SAMPLE_RATE
    print(f'  Woodworth ITD bound at r={HEAD_RADIUS} m: '
          f'+/-{woodworth:.1f} samples ({woodworth / SAMPLE_RATE * 1000:.2f} ms)')
    print(f'  {"az":>5}{"ITD (samples)":>15}{"ILD (dB)":>11}   expected')
    bad = 0
    for az in (0, 30, 60, 90, 120, 180, 240, 270, 300, 330):
        i = dirs.index((az, 0))
        L, R = irs[i]
        cl, cr = energy_centroid(L), energy_centroid(R)
        itd = (cr - cl + n / 2) % n - n / 2      # >0 means the left ear leads
        eL = float(np.sum(L ** 2))
        eR = float(np.sum(R ** 2))
        ild = 10 * np.log10(eL / eR) if eR > 0 else float('inf')
        # IRCAM azimuth is counter-clockwise: 0-180 is the LEFT half-plane
        if az in (0, 180):
            expect = 'symmetric'
            ok = abs(ild) < 3.0 and abs(itd) < 5.0
        elif 0 < az < 180:
            expect = 'left near'
            ok = ild > 0 and itd > 0
        else:
            expect = 'right near'
            ok = ild < 0 and itd < 0
        if abs(itd) > woodworth * 1.5:
            ok = False
        bad += (not ok)
        print(f'  {az:>5}{itd:>15.2f}{ild:>11.2f}   {expect:<12}'
              f'{"OK" if ok else "  <-- FAILS"}')
    if bad:
        raise SystemExit(f'HRTF reconstruction failed {bad} physical checks')
    print('  interaural time and level differences agree; all checks pass')


def main() -> int:
    name, dirs, per_ear, blocks = load_blob()
    print(f'HRTF "{name}": {len(dirs)} directions, {per_ear} taps per ear')

    irs = np.empty((len(dirs), 2, per_ear * 2))
    for i in range(len(dirs)):
        irs[i, 0] = spectrum_to_ir(blocks[i, 2])   # A[1] -> left ear
        irs[i, 1] = spectrum_to_ir(blocks[i, 3])   # B[1] -> right ear

    # energy sanity: a causal, compact response keeps its energy up front
    head = float(np.sum(irs[:, :, :128] ** 2) / np.sum(irs ** 2))
    print(f'  energy within the first 128 taps: {head * 100:.2f}%')

    print('\nvalidating against head physics:')
    validate(dirs, irs)

    # ---- write the makemhr data set ----------------------------------
    import soundfile as sf
    wavdir = os.path.join(OUT, 'wav')
    os.makedirs(wavdir, exist_ok=True)

    # index by (elevation, ircam azimuth), dropping the duplicate row
    table: dict[tuple[int, int], int] = {}
    dupes = 0
    for i, (az, el) in enumerate(dirs):
        if (el, az) in table:
            dupes += 1
            continue
        table[(el, az)] = i
    print(f'\n  {dupes} duplicate direction row(s) dropped')

    peak = float(np.max(np.abs(irs)))
    lines: list[str] = []
    written = 0
    missing_rings = []
    for ei, el in enumerate(MHR_ELEVATIONS):
        naz = MHR_AZIMUTH_COUNTS[ei]
        have = [a for (e, a) in table if e == el]
        if not have:
            missing_rings.append(el)
            continue
        have.sort()
        for ai in range(naz):
            # makemhr's azimuth index runs clockwise; IRCAM's runs
            # counter-clockwise, so index k maps to IRCAM (360 - 360k/naz).
            want = (360 - ai * 360.0 / naz) % 360
            # Match the nearest measured azimuth on this ring.  At the pole
            # (naz == 1) azimuth is meaningless and the single measurement is
            # filed under 180 in the original data, so nearest-match handles it.
            ircam_az = min(have, key=lambda a: min(abs(a - want),
                                                   360 - abs(a - want)))
            gap = min(abs(ircam_az - want), 360 - abs(ircam_az - want))
            if naz > 1 and gap > 1.0:
                raise SystemExit(
                    f'el={el}: no measurement near azimuth {want:.1f} '
                    f'(nearest {ircam_az}, off by {gap:.1f} degrees)')
            idx = table[(el, ircam_az)]
            fn = f'az{ircam_az:03d}_el{el:+04d}.wav'
            stereo = np.stack([irs[idx, 0], irs[idx, 1]], axis=1) / peak
            sf.write(os.path.join(wavdir, fn), stereo, SAMPLE_RATE,
                     subtype='FLOAT')
            lines.append(f'[ {ei:>2}, {ai:>2} ] = '
                         f'wave (0) : "wav/{fn}" left\n'
                         f'           + wave (1) : "wav/{fn}" right')
            written += 1

    if missing_rings:
        print(f'  elevations not measured by IRCAM (omitted): {missing_rings}')

    defpath = os.path.join(OUT, 'papa_ircam_1050.def')
    with open(defpath, 'w', encoding='utf-8') as fh:
        fh.write(
            '# Papa Sangre HRTF, recovered from the iOS binary.\n'
            f'# IRCAM LISTEN subject {name}, {len(dirs)} measured directions.\n'
            '# Generated by tools/extract_hrtf.py -- do not edit by hand.\n\n'
            f'rate     = {SAMPLE_RATE}\n'
            'type     = stereo\n'
            f'points   = {per_ear * 2}\n'
            f'radius   = {HEAD_RADIUS}\n'
            f'distance = {DISTANCE}\n'
            f'azimuths = {", ".join(str(n) for n in MHR_AZIMUTH_COUNTS)}\n\n')
        fh.write('\n'.join(lines))
        fh.write('\n')

    print(f'\n  wrote {written} stereo WAVs to {wavdir}')
    print(f'  wrote {defpath}')
    print('\nnext:  vendor/makemhr/makemhr.exe -i build/hrtf/papa_ircam_1050.def '
          '-o build/hrtf/papa_ircam_1050.mhr')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
