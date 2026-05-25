"""Pure-Python leader → (intro video, audio) asset resolver for Gen 1 RBY pipelines.

No Resolve dependency. Stdlib only. Importable from the skill orchestrator,
testable in isolation, and reusable from any future Gen 1 edit-timeline skill.

The mapping is grounded in the actual on-disk asset matrix at
`C:\\Programming\\RBYNewLayout\\gymLeaders\\LeaderIntros\\` and `.../audio/`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

Version = Literal['yellow', 'red_blue']


@dataclass(frozen=True)
class LeaderAssets:
    """Resolved per-leader asset paths."""
    leader_key: str             # raw key from session log: BROCK, MISTY, etc.
    pretty_name: str            # Pretty form for marker labels: Brock, Misty, etc.
    audio_filename: str         # filename only, e.g. "Brock.mp3" or "Giovanni 1.mp3"
    audio_path: Path            # full path
    intro_video_filename: Optional[str]   # None if no video for this leader
    intro_video_path: Optional[Path]
    has_intro_video: bool       # convenience: True if intro_video_path resolves
    category: str               # 'gym_leader' | 'rival' | 'champion' | 'rocket_special'

    @property
    def first_appearance_inserts_intro(self) -> bool:
        """True if first-appearance battles should insert a V1 intro video."""
        return self.has_intro_video


# ──────────────────────────────────────────────────────────────────────────────
# Core mapping table (verified against on-disk assets 2026-05-23)
# ──────────────────────────────────────────────────────────────────────────────

# Each entry: (leader_key, pretty_name, audio_filename, video_base, has_blue_variant, category)
# video_base = None means no intro video exists (audio-only)
# has_blue_variant means a `<video_base>Blue.mp4` file exists for Red/Blue version
_TABLE = [
    # (leader_key,    pretty_name,    audio_filename,    video_base, has_blue, category)
    ('BROCK',         'Brock',        'Brock.mp3',       'Brock',    False, 'gym_leader'),
    ('MISTY',         'Misty',        'Misty.mp3',       'Misty',    False, 'gym_leader'),
    ('LT.SURGE',      'Lt. Surge',    'Surge.mp3',       'Surge',    True,  'gym_leader'),
    ('ERIKA',         'Erika',        'Erika.mp3',       'Erika',    True,  'gym_leader'),
    ('KOGA',          'Koga',         'Koga.mp3',        'Koga',     True,  'gym_leader'),
    ('SABRINA',       'Sabrina',      'Sabrina.mp3',     'Sabrina',  True,  'gym_leader'),
    ('BLAINE',        'Blaine',       'Blaine.mp3',      'Blaine',   True,  'gym_leader'),

    # Giovanni 1/2 are NON-gym encounters with special audio, no intro video.
    # Giovanni 3 is the gym leader battle, with full intro + audio.
    ('GIOVANNI_1',    'Giovanni (R1)', 'Giovanni 1.mp3',   None,      False, 'rocket_special'),
    ('GIOVANNI_2',    'Giovanni (R2)', 'Giovanni 2.mp3',   None,      False, 'rocket_special'),
    ('GIOVANNI_GYM',  'Giovanni',     'Giovanni 3.mp3',  'Giovanni', True,  'gym_leader'),

    # Elite 4 + Champion
    ('LORELEI',       'Lorelei',      'Lorelei.mp3',     'Lorelei',  False, 'elite_4'),
    ('BRUNO',         'Bruno',        'Bruno.mp3',       'Bruno',    False, 'elite_4'),
    ('AGATHA',        'Agatha',       'Agatha.mp3',      'Agatha',   False, 'elite_4'),
    ('LANCE',         'Lance',        'Lance.mp3',       'Lance',    False, 'elite_4'),

    # Rivals — Rival (1/2) early-game audio only; Rival3 = champion with full intro
    ('RIVAL',         'Rival',        'Rival.mp3',       None,       False, 'rival'),
    ('RIVAL3',        'Champion',     'Champion.mp3',    'Champion', True,  'champion'),
]

_LEADER_KEYS = {e[0]: e for e in _TABLE}


# Asset folder layout under RBYNewLayout repo root
_INTRO_VIDEO_SUBDIR = Path('gymLeaders') / 'LeaderIntros'
_INTRO_AUDIO_SUBDIR = Path('gymLeaders') / 'LeaderIntros' / 'audio'


def asset_dirs(rby_root: Path) -> tuple[Path, Path]:
    """Return (video_dir, audio_dir) for a given RBYNewLayout repo root."""
    return (rby_root / _INTRO_VIDEO_SUBDIR, rby_root / _INTRO_AUDIO_SUBDIR)


def resolve_video_filename(video_base: str | None, version: Version,
                           video_dir: Path) -> Optional[str]:
    """Pick the correct video filename for a leader + version.

    Rules:
    - If video_base is None: no video exists for this leader.
    - If version == 'red_blue' AND `<video_base>Blue.mp4` exists: use the Blue variant.
    - Else: use `<video_base>.mp4`.
    - If `<video_base>.mp4` doesn't exist either: return None (asset missing).
    """
    if video_base is None:
        return None

    if version == 'red_blue':
        blue = f'{video_base}Blue.mp4'
        if (video_dir / blue).exists():
            return blue

    base = f'{video_base}.mp4'
    if (video_dir / base).exists():
        return base
    return None


def resolve_leader(leader_key: str, version: Version,
                   rby_root: Path) -> Optional[LeaderAssets]:
    """Resolve a session-log leader_key to its on-disk assets.

    Returns None if leader_key is unknown to the table. Returns LeaderAssets
    with possibly missing video (when video doesn't apply or files moved).
    """
    entry = _LEADER_KEYS.get(leader_key)
    if entry is None:
        return None

    _, pretty, audio_filename, video_base, _, category = entry
    video_dir, audio_dir = asset_dirs(rby_root)

    audio_path = audio_dir / audio_filename
    video_filename = resolve_video_filename(video_base, version, video_dir)
    video_path = (video_dir / video_filename) if video_filename else None

    return LeaderAssets(
        leader_key=leader_key,
        pretty_name=pretty,
        audio_filename=audio_filename,
        audio_path=audio_path,
        intro_video_filename=video_filename,
        intro_video_path=video_path,
        has_intro_video=video_path is not None and video_path.exists(),
        category=category,
    )


def detect_version_from_meta(meta_json: dict) -> Optional[Version]:
    """Parse the `version` field from a session log meta.json.

    Mapping:
      "Yellow"           -> 'yellow'
      "Red"              -> 'red_blue'
      "Blue"             -> 'red_blue'
      "Red and Blue"     -> 'red_blue'
      anything else      -> None (caller should require --version explicit)
    """
    v = (meta_json.get('version') or '').strip().lower()
    if not v:
        return None
    if v == 'yellow':
        return 'yellow'
    if 'red' in v or 'blue' in v:
        return 'red_blue'
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Repeat-leader handling (first vs subsequent appearance)
# ──────────────────────────────────────────────────────────────────────────────

def first_appearance_map(battle_sequence: list[str]) -> dict[int, bool]:
    """For a chronological list of leader_keys, return {index: is_first}.

    First appearance per leader_key gets True. Subsequent appearances get False.
    Note: GIOVANNI_1/_2/_GYM are distinct keys, so Giovanni 1, 2, and 3 are
    each first-appearances for their own keys (not a shared count).

    Example:
        ['RIVAL', 'BROCK', 'MISTY', 'RIVAL', 'BROCK', 'RIVAL3']
        -> {0: True (RIVAL), 1: True (BROCK), 2: True (MISTY),
            3: False (RIVAL re-fight), 4: False (BROCK re-fight),
            5: True (RIVAL3 = different key)}
    """
    seen: set[str] = set()
    out: dict[int, bool] = {}
    for i, key in enumerate(battle_sequence):
        is_first = key not in seen
        out[i] = is_first
        seen.add(key)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Smoke test (run as `python leader_asset_map.py`)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    rby_root = Path(r'C:\Programming\RBYNewLayout')
    print(f'Resolving against: {rby_root}')
    print()

    # Test every leader in the table for both versions
    print(f'{"leader_key":<14} {"category":<14} {"yellow video":<22} {"red/blue video":<22} {"audio":<22}')
    print('-' * 100)
    for entry in _TABLE:
        key = entry[0]
        for version in ('yellow', 'red_blue'):
            a = resolve_leader(key, version, rby_root)
            if a is None:
                continue
            video_str = (a.intro_video_filename or '—')[:22]
            if version == 'yellow':
                yellow_video = video_str
            else:
                red_blue_video = video_str
        print(f'{key:<14} {a.category:<14} {yellow_video:<22} {red_blue_video:<22} {a.audio_filename:<22}')

    # Test first_appearance_map
    print()
    print('first_appearance_map test:')
    seq = ['RIVAL', 'BROCK', 'MISTY', 'RIVAL', 'BROCK', 'RIVAL3']
    fmap = first_appearance_map(seq)
    for i, k in enumerate(seq):
        marker = '*FIRST*' if fmap[i] else 'repeat '
        print(f'  [{i}] {k:<8} {marker}')
