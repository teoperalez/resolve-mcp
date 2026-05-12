"""
Validate and import game-specific and shared assets into DaVinci Resolve bins.

Asset catalog (what assets each game needs, plus shared folder definitions) lives
in assets/catalog.json within the project and is committed to git.

Asset manifest (where files actually live on this machine) lives globally at
~/.resolve-mcp/manifest.json and is shared across all Resolve projects on this
machine. Paths are tested each run; invalid entries trigger a re-prompt.

Usage (game-specific):
    python import_assets.py --game GAME_KEY --check
    python import_assets.py --game GAME_KEY --set-path ASSET_ID "PATH"
    python import_assets.py --game GAME_KEY --do-import [--dry-run]

Usage (shared assets — folders imported into sub-bins under "assets"):
    python import_assets.py --check-shared
    python import_assets.py --set-shared-path ASSET_ID "PATH"
    python import_assets.py --import-shared [--dry-run]
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
SHARED_KEY    = 'shared'

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


def _collect_files_recursive(path_str: str) -> list[str]:
    """Collect all media files under path_str, including subdirectories."""
    p = Path(path_str)
    return sorted(str(f) for f in p.rglob('*')
                  if f.is_file() and f.suffix.lower() in MEDIA_EXTS)


def _find_or_create_subfolder(pool, parent, name: str):
    """Return (folder, was_created). Looks for existing subfolder by name."""
    for sub in (parent.GetSubFolderList() or []):
        if sub.GetName() == name:
            return sub, False
    return pool.AddSubFolder(parent, name), True


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

    game_def   = catalog[game_key]
    group_key  = game_def.get('asset_group', game_key)
    game_paths = manifest.get(group_key, {})

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
        'asset_group': group_key,
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

    group_key = game_def.get('asset_group', game_key)
    manifest.setdefault(group_key, {})[asset_id] = path
    save_manifest(manifest)
    print(f'Manifest updated ({MANIFEST_PATH}):')
    print(f'  {group_key}.{asset_id} = {path}')
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
    group_key  = game_def.get('asset_group', game_key)
    game_paths = manifest.get(group_key, {})

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

    assets_bin, created = _find_or_create_subfolder(pool, root, 'assets')
    print(f"{'Created' if created else 'Found'} 'assets' bin.")

    pool.SetCurrentFolder(assets_bin)
    imported = pool.ImportMedia(all_files) or []
    print(f'\nImported {len(imported)}/{len(all_files)} files into "assets" bin.')
    return 0 if imported else 1


# ---------------------------------------------------------------------------
# --check-shared
# ---------------------------------------------------------------------------
def cmd_check_shared(catalog: dict, manifest: dict) -> int:
    shared_defs = catalog.get('shared_assets', [])
    if not shared_defs:
        print(json.dumps({
            'status': 'no_shared_assets',
            'message': 'No shared_assets defined in catalog.json.',
            'missing': [], 'invalid': [], 'valid': [],
        }, indent=2))
        return 0

    shared_paths = manifest.get(SHARED_KEY, {})
    missing, invalid, valid = [], [], []
    for defn in shared_defs:
        aid    = defn['id']
        stored = shared_paths.get(aid)
        entry  = {'id': aid, 'label': defn['label'], 'bin_name': defn['bin_name']}
        if not stored:
            missing.append(entry)
        elif not Path(stored).is_dir():
            invalid.append({**entry, 'stored_path': stored})
        else:
            valid.append({**entry, 'path': stored})

    status = 'ready' if not missing and not invalid else 'needs_paths'
    print(json.dumps({
        'status': status,
        'manifest_path': str(MANIFEST_PATH),
        'missing': missing,
        'invalid': invalid,
        'valid': valid,
    }, indent=2))
    return 0


# ---------------------------------------------------------------------------
# --set-shared-path
# ---------------------------------------------------------------------------
def cmd_set_shared_path(asset_id: str, path: str,
                        catalog: dict, manifest: dict) -> int:
    shared_defs = catalog.get('shared_assets', [])
    defn = next((d for d in shared_defs if d['id'] == asset_id), None)
    if defn is None:
        known = [d['id'] for d in shared_defs]
        print(f'ERROR: Shared asset ID "{asset_id}" not in catalog. '
              f'Known IDs: {known}', file=sys.stderr)
        return 1

    if not Path(path).is_dir():
        print(f'ERROR: Path is not an accessible directory: {path}', file=sys.stderr)
        return 1

    manifest.setdefault(SHARED_KEY, {})[asset_id] = path
    save_manifest(manifest)
    print(f'Manifest updated ({MANIFEST_PATH}):')
    print(f'  shared.{asset_id} = {path}')
    return 0


# ---------------------------------------------------------------------------
# --import-shared
# ---------------------------------------------------------------------------
def cmd_import_shared(catalog: dict, manifest: dict, dry_run: bool = False,
                      only: list[str] | None = None) -> int:
    import DaVinciResolveScript as dvr

    shared_defs = catalog.get('shared_assets', [])
    if not shared_defs:
        print('No shared_assets defined in catalog.json.')
        return 1

    shared_paths = manifest.get(SHARED_KEY, {})
    if only:
        shared_defs = [d for d in shared_defs if d['id'] in only]

    bins_to_import: list[tuple[str, list[str]]] = []  # (bin_name, files)
    for defn in shared_defs:
        aid    = defn['id']
        stored = shared_paths.get(aid)
        if not stored or not Path(stored).is_dir():
            print(f'  SKIP  {aid}: path missing or inaccessible ({stored!r})')
            continue
        files = _collect_files_recursive(stored)
        print(f'  OK    {aid} ({defn["label"]}): {len(files)} file(s) → bin "{defn["bin_name"]}"')
        bins_to_import.append((defn['bin_name'], files))

    if not bins_to_import:
        print('No shared assets to import — run --check-shared to see what paths are needed.')
        return 1

    total_files = sum(len(f) for _, f in bins_to_import)

    if dry_run:
        print(f'\nDRY RUN — would import {total_files} file(s) into "assets" sub-bins:')
        for bin_name, files in bins_to_import:
            print(f'\n  [{bin_name}] ({len(files)} files):')
            for f in files:
                print(f'    {f}')
        return 0

    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1

    project = resolve.GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()
    root    = pool.GetRootFolder()

    assets_bin, created = _find_or_create_subfolder(pool, root, 'assets')
    print(f"{'Created' if created else 'Found'} 'assets' bin.")

    total_imported = 0
    for bin_name, files in bins_to_import:
        sub_bin, created = _find_or_create_subfolder(pool, assets_bin, bin_name)
        print(f"  {'Created' if created else 'Found'} '{bin_name}' sub-bin.")
        pool.SetCurrentFolder(sub_bin)
        imported = pool.ImportMedia(files) or []
        print(f'  Imported {len(imported)}/{len(files)} files.')
        total_imported += len(imported)

    print(f'\nTotal: {total_imported}/{total_files} shared asset files imported.')
    return 0 if total_imported else 1


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game',
                        help='Game catalog key (e.g. pokemon_crystal) — required for game-specific commands')

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true',
                      help='Validate game manifest entries, print JSON report')
    mode.add_argument('--set-path', nargs=2, metavar=('ASSET_ID', 'PATH'),
                      help='Set a manifest path for one game asset slot')
    mode.add_argument('--do-import', action='store_true',
                      help='Create/find "assets" bin in Resolve and import game files')
    mode.add_argument('--check-shared', action='store_true',
                      help='Validate shared asset folder paths, print JSON report')
    mode.add_argument('--set-shared-path', nargs=2, metavar=('ASSET_ID', 'PATH'),
                      help='Set a manifest path for one shared asset folder')
    mode.add_argument('--import-shared', action='store_true',
                      help='Import shared assets into their own sub-bins under "assets"')

    parser.add_argument('--dry-run', action='store_true',
                        help='With --do-import / --import-shared: list files without modifying Resolve')
    parser.add_argument('--only', nargs='+', metavar='ASSET_ID',
                        help='With --import-shared: limit to specific asset IDs (e.g. --only gymleaders)')

    args = parser.parse_args()

    # Game key is required for game-specific commands
    game_commands = (args.check, args.set_path, args.do_import)
    if any(game_commands) and not args.game:
        parser.error('--game is required for --check, --set-path, and --do-import')

    catalog  = load_catalog()
    manifest = load_manifest()

    if args.check:
        return cmd_check(args.game, catalog, manifest)
    elif args.set_path:
        return cmd_set_path(args.game, args.set_path[0], args.set_path[1],
                            catalog, manifest)
    elif args.do_import:
        return cmd_import(args.game, catalog, manifest, dry_run=args.dry_run)
    elif args.check_shared:
        return cmd_check_shared(catalog, manifest)
    elif args.set_shared_path:
        return cmd_set_shared_path(args.set_shared_path[0], args.set_shared_path[1],
                                   catalog, manifest)
    elif args.import_shared:
        return cmd_import_shared(catalog, manifest, dry_run=args.dry_run, only=args.only)

    return 0


if __name__ == '__main__':
    sys.exit(main())
