"""Waveform verification for borderline cuts.

For each cut window: extract audio, compute RMS energy in 25ms bins, classify:
  - SILENT (peak < -45 dB): safe artifact cut
  - LOW_ENERGY (peak < -30 dB): probably breath/throat-clear, safe to cut
  - SPEECH_LIKE (peak >= -30 dB): contains audible voice — manual review needed
"""
import subprocess
import json
import math
import wave
import struct
import tempfile
import os
from pathlib import Path

SOURCE = r'E:/Brock Red/Brock Red Blue versus Crystl.mp4'
OUT = Path('audio-checks/qa-cuts/waveform-verify.md')

# Cuts to verify with their listed type/reason
CUTS_TO_VERIFY = [
    (172.75, 173.05, 'orig-micro', 'throat-clear/breath'),
    (258.57, 259.05, 'orig-micro', 'empty inter-word breath'),
    (556.00, 556.28, 'orig-micro', 'silent gap'),
    (599.73, 600.42, 'orig-micro', 'inter-sentence silence'),
    (634.00, 634.82, 'new', 'silence gap between damage report and tactical thought'),
    (1778.85, 1779.28, 'orig-micro', 'silent gap mid-sentence'),
    (2325.30, 2325.78, 'orig-micro', 'throat-clear'),
    (2692.58, 2692.92, 'orig-micro', 'silent gap in outro'),
    # Investigation: 26.8s gap
    (1989.96, 2016.76, 'investigation', '26.8s speechless gap between seg 247 and seg 248'),
]


def extract_audio(src, start, end, out_wav):
    """ffmpeg extract audio to mono 16-bit 16kHz WAV."""
    dur = end - start
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-ss', f'{start:.3f}', '-i', src,
        '-t', f'{dur:.3f}',
        '-ac', '1', '-ar', '16000', '-sample_fmt', 's16',
        str(out_wav),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and out_wav.exists()


def analyze_wav(wav_path, bin_ms=25):
    """Read WAV, compute RMS in bin_ms windows, return peak/mean/silent_frac."""
    with wave.open(str(wav_path), 'rb') as w:
        sr = w.getframerate()
        nframes = w.getnframes()
        frames = w.readframes(nframes)
    samples = struct.unpack(f'<{nframes}h', frames)
    bin_samples = int(sr * bin_ms / 1000)
    bins = []
    for i in range(0, len(samples), bin_samples):
        chunk = samples[i:i + bin_samples]
        if not chunk:
            continue
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
        # Convert to dBFS (full scale = 32768 for s16)
        if rms < 1:
            db = -100.0
        else:
            db = 20 * math.log10(rms / 32768.0)
        bins.append(db)
    if not bins:
        return None
    return {
        'peak_db': max(bins),
        'mean_db': sum(bins) / len(bins),
        'silent_frac_minus45': sum(1 for b in bins if b < -45) / len(bins),
        'silent_frac_minus30': sum(1 for b in bins if b < -30) / len(bins),
        'speech_frac_minus20': sum(1 for b in bins if b > -20) / len(bins),
        'bins': len(bins),
        'sr': sr,
        'duration_s': nframes / sr,
    }


def classify(stats):
    if stats is None:
        return 'NO_AUDIO'
    p = stats['peak_db']
    if p < -45:
        return 'SILENT'
    if p < -30:
        return 'LOW_ENERGY'
    if p < -20:
        return 'BORDERLINE'
    return 'SPEECH_LIKE'


def main():
    report = ['# Waveform verification report\n',
              f'Source: `{SOURCE}`',
              f'Method: ffmpeg extract -> 16kHz mono s16 WAV -> RMS in 25ms bins -> classify by peak dBFS',
              '',
              'Classification thresholds:',
              '- **SILENT**: peak < -45 dBFS (safe artifact cut)',
              '- **LOW_ENERGY**: peak < -30 dBFS (breath/throat-clear, safe to cut)',
              '- **BORDERLINE**: peak < -20 dBFS (audible but quiet, manual review)',
              '- **SPEECH_LIKE**: peak >= -20 dBFS (contains voice, DO NOT cut)',
              '',
              '## Results\n',
              '| src range | dur (s) | category | peak dBFS | mean dBFS | silent frac < -45 | speech frac > -20 | notes |',
              '|---|---|---|---|---|---|---|---|']

    tmpdir = Path(tempfile.mkdtemp(prefix='waveform-verify-'))
    print(f'Temp: {tmpdir}')

    decisions = {}
    for start, end, category, descr in CUTS_TO_VERIFY:
        wav_path = tmpdir / f'cut-{start:.2f}-{end:.2f}.wav'
        ok = extract_audio(SOURCE, start, end, wav_path)
        if not ok:
            report.append(f'| {start:.2f}-{end:.2f} | {end-start:.2f} | EXTRACT_FAIL | - | - | - | - | {descr} |')
            decisions[(start, end)] = ('EXTRACT_FAIL', None)
            print(f'  EXTRACT_FAIL: {start}-{end}')
            continue
        stats = analyze_wav(wav_path)
        cls = classify(stats)
        decisions[(start, end)] = (cls, stats)
        report.append(
            f'| {start:.2f}-{end:.2f} | {end-start:.2f} | **{cls}** | '
            f'{stats["peak_db"]:.1f} | {stats["mean_db"]:.1f} | '
            f'{stats["silent_frac_minus45"]:.1%} | {stats["speech_frac_minus20"]:.1%} | '
            f'{category} - {descr} |'
        )
        print(f'  {start}-{end} ({end-start:.2f}s): {cls} | peak={stats["peak_db"]:.1f}dB | silent_frac={stats["silent_frac_minus45"]:.0%}')

    # For the 26.8s investigation specifically, sample bins
    big_gap = (1989.96, 2016.76)
    if big_gap in decisions:
        report.append('\n## Investigation: 26.8s gap at 1989.96-2016.76\n')
        wav = tmpdir / f'cut-{big_gap[0]:.2f}-{big_gap[1]:.2f}.wav'
        if wav.exists():
            stats = decisions[big_gap][1]
            cls = decisions[big_gap][0]
            report.append(f'- Peak: {stats["peak_db"]:.1f} dBFS')
            report.append(f'- Mean: {stats["mean_db"]:.1f} dBFS')
            report.append(f'- Silent frac (< -45 dBFS): {stats["silent_frac_minus45"]:.1%}')
            report.append(f'- Speech-like frac (> -20 dBFS): {stats["speech_frac_minus20"]:.1%}')
            report.append(f'- **Classification**: {cls}')
            report.append('')
            if cls == 'SILENT':
                report.append('**Recommendation:** PROMOTE TO CUT — 26.8s of dead air contributes nothing to the video.')
            elif cls == 'LOW_ENERGY':
                report.append('**Recommendation:** PROMOTE TO CUT — low-energy ambient/game audio only, no commentary.')
            else:
                report.append('**Recommendation:** DO NOT CUT — contains audible content (likely gameplay audio); leaving as-is.')

    report.append('\n## Decision summary\n')
    report.append('Apply these decisions to `proposed-cut-list-round2.json`:\n')
    for (s, e), (cls, stats) in decisions.items():
        if cls in ('SILENT', 'LOW_ENERGY'):
            report.append(f'- `{s:.2f}-{e:.2f}` -> **KEEP cut** (verified {cls})')
        elif cls == 'BORDERLINE':
            report.append(f'- `{s:.2f}-{e:.2f}` -> **KEEP cut + flag for manual review** ({cls}, peak {stats["peak_db"]:.1f} dB)')
        elif cls == 'SPEECH_LIKE':
            report.append(f'- `{s:.2f}-{e:.2f}` -> **REMOVE cut** (contains speech, would clip audible content)')
        elif cls == 'EXTRACT_FAIL':
            report.append(f'- `{s:.2f}-{e:.2f}` -> **MANUAL REVIEW** (audio extraction failed)')
        else:
            report.append(f'- `{s:.2f}-{e:.2f}` -> {cls}')

    OUT.write_text('\n'.join(report), encoding='utf-8')
    print(f'\nReport: {OUT}')

    # Cleanup temp
    for p in tmpdir.iterdir():
        try:
            p.unlink()
        except Exception:
            pass
    tmpdir.rmdir()


if __name__ == '__main__':
    main()
