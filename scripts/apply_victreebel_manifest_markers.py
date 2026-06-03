from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


def coalesced_markers(manifest: dict) -> list[dict]:
    by_frame: dict[int, list[dict]] = {}
    for marker in manifest.get("markers", []):
        by_frame.setdefault(int(marker["combined_frame"]), []).append(marker)

    out = []
    for frame, group in sorted(by_frame.items()):
        labels = []
        notes = []
        for marker in group:
            label = marker.get("label") or ""
            if label and label not in labels:
                labels.append(label)
            note = marker.get("note") or marker.get("category") or ""
            if note and note not in notes:
                notes.append(note)
        out.append(
            {
                "frame": frame,
                "name": " / ".join(labels),
                "note": "\n".join(notes),
                "color": group[0].get("color") or "Blue",
                "events": len(group),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--timeline", default="")
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    markers = coalesced_markers(data)
    lock_path = args.manifest.with_name("apply_manifest_markers.lock")
    lock_fd = None
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
    except FileExistsError:
        print(f"lock exists, exiting: {lock_path}", flush=True)
        return 3

    try:
        resolve = dvr.scriptapp("Resolve")
        if not resolve:
            raise RuntimeError("Resolve scripting connection failed")
        project = resolve.GetProjectManager().GetCurrentProject()
        if not project:
            raise RuntimeError("No current Resolve project")
        timeline = project.GetCurrentTimeline()
        if args.timeline:
            for index in range(1, project.GetTimelineCount() + 1):
                candidate = project.GetTimelineByIndex(index)
                if candidate and candidate.GetName() == args.timeline:
                    timeline = candidate
                    project.SetCurrentTimeline(timeline)
                    break
        if not timeline:
            raise RuntimeError("No current timeline")

        print(f"timeline={timeline.GetName()}", flush=True)
        print(f"markers={len(markers)} unique frames from {len(data.get('markers', []))} events", flush=True)

        if args.clear:
            print("clearing existing markers", flush=True)
            timeline.DeleteMarkersByColor("All")

        added = 0
        for index, marker in enumerate(markers, 1):
            ok = timeline.AddMarker(
                int(marker["frame"]),
                marker["color"],
                marker["name"],
                marker["note"],
                1,
                "victreebel_manifest",
            )
            added += 1 if ok else 0
            print(f"{index}/{len(markers)} frame={marker['frame']} ok={bool(ok)} name={marker['name']}", flush=True)

        final_count = len(timeline.GetMarkers() or {})
        print(f"added={added}/{len(markers)} final_marker_count={final_count}", flush=True)
        return 0 if added == len(markers) else 2
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
