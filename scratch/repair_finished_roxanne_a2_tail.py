from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


ROOT = Path(r"F:\Roxanne Minimum\CODEx\full_track_review\narrative_audit")
FINISHED_DIR = ROOT / "finished_timeline"
BUILD_REPORT = FINISHED_DIR / "finished_timeline_build_report.json"
VERIFY_REPORT = FINISHED_DIR / "finished_timeline_verify_report.json"
REPAIR_REPORT = FINISHED_DIR / "finished_timeline_a2_tail_repair_report.json"
TRIM_DIR = FINISHED_DIR / "bgm_trims"
BUILDER_PATH = Path(__file__).with_name("build_finished_roxanne_timeline.py")


def load_builder():
    spec = importlib.util.spec_from_file_location("roxanne_finished_builder", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["roxanne_finished_builder"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def find_timeline(project, name: str):
    for index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == name:
            return timeline
    return None


def item_path(item) -> Path:
    mpi = item.GetMediaPoolItem()
    props = mpi.GetClipProperty() if mpi else {}
    raw = props.get("File Path") or ""
    if not raw:
        raise RuntimeError(f"Could not read media path for {item.GetName()!r}")
    return Path(raw)


def main() -> int:
    builder = load_builder()
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    timeline_name = build["output_timeline"]
    final_end = int(build["final_end_frame"])

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve not connected")
    project = resolve.GetProjectManager().GetCurrentProject()
    pool = project.GetMediaPool()
    timeline = find_timeline(project, timeline_name)
    if not timeline:
        raise RuntimeError(f"Could not find timeline {timeline_name!r}")
    project.SetCurrentTimeline(timeline)

    a2_items = sorted(timeline.GetItemListInTrack("audio", 2) or [], key=lambda item: item.GetStart())
    overhanging = [item for item in a2_items if int(item.GetStart()) < final_end < int(item.GetStart() + item.GetDuration())]
    if len(overhanging) != 1:
        raise RuntimeError(f"Expected exactly one A2 clip crossing final_end={final_end}, found {len(overhanging)}")

    original = overhanging[0]
    original_name = original.GetName()
    original_start = int(original.GetStart())
    original_end = int(original.GetStart() + original.GetDuration())
    original_path = item_path(original)
    start = original_start
    needed_frames = final_end - start
    if needed_frames <= 0:
        raise RuntimeError("Final A2 tail has no positive duration")
    needed_sec = needed_frames / 60.0
    TRIM_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = TRIM_DIR / f"{original_path.stem}_loop_tail_{start}_{final_end}_{needed_frames}f.wav"
    if not trimmed.exists() or trimmed.stat().st_size == 0:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-stream_loop",
                "-1",
                "-i",
                str(original_path),
                "-t",
                f"{needed_sec:.9f}",
                "-ac",
                "2",
                "-ar",
                "48000",
                str(trimmed),
            ],
            check=True,
        )

    imported = pool.ImportMedia([str(trimmed)]) or []
    if not imported:
        # It may already be in the media pool.
        imported = [
            item for item in (pool.GetCurrentFolder().GetClipList() or [])
            if (item.GetClipProperty() or {}).get("File Path") == str(trimmed)
        ]
    if not imported:
        raise RuntimeError(f"Could not import trimmed BGM tail: {trimmed}")
    trimmed_item = imported[0]

    delete_ok = timeline.DeleteClips([original], False)
    if not delete_ok:
        raise RuntimeError("DeleteClips failed for overhanging A2 tail")
    placed = pool.AppendToTimeline(
        [
            {
                "mediaPoolItem": trimmed_item,
                "recordFrame": start,
                "trackIndex": 2,
                "mediaType": 2,
            }
        ]
    ) or []
    if len(placed) != 1:
        raise RuntimeError(f"Trimmed BGM tail placement failed: placed {len(placed)}")

    plan = json.loads(builder.PLAN_PATH.read_text(encoding="utf-8"))
    features_data = json.loads(builder.FEATURES_PATH.read_text(encoding="utf-8"))
    visual_markers = json.loads(builder.VISUAL_MARKERS_PATH.read_text(encoding="utf-8"))
    features = {int(row["clip_index"]): row for row in features_data["features"]}
    plan["timeline_end_frame"] = int(build["source_end_frame"])
    hold_plans = builder.build_hold_plans(plan, features, visual_markers)
    source_timeline = find_timeline(project, builder.SOURCE_TIMELINE_NAME)
    if not source_timeline:
        raise RuntimeError(f"Could not find source timeline {builder.SOURCE_TIMELINE_NAME!r}")
    v1_specs = builder.collect_track_specs(source_timeline, "video", 1, 1)
    v1_segments, _hold_report = builder.build_v1_hold_spine(v1_specs, hold_plans, 60.0)
    verify = builder.verify_timeline(
        timeline,
        plan,
        hold_plans,
        v1_segments,
        int(build["intro_frames"]),
        int(build["source_end_frame"]),
        final_end,
        build["markers"],
    )
    VERIFY_REPORT.write_text(json.dumps(verify, indent=2), encoding="utf-8")
    save_result = bool(resolve.GetProjectManager().SaveProject())

    report = {
        "timeline": timeline_name,
        "original_clip": original_name,
        "original_path": str(original_path),
        "original_start": original_start,
        "original_end": original_end,
        "final_end": final_end,
        "needed_frames": needed_frames,
        "trimmed_path": str(trimmed),
        "delete_ok": bool(delete_ok),
        "placed": len(placed),
        "verify_ok_after": verify["ok"],
        "verify_failures_after": verify["failures"],
        "overhanging_items_after": verify.get("overhanging_items", []),
        "project_save_result": save_result,
    }
    REPAIR_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if verify["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
