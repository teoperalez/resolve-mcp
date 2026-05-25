"""Promote round-2 cut list to canonical cut-analysis-4.out.md format."""
import json
import shutil
from pathlib import Path

ROUND2 = Path('audio-checks/qa-cuts/proposed-cut-list-round2.json')
CANONICAL = Path('plans/prompts/cut-analysis-4.out.md')

# Back up the current canonical file
backup = Path('audio-checks/qa-cuts/cut-analysis-4.previous.out.md')
if CANONICAL.exists():
    shutil.copy(CANONICAL, backup)
    print(f'Backed up existing canonical to {backup}')

# Read round-2 list and write to canonical schema (no extra fields)
cuts = json.loads(ROUND2.read_text(encoding='utf-8'))
clean = []
for c in cuts:
    clean.append({
        'start_sec': c['start_sec'],
        'end_sec': c['end_sec'],
        'confidence': c['confidence'],
        'type': c['type'],
        'reason': c['reason'],
    })

CANONICAL.write_text(json.dumps(clean, indent=2), encoding='utf-8')
total = sum(c['end_sec'] - c['start_sec'] for c in clean)
print(f'Promoted {len(clean)} cuts to {CANONICAL}')
print(f'Total source seconds: {total:.2f}s')
