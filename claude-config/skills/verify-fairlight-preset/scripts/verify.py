"""Verify the Fairlight mixer preset is applied to the current Resolve timeline.

Returns exit code 0 on APPLIED_AND_SAVED or MISSING_NOW_APPLIED,
1 on APPLIED_BUT_UNSAVED (warning), 2 on MISSING_CANNOT_APPLY (hard fail).

Detection rule (all 3 must pass for "applied"):
  - A1 track name matches regex `(?i)dialogue`
  - A2 track name matches regex `(?i)music`
  - A2 GetIsTrackLocked('audio', 2) returns True
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Find resolve-mcp scripts dir for apply_fairlight_preset.py invocation
RESOLVE_MCP_SCRIPTS = Path(r'C:\Programming\resolve-mcp\scripts')


def setup_resolve():
    """Bootstrap DaVinciResolveScript import path."""
    api_base = r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting'
    modules_dir = os.path.join(api_base, 'Modules')
    lib_path = r'C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll'
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)
    os.environ.setdefault('RESOLVE_SCRIPT_API', api_base)
    os.environ.setdefault('RESOLVE_SCRIPT_LIB',
                          lib_path)
    if sys.platform.startswith('win'):
        pyhome = sys.base_prefix or sys.prefix
        if pyhome and os.path.isdir(pyhome):
            os.environ.setdefault('PYTHON3HOME', pyhome)
        for dll_dir in (
            os.path.dirname(lib_path),
            pyhome,
            os.path.join(pyhome, 'DLLs') if pyhome else '',
            sys.prefix,
            os.path.join(sys.prefix, 'DLLs'),
        ):
            if not dll_dir or not os.path.isdir(dll_dir):
                continue
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(dll_dir)
                except OSError:
                    pass
            current_path = os.environ.get('PATH', '')
            norm_dll = os.path.normcase(os.path.abspath(dll_dir))
            existing = {
                os.path.normcase(os.path.abspath(entry))
                for entry in current_path.split(os.pathsep)
                if entry
            }
            if norm_dll not in existing:
                os.environ['PATH'] = dll_dir + (os.pathsep + current_path if current_path else '')


def detect_signature(tl, verbose: bool = False) -> tuple[bool, dict]:
    """Check if Fairlight preset signature is present on timeline.

    Returns (all_pass, details_dict).
    """
    if tl.GetTrackCount('audio') < 2:
        return False, {'error': f'Timeline has only {tl.GetTrackCount("audio")} audio tracks; need ≥2'}

    a1_name = tl.GetTrackName('audio', 1) or ''
    a2_name = tl.GetTrackName('audio', 2) or ''
    a2_locked = tl.GetIsTrackLocked('audio', 2)

    a1_pass = bool(re.search(r'dialogue', a1_name, re.I))
    a2_name_pass = bool(re.search(r'music', a2_name, re.I))
    a2_locked_pass = bool(a2_locked)

    all_pass = a1_pass and a2_name_pass and a2_locked_pass

    details = {
        'a1_name': a1_name,
        'a1_match_dialogue': a1_pass,
        'a2_name': a2_name,
        'a2_match_music': a2_name_pass,
        'a2_locked': a2_locked,
        'all_pass': all_pass,
        'track_count': tl.GetTrackCount('audio'),
    }

    if verbose:
        print(f'  A1 name: {a1_name!r}  {"OK" if a1_pass else "FAIL expected /dialogue/i"}')
        print(f'  A2 name: {a2_name!r}  {"OK" if a2_name_pass else "FAIL expected /music/i"}')
        print(f'  A2 locked: {a2_locked}  {"OK" if a2_locked_pass else "FAIL expected True"}')
        print(f'  Audio track count: {details["track_count"]}')

    return all_pass, details


def apply_preset(preset: str, preset_type: str, timeline_name: str | None,
                 verbose: bool = False) -> tuple[bool, str]:
    """Invoke resolve-mcp/scripts/apply_fairlight_preset.py.

    Returns (success, output).
    """
    script = RESOLVE_MCP_SCRIPTS / 'apply_fairlight_preset.py'
    if not script.exists():
        return False, f'apply_fairlight_preset.py not found at {script}'

    cmd = [
        sys.executable, str(script),
        '--preset', preset,
        '--type', preset_type,
    ]
    if timeline_name:
        cmd.extend(['--timeline', timeline_name])

    if verbose:
        print(f'  Running: {" ".join(cmd)}')

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return False, f'apply script exit {r.returncode}: {r.stderr}'

    # Look for 'Result: True' in stdout
    if 'Result: True' in r.stdout:
        return True, r.stdout
    return False, f'apply script did not report Result: True. stdout:\n{r.stdout}'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--preset', default='Standard Gameplay youtube',
                    help='Preset name to verify/apply (default: "Standard Gameplay youtube")')
    ap.add_argument('--type', default='CONSOLE_FLEXI',
                    help='Preset type subfolder (default: CONSOLE_FLEXI)')
    ap.add_argument('--timeline', default=None,
                    help='Switch to this timeline first (default: current)')
    ap.add_argument('--no-apply', dest='apply_if_missing', action='store_false',
                    default=True,
                    help='Verify only; do not apply if missing')
    ap.add_argument('--no-save', dest='save_after_apply', action='store_false',
                    default=True,
                    help='Skip the pm.SaveProject() step after apply')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='Print track-by-track detection results')
    args = ap.parse_args()

    setup_resolve()
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Cannot connect to Resolve. Is Resolve running with external scripting enabled?',
              file=sys.stderr)
        return 2

    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if proj is None:
        print('ERROR: No current project.', file=sys.stderr)
        return 2

    # Switch timeline if requested
    if args.timeline:
        for i in range(1, proj.GetTimelineCount() + 1):
            t = proj.GetTimelineByIndex(i)
            if t and t.GetName() == args.timeline:
                proj.SetCurrentTimeline(t)
                break
        else:
            print(f'ERROR: Timeline {args.timeline!r} not found.', file=sys.stderr)
            return 2

    tl = proj.GetCurrentTimeline()
    if tl is None:
        print('ERROR: No current timeline.', file=sys.stderr)
        return 2

    print(f'=== Fairlight Preset Verification ===')
    print(f'Timeline: {tl.GetName()!r}')
    print(f'Preset: {args.preset!r}')

    # Step 2 — detect
    all_pass, details = detect_signature(tl, verbose=args.verbose)

    if all_pass:
        # Step 3a — preset already applied. Save is a no-op in this case (no changes),
        # so SaveProject() returning False just means "nothing to save", which is FINE.
        # We don't make a noisy warning on no-op saves.
        if args.save_after_apply:
            saved = pm.SaveProject()
            note = 'project saved' if saved else 'no changes to save (already persisted)'
            print(f'Result: APPLIED_AND_SAVED  ({note})')
        else:
            print(f'Result: APPLIED  (--no-save; durability not verified)')
        return 0

    # Step 3b — preset is missing
    if not args.apply_if_missing:
        print(f'Result: MISSING  (preset not detected; --no-apply set, not auto-applying)',
              file=sys.stderr)
        return 2

    print(f'Preset NOT detected. Applying...')
    ok, output = apply_preset(args.preset, args.type, tl.GetName(), verbose=args.verbose)
    if not ok:
        print(f'Result: MISSING_CANNOT_APPLY', file=sys.stderr)
        print(output, file=sys.stderr)
        return 2

    # Re-detect to confirm
    all_pass, details = detect_signature(tl, verbose=args.verbose)
    if not all_pass:
        print(f'Result: MISSING_CANNOT_APPLY  (apply reported success but signature still missing)',
              file=sys.stderr)
        print(f'  Detection details: {details}', file=sys.stderr)
        return 2

    # Save — here SaveProject MUST return True because apply just made changes.
    # If False, the apply isn't durable.
    if args.save_after_apply:
        saved = pm.SaveProject()
        if saved:
            print(f'Result: MISSING_NOW_APPLIED  (applied + saved successfully)')
            return 0
        else:
            print(f'Result: APPLIED_BUT_UNSAVED  (applied but SaveProject failed despite changes)',
                  file=sys.stderr)
            print(f'  WARNING: preset is on timeline but a Resolve crash before next auto-save loses it.',
                  file=sys.stderr)
            return 1

    print(f'Result: MISSING_NOW_APPLIED  (--no-save; durability not verified)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
