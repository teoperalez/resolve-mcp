"""
Remove duplicated gameplay-source audio from A2-A5 while preserving intentional
music/audio assets such as intro and outro BGM.

Resolve often re-appends every embedded audio channel from the source MP4 when
building a derived timeline. The edit pipeline only wants the gameplay dialogue
on A1; A2-A5 are reserved for music, battle audio, and outro audio. This script
therefore deletes clips on A2-A5 whose name matches the dominant A1 gameplay
source and leaves every other clip alone.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


def main() -> int:
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("ERROR: Could not connect to DaVinci Resolve.", file=sys.stderr)
        return 1
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("ERROR: No active timeline.", file=sys.stderr)
        return 1

    a1 = timeline.GetItemListInTrack("audio", 1) or []
    if not a1:
        print("A1 is empty; refusing to infer gameplay source.")
        return 1
    gameplay_name = Counter(c.GetName() for c in a1).most_common(1)[0][0]
    print(f"Gameplay audio source inferred from A1: {gameplay_name!r}")

    to_delete = []
    preserved = []
    max_audio = timeline.GetTrackCount("audio")
    for track in range(2, min(max_audio, 5) + 1):
        items = timeline.GetItemListInTrack("audio", track) or []
        for clip in items:
            if clip.GetName() == gameplay_name:
                to_delete.append(clip)
            else:
                preserved.append((track, clip.GetName(), clip.GetStart(), clip.GetEnd()))

    print(f"Duplicate gameplay clips to delete: {len(to_delete)}")
    if preserved:
        print("Preserving intentional A2-A5 clips:")
        for track, name, start, end in preserved[:20]:
            print(f"  A{track}: {name!r} {start}-{end}")
        if len(preserved) > 20:
            print(f"  ...and {len(preserved) - 20} more")

    if not to_delete:
        print("Nothing to delete.")
        return 0
    ok = timeline.DeleteClips(to_delete, False)
    print(f"DeleteClips: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
