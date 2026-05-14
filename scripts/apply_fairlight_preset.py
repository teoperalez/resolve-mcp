r"""
Install a repo-bundled Fairlight preset into the local DaVinci Resolve
Presets folder (if not already there), then apply it to the target timeline
via Project.ApplyFairlightPresetToCurrentTimeline().

The preset travels with the repo at:
    assets/fairlight-presets/<TYPE>/<Name>.dat

Resolve expects presets at platform-specific paths:
    Windows:   %APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences\Fairlight\Presets\<TYPE>\<Name>.dat
    macOS:     ~/Library/Preferences/Blackmagic Design/DaVinci Resolve/Fairlight/Presets/<TYPE>/<Name>.dat
    Linux:     ~/.config/Blackmagic Design/DaVinci Resolve/Fairlight/Presets/<TYPE>/<Name>.dat

The script copies the repo file into the target dir on first run; later runs
hit a no-op unless --force-install is given (or the host file differs in size).

After install, switches to --timeline (or stays on the current one) and calls
ApplyFairlightPresetToCurrentTimeline(preset_name). On success, prints the
manual Normalize Audio walkthrough.

Usage:
    python apply_fairlight_preset.py
    python apply_fairlight_preset.py --preset "Standard Gameplay youtube"
    python apply_fairlight_preset.py --timeline "Brock Red Blue versus Crystl (edit) 3"
    python apply_fairlight_preset.py --force-install   # overwrite host file
    python apply_fairlight_preset.py --install-only    # don't apply, just install
"""
import sys
import os
import shutil
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

# Anchor repo paths to the script's own directory so the script works regardless
# of where the user runs it from (main tree, worktree, anywhere else).
SCRIPTS_DIR          = Path(__file__).resolve().parent
REPO_ROOT            = SCRIPTS_DIR.parent
REPO_PRESETS_DIR     = REPO_ROOT / 'assets' / 'fairlight-presets'
DEFAULT_PRESET_NAME  = 'Standard Gameplay youtube'
DEFAULT_PRESET_TYPE  = 'CONSOLE_FLEXI'   # Fairlight Configuration Preset


def resolve_presets_root() -> Path:
    """Platform-specific Fairlight presets directory."""
    if sys.platform.startswith('win'):
        base = Path(os.environ.get('APPDATA', '')) or Path.home() / 'AppData' / 'Roaming'
        return base / 'Blackmagic Design' / 'DaVinci Resolve' / 'Preferences' / 'Fairlight' / 'Presets'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Preferences' / 'Blackmagic Design' / 'DaVinci Resolve' / 'Fairlight' / 'Presets'
    return Path.home() / '.config' / 'Blackmagic Design' / 'DaVinci Resolve' / 'Fairlight' / 'Presets'


def install_preset(repo_path: Path, host_path: Path, force: bool) -> str:
    """Copy repo_path → host_path if missing or different. Returns a status word."""
    if not repo_path.exists():
        raise FileNotFoundError(f'Repo preset not found: {repo_path}')
    host_path.parent.mkdir(parents=True, exist_ok=True)
    if host_path.exists() and not force:
        if host_path.stat().st_size == repo_path.stat().st_size:
            return 'already-installed'
        return 'host-differs-keeping'  # don't overwrite by default
    shutil.copy2(repo_path, host_path)
    return 'installed' if not host_path.exists() else 'overwritten'


def find_timeline(project, name: str):
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t and t.GetName() == name:
            return t
    return None


def print_normalize_walkthrough():
    print("""
─────────────────────────────────────────────────────────────────────────
Next step: Normalize Audio (Sample Peak -9.0 dB, per-track independently)

The Resolve scripting API does NOT expose NormalizeAudio. Do this in the UI:

  1. Edit page (or Fairlight page) — select all clips on the track:
       click first clip → Ctrl+Shift+End to extend to the end of the track.
  2. Right-click any selected clip → 'Normalize Audio Levels…'
  3. Set:
       Normalization Mode → Sample Peak Program
       Target Level       → -9.0 dBFS
       Set Level          → Relative
       Reference          → Independently (each clip's own peak)
  4. Click Normalize.
  5. Repeat for every audio track that needs leveling.
─────────────────────────────────────────────────────────────────────────
""".rstrip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--preset', default=DEFAULT_PRESET_NAME,
                    help=f'Preset name (without .dat). Default: "{DEFAULT_PRESET_NAME}"')
    ap.add_argument('--type', default=DEFAULT_PRESET_TYPE,
                    help=f'Preset type subfolder. Default: "{DEFAULT_PRESET_TYPE}"')
    ap.add_argument('--timeline', default=None,
                    help='Switch to this timeline before applying (default: current)')
    ap.add_argument('--install-only', action='store_true',
                    help='Install the preset file but skip the apply step')
    ap.add_argument('--force-install', action='store_true',
                    help='Overwrite host preset even if it already exists')
    args = ap.parse_args()

    repo_path = REPO_PRESETS_DIR / args.type / f'{args.preset}.dat'
    host_root = resolve_presets_root()
    host_path = host_root / args.type / f'{args.preset}.dat'

    print(f'Preset: {args.preset!r}  (type: {args.type})')
    print(f'  repo: {repo_path}')
    print(f'  host: {host_path}')

    # 1) Install the preset file into Resolve's Fairlight Presets dir
    try:
        status = install_preset(repo_path, host_path, force=args.force_install)
    except FileNotFoundError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1
    print(f'  install: {status}')

    if args.install_only:
        return 0

    # 2) Apply via Resolve API
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1
    project = resolve.GetProjectManager().GetCurrentProject()

    if args.timeline:
        target = find_timeline(project, args.timeline)
        if target is None:
            print(f'ERROR: Timeline {args.timeline!r} not found in project.',
                  file=sys.stderr)
            return 1
        project.SetCurrentTimeline(target)

    cur = project.GetCurrentTimeline()
    if cur is None:
        print('ERROR: No current timeline.', file=sys.stderr)
        return 1
    print(f'Target timeline: {cur.GetName()!r}')

    print(f'Calling ApplyFairlightPresetToCurrentTimeline({args.preset!r})...')
    try:
        ok = project.ApplyFairlightPresetToCurrentTimeline(args.preset)
    except Exception as e:
        print(f'ERROR: ApplyFairlightPresetToCurrentTimeline raised: {e}',
              file=sys.stderr)
        return 1
    print(f'Result: {ok!r}')
    if not ok:
        print('WARNING: Apply returned a falsy value. The preset may not have '
              'landed. Possible causes: Resolve needs a restart to pick up the '
              'newly installed preset, name mismatch, or the timeline is '
              "incompatible with the preset's track layout.")
        return 1

    print_normalize_walkthrough()
    return 0


if __name__ == '__main__':
    sys.exit(main())
