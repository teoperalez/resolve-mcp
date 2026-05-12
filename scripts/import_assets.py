"""
Validate and import game-specific assets into a DaVinci Resolve 'assets' bin.

Asset catalog (what assets each game needs) lives in assets/catalog.json within
the project and is committed to git.

Asset manifest (where files actually live on this machine) lives globally at
~/.resolve-mcp/manifest.json and is shared across all Resolve projects on this
machine. Paths are tested each run; invalid entries trigger a re-prompt.

Usage:
    python import_assets.py --game GAME_KEY --check
    python import_assets.py --game GAME_KEY --set-path ASSET_ID "PATH"
    python import_assets.py --game GAME_KEY --do-import [--dry-run]
"""
import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

CATALOG_PATH  = Path('assets/catalog.json')
MANIFEST_DIR  = Path.home() / '.resolve-mcp'
MANIFEST_PATH = MANIFEST_DIR / 'manifest.json'

MEDIA_EXTS = {
    '.mp4', '.mov', '.mxf', '.avi', '.mkv', '.r3d', '.braw',
    '.wav', '.mp3', '.aiff', '.aac', '.flac',
    '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.psd', '.exr',
}


def load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        print(f'ERROR: Catalog not found: {CATALOG_PATH.resolve()}', file=sys.stderr)
        print('       Create assets/catalog.json in your project root.', file=sys.stderr)
        sys.exit(1)
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


def save_manifest(manifest: dict) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                             encoding='utf-8')


def _path_ok(path_str: str | None, asset_type: str) -> bool:
    if not path_str:
        return False
    p = Path(path_str)
    return p.is_dir() if asset_type == 'folder' else p.is_file()


def _collect_files(path_str: str, asset_type: str) -> list[str]:
    p = Path(path_str)
    if asset_type == 'file':
        return [str(p)]
    return sorted(str(f) for f in p.iterdir()
                  if f.is_file() and f.suffix.lower() in MEDIA_EXTS)


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------
def cmd_check(game_key: str, catalog: dict, manifest: dict) -> int:
    if game_key not in catalog:
        out = {
            'status': 'unknown_game',
            'game_key': game_key,
            'message': (f'Game "{game_key}" not found in {CATALOG_PATH}. '
                        'Add an entry there to define the required asset slots.'),
            'missing': [], 'invalid': [], 'valid': [],
        }
        print(json.dumps(out, indent=2))
        return 0

    game_def  = catalog[game_key]
    game_paths = manifest.get(game_key, {})

    missing, invalid, valid = [], [], []
    for asset_id, asset_def in game_def['assets'].items():
        stored = game_paths.get(asset_id)
        if not stored:
            missing.append({
                'id': asset_id,
                'label': asset_def['label'],
                'type': asset_def['type'],
            })
        elif not _path_ok(stored, asset_def['type']):
            invalid.append({
                'id': asset_id,
                'label': asset_def['label'],
                'type': asset_def['type'],
                'stored_path': stored,
            })
        else:
            valid.append({
                'id': asset_id,
                'label': asset_def['label'],
                'type': asset_def['type'],
                'path': stored,
            })

    status = 'ready' if not missing and not invalid else 'needs_paths'
    print(json.dumps({
        'status': status,
        'game_key': game_key,
        'display_name': game_def['display_name'],
        'manifest_path': str(MANIFEST_PATH),
        'missing': missing,
        'invalid': invalid,
        'valid': valid,
    }, indent=2))
    return 0


# ---------------------------------------------------------------------------
# --set-path
# ---------------------------------------------------------------------------
def cmd_set_path(game_key: str, asset_id: str, path: str,
                 catalog: dict, manifest: dict) -> int:
    if game_key not in catalog:
        print(f'ERROR: Game "{game_key}" not in catalog.', file=sys.stderr)
        return 1

    game_def = catalog[game_key]
    if asset_id not in game_def['assets']:
        print(f'ERROR: Asset ID "{asset_id}" not defined for {game_key}.', file=sys.stderr)
        return 1

    asset_def = game_def['assets'][asset_id]
    if not _path_ok(path, asset_def['type']):
        expected = 'directory' if asset_def['type'] == 'folder' else 'file'
        print(f'ERROR: Path is not an accessible {expected}: {path}', file=sys.stderr)
        return 1

    manifest.setdefault(game_key, {})[asset_id] = path
    save_manifest(manifest)
    print(f'Manifest updated ({MANIFEST_PATH}):')
    print(f'  {game_key}.{asset_id} = {path}')
    return 0


# ---------------------------------------------------------------------------
# --do-import
# ---------------------------------------------------------------------------
def cmd_import(game_key: str, catalog: dict, manifest: dict,
               dry_run: bool = False) -> int:
    import DaVinciResolveScript as dvr  # only needed for import

    if game_key not in catalog:
        print(f'ERROR: Game "{game_key}" not in catalog.', file=sys.stderr)
        return 1

    game_def   = catalog[game_key]
    game_paths = manifest.get(game_key, {})

    all_files: list[str] = []
    for asset_id, asset_def in game_def['assets'].items():
        stored = game_paths.get(asset_id)
        if not _path_ok(stored, asset_def['type']):
            print(f'  SKIP  {asset_id}: path missing or inaccessible ({stored!r})')
            continue
        files = _collect_files(stored, asset_def['type'])
        label = asset_def['label']
        print(f'  OK    {asset_id} ({label}): {len(files)} file(s)')
        all_files.extend(files)

    if not all_files:
        print('No files to import — run --check to see what paths are needed.')
        return 1

    if dry_run:
        print(f'\nDRY RUN — would import {len(all_files)} file(s) into "assets" bin:')
        for f in all_files:
            print(f'  {f}')
        return 0

    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1

    project = resolve.GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()
    root    = pool.GetRootFolder()

    assets_bin = None
    for sub in (root.GetSubFolderList() or []):
        if sub.GetName() == 'assets':
            assets_bin = sub
            break
    if assets_bin is None:
        assets_bin = pool.AddSubFolder(root, 'assets')
        print("Created 'assets' bin.")
    else:
        print("Found existing 'assets' bin.")

    pool.SetCurrentFolder(assets_bin)
    imported = pool.ImportMedia(all_files) or []
    print(f'\nImported {len(imported)}/{len(all_files)} files into "assets" bin.')
    return 0 if imported else 1


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game', required=True,
                        help='Game catalog key (e.g. pokemon_crystal)')

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true',
                      help='Validate manifest entries, print JSON report')
    mode.add_argument('--set-path', nargs=2, metavar=('ASSET_ID', 'PATH'),
                      help='Set a manifest path for one asset slot')
    mode.add_argument('--do-import', action='store_true',
                      help='Create/find "assets" bin in Resolve and import files')

    parser.add_argument('--dry-run', action='store_true',
                        help='With --do-import: list files without modifying Resolve')

    args = parser.parse_args()

    catalog  = load_catalog()
    manifest = load_manifest()

    if args.check:
        return cmd_check(args.game, catalog, manifest)
    elif args.set_path:
        return cmd_set_path(args.game, args.set_path[0], args.set_path[1],
                            catalog, manifest)
    elif args.do_import:
        return cmd_import(args.game, catalog, manifest, dry_run=args.dry_run)

    return 0


if __name__ == '__main__':
    sys.exit(main())
