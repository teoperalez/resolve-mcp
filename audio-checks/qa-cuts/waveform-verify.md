# Waveform verification report

Source: `E:/Brock Red/Brock Red Blue versus Crystl.mp4`
Method: ffmpeg extract -> 16kHz mono s16 WAV -> RMS in 25ms bins -> classify by peak dBFS

Classification thresholds:
- **SILENT**: peak < -45 dBFS (safe artifact cut)
- **LOW_ENERGY**: peak < -30 dBFS (breath/throat-clear, safe to cut)
- **BORDERLINE**: peak < -20 dBFS (audible but quiet, manual review)
- **SPEECH_LIKE**: peak >= -20 dBFS (contains voice, DO NOT cut)

## Results

| src range | dur (s) | category | peak dBFS | mean dBFS | silent frac < -45 | speech frac > -20 | notes |
|---|---|---|---|---|---|---|---|
| 172.75-173.05 | 0.30 | **SPEECH_LIKE** | -16.2 | -37.3 | 50.0% | 25.0% | orig-micro - throat-clear/breath |
| 258.57-259.05 | 0.48 | **SPEECH_LIKE** | -17.0 | -33.1 | 35.0% | 25.0% | orig-micro - empty inter-word breath |
| 556.00-556.28 | 0.28 | **SPEECH_LIKE** | -18.7 | -56.8 | 58.3% | 16.7% | orig-micro - silent gap |
| 599.73-600.42 | 0.69 | **SPEECH_LIKE** | -17.3 | -36.0 | 32.1% | 17.9% | orig-micro - inter-sentence silence |
| 634.00-634.82 | 0.82 | **BORDERLINE** | -22.2 | -48.9 | 66.7% | 0.0% | new - silence gap between damage report and tactical thought |
| 1778.85-1779.28 | 0.43 | **SPEECH_LIKE** | -18.5 | -36.3 | 33.3% | 5.6% | orig-micro - silent gap mid-sentence |
| 2325.30-2325.78 | 0.48 | **BORDERLINE** | -20.9 | -40.4 | 40.0% | 0.0% | orig-micro - throat-clear |
| 2692.58-2692.92 | 0.34 | **SPEECH_LIKE** | -16.1 | -39.3 | 50.0% | 21.4% | orig-micro - silent gap in outro |
| 1989.96-2016.76 | 26.80 | **LOW_ENERGY** | -39.2 | -70.0 | 98.4% | 0.0% | investigation - 26.8s speechless gap between seg 247 and seg 248 |

## Investigation: 26.8s gap at 1989.96-2016.76

- Peak: -39.2 dBFS
- Mean: -70.0 dBFS
- Silent frac (< -45 dBFS): 98.4%
- Speech-like frac (> -20 dBFS): 0.0%
- **Classification**: LOW_ENERGY

**Recommendation:** PROMOTE TO CUT — low-energy ambient/game audio only, no commentary.

## Decision summary

Apply these decisions to `proposed-cut-list-round2.json`:

- `172.75-173.05` -> **REMOVE cut** (contains speech, would clip audible content)
- `258.57-259.05` -> **REMOVE cut** (contains speech, would clip audible content)
- `556.00-556.28` -> **REMOVE cut** (contains speech, would clip audible content)
- `599.73-600.42` -> **REMOVE cut** (contains speech, would clip audible content)
- `634.00-634.82` -> **KEEP cut + flag for manual review** (BORDERLINE, peak -22.2 dB)
- `1778.85-1779.28` -> **REMOVE cut** (contains speech, would clip audible content)
- `2325.30-2325.78` -> **KEEP cut + flag for manual review** (BORDERLINE, peak -20.9 dB)
- `2692.58-2692.92` -> **REMOVE cut** (contains speech, would clip audible content)
- `1989.96-2016.76` -> **KEEP cut** (verified LOW_ENERGY)