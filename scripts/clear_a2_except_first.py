"""Delete all clips on A2 (or --track-index N) EXCEPT the first one.

Use this to clear the chained BGM after Dual Screen Lovelife so we can re-run
the placement scripts cleanly."""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--track-index', type=int, default=2)
    args = ap.parse_args()

    import DaVinciResolveScript as dvr
    project = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject()
    tl      = project.GetCurrentTimeline()
    fps     = float(project.GetSetting('timelineFrameRate'))
    clips   = sorted(tl.GetItemListInTrack('audio', args.track_index) or [],
                     key=lambda c: c.GetStart())
    print(f'A{args.track_index}: {len(clips)} clips total')
    if len(clips) <= 1:
        print('Nothing to delete.')
        return 0

    keep = clips[0]
    to_delete = clips[1:]
    print(f'Keeping: "{keep.GetName()}" '
          f'start={keep.GetStart()}  dur={keep.GetDuration()}')
    print(f'Deleting {len(to_delete)} clips:')
    for c in to_delete:
        print(f'  {c.GetName()!r}  start={c.GetStart()}')
    ok = tl.DeleteClips(to_delete)
    print(f'DeleteClips returned: {ok}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
