"""Build the browser HTML cut-review tool.

Manual review candidates default to KEEP and can be toggled/dragged into cuts.
Automatic cut candidates default to CUT and can be toggled/dragged into restores.

Usage:
    python build_cut_review.py --mic MIC.wav --clips clips.json --out-dir OUTDIR
        [--preload pink_decisions.json] [--categories categories.json]
        [--sr 44100] [--cap 3.0] [--tl-fps 60] [--reuse-assets]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.io import wavfile


ap = argparse.ArgumentParser()
ap.add_argument("--mic", required=True)
ap.add_argument("--clips", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--preload", default="")
ap.add_argument("--categories", default="")
ap.add_argument("--sr", type=int, default=44100)
ap.add_argument("--cap", type=float, default=3.0)
ap.add_argument("--tl-fps", type=float, default=60.0)
ap.add_argument("--reuse-assets", action="store_true")
A = ap.parse_args()

REV = Path(A.out_dir)
AST = REV / "assets"
AST.mkdir(parents=True, exist_ok=True)
SR, CAP = A.sr, A.cap

raw = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", A.mic, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
    capture_output=True,
    check=True,
).stdout
audio = np.frombuffer(raw, np.float32).copy()
data = json.loads(Path(A.clips).read_text(encoding="utf-8"))
clips = data["clips"] if isinstance(data, dict) else data
source_video = data.get("source_video", "") if isinstance(data, dict) else ""
structural_reviews = (
    data.get("structural_restart_reviews") or data.get("structural_cuts") or []
    if isinstance(data, dict)
    else []
)
structural_review_groups = data.get("structural_review_groups", []) if isinstance(data, dict) else []
auto_cut_candidates = data.get("auto_cut_candidates", []) if isinstance(data, dict) else []
manual_review_candidates = data.get("manual_review_candidates", []) if isinstance(data, dict) else []
livestream_review = data.get("livestream_review", {}) if isinstance(data, dict) else {}
N = len(clips)

cats = {}
if A.categories and os.path.exists(A.categories):
    cats = {int(r["i"]): r for r in json.loads(Path(A.categories).read_text(encoding="utf-8")) if "i" in r}

clip_pos_by_i = {int(c.get("i", pos)): pos for pos, c in enumerate(clips)}


def tc(frame: int) -> str:
    seconds = frame / A.tl_fps
    return "%d:%05.2f" % (int(seconds // 60), seconds % 60)


def seg_audio(row: dict, side: str | None = None) -> tuple[np.ndarray, float, float]:
    start = row["left"] / (row.get("fps") or A.tl_fps)
    duration = row["dur"] / A.tl_fps
    chunk = audio[int(start * SR) : int((start + duration) * SR)]
    seg_start, seg_end = start, start + duration
    if side == "before" and len(chunk) > CAP * SR:
        chunk = chunk[-int(CAP * SR) :]
        seg_start = (start + duration) - CAP
    if side == "after" and len(chunk) > CAP * SR:
        chunk = chunk[: int(CAP * SR)]
        seg_end = start + CAP
    return chunk, seg_start, seg_end


def adjacent_groups(positions: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    for pos in sorted(set(positions)):
        if current and pos == current[-1] + 1:
            current.append(pos)
        else:
            if current:
                groups.append(current)
            current = [pos]
    if current:
        groups.append(current)
    return groups


def auto_positions_from_candidates(candidates: list[dict]) -> list[int]:
    positions: list[int] = []
    for candidate in candidates:
        for clip_i in (candidate.get("section_policy") or {}).get("covered_section_indexes", []):
            pos = clip_pos_by_i.get(int(clip_i))
            if pos is not None:
                positions.append(pos)
    return sorted(set(positions))


auto_reason_by_i: dict[int, list[str]] = {}
manual_reason_by_i: dict[int, list[str]] = {}
structural_reason_by_i: dict[int, list[str]] = {}


def candidate_summary(candidate: dict, fallback: str) -> str:
    pieces = []
    thread = candidate.get("thread") or candidate.get("thread_label") or candidate.get("narrative_thread")
    category = candidate.get("category") or candidate.get("type")
    candidate_type = candidate.get("type")
    if thread:
        pieces.append(f"Thread: {thread}")
    if category:
        pieces.append(f"Category: {category}")
    elif candidate_type:
        pieces.append(f"Type: {candidate_type}")
    if candidate.get("confidence"):
        pieces.append(f"Confidence: {candidate.get('confidence')}")
    if candidate.get("reason"):
        pieces.append(str(candidate["reason"]))
    if candidate.get("downgrade_reason"):
        pieces.append(str(candidate["downgrade_reason"]))
    return " | ".join(pieces) or fallback


for candidate in manual_review_candidates:
    summary = candidate_summary(candidate, "manual review candidate")
    for clip_i in (candidate.get("section_policy") or {}).get("covered_section_indexes", []):
        manual_reason_by_i.setdefault(int(clip_i), []).append(summary)

for candidate in auto_cut_candidates:
    summary = candidate_summary(candidate, "auto cut")
    for clip_i in (candidate.get("section_policy") or {}).get("covered_section_indexes", []):
        auto_reason_by_i.setdefault(int(clip_i), []).append(summary)

for group in structural_review_groups:
    summary = candidate_summary(group.get("llm_review") or group, "structural review candidate")
    for clip_i in group.get("section_indexes") or []:
        structural_reason_by_i.setdefault(int(clip_i), []).append(summary)


manual_groups = adjacent_groups([pos for pos, c in enumerate(clips) if c.get("color") == "Pink"])
auto_groups = adjacent_groups(auto_positions_from_candidates(auto_cut_candidates))
structural_groups = [
    [clip_pos_by_i[int(clip_i)] for clip_i in group.get("section_indexes", []) if int(clip_i) in clip_pos_by_i]
    for group in structural_review_groups
]
structural_groups = [group for group in structural_groups if group]


def draw_waveform(path: Path, snip: np.ndarray, bounds: list[tuple[int, int, str]]) -> None:
    width, height = 1100, 170
    img = Image.new("RGB", (width, height), (22, 22, 28))
    dr = ImageDraw.Draw(img)
    mid = height // 2
    total = max(1, len(snip))
    for b0, b1, kind in bounds:
        if kind == "manual":
            fill = (64, 30, 38)
        elif kind in {"auto", "structural"}:
            fill = (72, 34, 34)
        else:
            continue
        dr.rectangle([int(b0 / total * (width - 1)), 0, int(b1 / total * (width - 1)), height], fill=fill)
    for x in range(width - 1):
        a0 = x * total // (width - 1)
        segment = snip[a0 : (x + 1) * total // (width - 1) + 1]
        if len(segment) == 0:
            continue
        color = (120, 200, 140)
        for b0, b1, kind in bounds:
            if b0 <= a0 < b1:
                color = (245, 110, 110) if kind in {"manual", "auto", "structural"} else (120, 200, 140)
                break
        dr.line(
            [(x, int(mid - segment.max() * mid * 0.92)), (x, int(mid - segment.min() * mid * 0.92))],
            fill=color,
        )
    img.save(path)


def build_group_meta(groups: list[list[int]], mode: str, asset_prefix: str) -> tuple[list[dict], dict]:
    meta: list[dict] = []
    segmap: dict[str, list[dict]] = {}
    active_kind = mode if mode in {"auto", "structural"} else "manual"
    for group_index, group in enumerate(groups):
        first, last = group[0], group[-1]
        parts: list[np.ndarray] = []
        bounds: list[tuple[int, int, str, int, float, float]] = []
        segments: list[dict] = []
        pos = 0

        def add_clip(clip_pos: int, kind: str, side: str | None = None) -> None:
            nonlocal pos
            row = clips[clip_pos]
            clip_id = int(row.get("i", clip_pos))
            chunk, src_start, src_end = seg_audio(row, side)
            parts.append(chunk)
            bounds.append((pos, pos + len(chunk), kind, clip_id, src_start, src_end))
            segments.append(
                {
                    "clip_idx": clip_id,
                    "kind": "ctx" if kind == "ctx" else active_kind,
                    "src_start": round(src_start, 4),
                    "src_end": round(src_end, 4),
                    "snip_start": round(pos / SR, 4),
                    "snip_end": round((pos + len(chunk)) / SR, 4),
                }
            )
            pos += len(chunk)

        if mode != "structural" and first - 1 >= 0:
            add_clip(first - 1, "ctx", "before")
        for clip_pos in group:
            add_clip(clip_pos, active_kind)
        if mode != "structural" and last + 1 < N:
            add_clip(last + 1, "ctx", "after")

        snip = np.concatenate(parts) if parts else np.zeros(1, np.float32)
        segmap[str(group_index)] = segments
        wav_path = AST / f"{asset_prefix}snip_{group_index}.wav"
        wave_path = AST / f"{asset_prefix}wave_{group_index}.png"
        if not (A.reuse_assets and wav_path.exists() and wave_path.exists()):
            wavfile.write(wav_path, SR, (np.clip(snip, -1, 1) * 32767).astype(np.int16))
            draw_waveform(wave_path, snip, [(b0, b1, kind) for b0, b1, kind, _ci, _ss, _se in bounds])

        duration = max(0.001, len(snip) / SR)
        seg_by_clip = {int(s["clip_idx"]): s for s in segments}
        active_rows = []
        for clip_pos in group:
            row = clips[clip_pos]
            clip_id = int(row.get("i", clip_pos))
            segment = seg_by_clip[clip_id]
            cat = cats.get(clip_id, {})
            active_rows.append(
                {
                    "idx": clip_id,
                    "tc": tc(int(row["start"])),
                    "dur": round(row["dur"] / A.tl_fps, 2),
                    "src_start": segment["src_start"],
                    "src_end": segment["src_end"],
                    "snip_start": segment["snip_start"],
                    "snip_end": segment["snip_end"],
                    "run_vs": cat.get("run_vs", "?"),
                    "zcr": cat.get("zcr", "?"),
                    "reason": "; ".join(auto_reason_by_i.get(clip_id, []))
                    if mode == "auto"
                    else "; ".join(structural_reason_by_i.get(clip_id, []))
                    if mode == "structural"
                    else "; ".join(manual_reason_by_i.get(clip_id, [])),
                }
            )

        regions = []
        active_ranges = []
        for segment in segments:
            left = float(segment["snip_start"]) / duration * 100.0
            width = (float(segment["snip_end"]) - float(segment["snip_start"])) / duration * 100.0
            regions.append(
                {
                    "clip_idx": int(segment["clip_idx"]),
                    "kind": segment["kind"],
                    "left": round(left, 4),
                    "width": round(width, 4),
                    "src_start": segment["src_start"],
                    "src_end": segment["src_end"],
                    "snip_start": segment["snip_start"],
                    "snip_end": segment["snip_end"],
                }
            )
            if segment["kind"] == active_kind:
                active_ranges.append([float(segment["snip_start"]), float(segment["snip_end"])])

        meta.append(
            {
                "g": group_index,
                "mode": mode,
                "asset_prefix": asset_prefix,
                "active_kind": active_kind,
                "active_rows": active_rows,
                "dur": round(duration, 3),
                "regions": regions,
                "active_ranges": [[round(r[0], 3), round(r[1], 3)] for r in active_ranges],
                "before": tc(int(clips[first - 1]["start"])) if first - 1 >= 0 else "-",
                "after": tc(int(clips[last + 1]["start"])) if last + 1 < N else "-",
            }
        )
    return meta, segmap


manual_meta, manual_segmap = build_group_meta(manual_groups, "manual", "")
auto_meta, auto_segmap = build_group_meta(auto_groups, "auto", "auto_")
structural_meta, structural_segmap = build_group_meta(structural_groups, "structural", "struct_")
(REV / "segmap.json").write_text(json.dumps(manual_segmap, indent=1), encoding="utf-8")
(REV / "auto_segmap.json").write_text(json.dumps(auto_segmap, indent=1), encoding="utf-8")
(REV / "structural_segmap.json").write_text(json.dumps(structural_segmap, indent=1), encoding="utf-8")

INITIAL = {"pink": {}, "cuts": {}, "auto": {}, "restores": {}, "structural": {}, "structural_restores": {}}
if A.preload and os.path.exists(A.preload):
    try:
        loaded = json.loads(Path(A.preload).read_text(encoding="utf-8"))
        INITIAL = {
            "pink": loaded.get("pink", loaded if "pink" not in loaded else {}),
            "cuts": loaded.get("cuts", {}),
            "auto": loaded.get("auto", {}),
            "restores": loaded.get("restores", {}),
            "structural": loaded.get("structural", {}),
            "structural_restores": loaded.get("structural_restores", {}),
        }
    except Exception:
        pass


def safe_filename_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in value).strip(" ._")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or "cut_review"


source_video_path = Path(source_video) if source_video else None
source_video_exists = bool(source_video_path and source_video_path.exists())
save_stem = safe_filename_stem(
    source_video_path.stem
    if source_video_path
    else Path(A.mic).stem
    if A.mic
    else "cut_review"
)
decision_filename = f"{save_stem}_cut_review_decisions.json"
save_target = {
    "filename": decision_filename,
    "legacyFilename": "pink_decisions.json",
    "sourcePath": str(source_video_path) if source_video_path else "",
    "sourceDir": str(source_video_path.parent) if source_video_exists and source_video_path else "",
    "sourceExists": source_video_exists,
    "reviewCopyPath": str(REV / "pink_decisions.json"),
}


def render_regions(group: dict) -> str:
    pieces = []
    for region in group["regions"]:
        mode_class = group["mode"] if region["kind"] != "ctx" else "ctx"
        label = ("ctx " if region["kind"] == "ctx" else "") + str(region["clip_idx"])
        title = (
            f"clip {region['clip_idx']} {region['kind']} | "
            f"src {float(region['src_start']):.3f}-{float(region['src_end']):.3f}s | "
            f"snippet {float(region['snip_start']):.3f}-{float(region['snip_end']):.3f}s"
        )
        pieces.append(
            '<div class="clipseg {mode} {kind}" data-idx="{idx}" title="{title}" '
            'data-snip-start="{snip_start:.4f}" data-snip-end="{snip_end:.4f}" '
            'style="left:{left:.4f}%;width:{width:.4f}%"><span>{label}</span></div>'.format(
                mode=mode_class,
                kind=html.escape(str(region["kind"])),
                idx=int(region["clip_idx"]),
                title=html.escape(title),
                snip_start=float(region["snip_start"]),
                snip_end=float(region["snip_end"]),
                left=float(region["left"]),
                width=float(region["width"]),
                label=html.escape(label),
            )
        )
    return "".join(pieces)


def render_rows(group: dict) -> str:
    rows = []
    for row in group["active_rows"]:
        if group["mode"] == "structural":
            buttons = (
                '<button class="cut" data-v="cut">CUT</button>'
                '<button class="restore" data-v="restore">RESTORE</button>'
                '<button class="restorefrom" data-bulk="restore_from">RESTORE FROM HERE</button>'
                '<button class="cutfrom" data-bulk="cut_from">CUT FROM HERE</button>'
            )
        elif group["mode"] == "auto":
            buttons = '<button class="cut" data-v="cut">CUT</button><button class="restore" data-v="restore">RESTORE</button>'
        else:
            buttons = '<button class="keep" data-v="keep">KEEP</button><button class="cut" data-v="cut">CUT</button>'
        reason = f'<div class="reason">{html.escape(row["reason"])}</div>' if row.get("reason") else ""
        rows.append(
            '<div class="seg" data-mode="{mode}" data-idx="{idx}"><span class="lab">'
            'Clip {idx} &middot; src {ss:.3f}-{se:.3f}s &middot; snippet {ps:.3f}-{pe:.3f}s '
            '&middot; {dur}s <span class="st">tl {tc} &middot; run {rv}/zcr {zc}</span>{reason}</span>'
            '<div class="tg">{buttons}</div></div>'.format(
                mode=group["mode"],
                idx=int(row["idx"]),
                ss=float(row["src_start"]),
                se=float(row["src_end"]),
                ps=float(row["snip_start"]),
                pe=float(row["snip_end"]),
                dur=row["dur"],
                tc=html.escape(row["tc"]),
                rv=html.escape(str(row["run_vs"])),
                zc=html.escape(str(row["zcr"])),
                reason=reason,
                buttons=buttons,
            )
        )
    return "".join(rows)


def review_card(group: dict) -> str:
    if group["mode"] == "auto":
        mode_title = "Automatic Cut"
        active_label = "AUTO CUT"
    elif group["mode"] == "structural":
        mode_title = "Structural Cut"
        active_label = "STRUCTURAL CUT"
    else:
        mode_title = "Manual Review"
        active_label = "PINK"
    asset_prefix = group["asset_prefix"]
    starts = ", ".join("%.1fs" % active[0] for active in group["active_ranges"])
    cap = (
        "green restore boxes keep part of the proposed cut"
        if group["mode"] in {"auto", "structural"}
        else "drag=new cut"
    )
    media = ""
    if group.get("removed_video"):
        media = (
            '<div class="smedia"><div><div class="vlabel">Proposed cut section</div>'
            '<video controls preload="none" src="{removed}"></video></div>'
            '<div><div class="vlabel">Flow with cut omitted</div>'
            '<video controls preload="none" src="{flow}"></video></div></div>'
        ).format(
            removed=html.escape(str(group.get("removed_video") or "")),
            flow=html.escape(str(group.get("flow_video") or "")),
        )
    bulk_controls = ""
    if group["mode"] == "structural":
        bulk_controls = (
            '<div class="bulkbar">'
            '<button class="restore-all" type="button">Restore whole narrative cut</button>'
            '<button class="cut-all" type="button">Cut whole narrative cut</button>'
            '</div>'
        )
    reason = (
        '<div class="sreason">{}</div>'.format(html.escape(str(group.get("reason") or "")))
        if group.get("reason") and group["mode"] == "structural"
        else ""
    )
    return (
        '<div class="card" data-mode="{mode}" data-g="{g}"><div class="hd">{title} Group {g} '
        '&nbsp;&middot;&nbsp; before {before} -> <b>{active}</b> -> after {after}</div>'
        '{reason}{bulk}{media}'
        '<div class="wavewrap"><img loading="lazy" src="assets/{prefix}wave_{g}.png">'
        '<div class="clips">{regions}</div><div class="playhead"></div><div class="nowpink">&#9654; IN RANGE</div></div>'
        '<div class="cap"><span style="color:#f77">&#9679;</span> ranges at {starts} &middot; {cap} '
        '&middot; drag box=move &middot; edges=resize &middot; right-click=clear</div>'
        '<div class="row"><audio controls preload="none" src="assets/{prefix}snip_{g}.wav"></audio>'
        '<button class="prev" type="button">&#9654; Preview result</button></div>'
        '<div class="segs">{rows}</div></div>'
    ).format(
        mode=group["mode"],
        g=group["g"],
        title=mode_title,
        before=group["before"],
        active=active_label,
        after=group["after"],
        reason=reason,
        bulk=bulk_controls,
        media=media,
        prefix=asset_prefix,
        regions=render_regions(group),
        starts=starts,
        cap=cap,
        rows=render_rows(group),
    )


def ffmpeg_preview(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def maybe_build_structural_assets(row: dict, idx: int) -> dict:
    if not source_video or not os.path.exists(source_video) or not os.path.exists(A.mic):
        return dict(row)
    start = float(row.get("start_sec", row.get("source_start_sec", 0.0)))
    end = float(row.get("end_sec", row.get("source_end_sec", start)))
    duration = max(0.001, end - start)
    removed = AST / f"struct_removed_{idx}.mp4"
    flow = AST / f"struct_flow_{idx}.mp4"
    vfilter = "scale=640:-2,fps=30,setpts=PTS-STARTPTS"
    afilter = "aresample=44100,asetpts=PTS-STARTPTS"
    if (not A.reuse_assets) or (not removed.exists()):
        ffmpeg_preview(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                "%.3f" % start,
                "-t",
                "%.3f" % duration,
                "-i",
                source_video,
                "-ss",
                "%.3f" % start,
                "-t",
                "%.3f" % duration,
                "-i",
                A.mic,
                "-filter_complex",
                "[0:v]%s[v];[1:a]%s[a]" % (vfilter, afilter),
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "32",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                str(removed),
            ]
        )
    pre = min(8.0, start)
    post = 8.0
    pre_start = max(0.0, start - pre)
    if (not A.reuse_assets) or (not flow.exists()):
        ffmpeg_preview(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                "%.3f" % pre_start,
                "-t",
                "%.3f" % pre,
                "-i",
                source_video,
                "-ss",
                "%.3f" % pre_start,
                "-t",
                "%.3f" % pre,
                "-i",
                A.mic,
                "-ss",
                "%.3f" % end,
                "-t",
                "%.3f" % post,
                "-i",
                source_video,
                "-ss",
                "%.3f" % end,
                "-t",
                "%.3f" % post,
                "-i",
                A.mic,
                "-filter_complex",
                "[0:v]%s[v0];[1:a]%s[a0];[2:v]%s[v1];[3:a]%s[a1];"
                "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]" % (vfilter, afilter, vfilter, afilter),
                "-map",
                "[outv]",
                "-map",
                "[outa]",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "32",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                str(flow),
            ]
        )
    return {**row, "removed_video": f"assets/{removed.name}", "flow_video": f"assets/{flow.name}"}


def structural_card(row: dict) -> str:
    label = html.escape(str(row.get("label") or row.get("type") or "structural_cut"))
    status = html.escape(str(row.get("status") or row.get("confidence") or "locked"))
    reason = html.escape(str(row.get("reason") or ""))
    start = float(row.get("start_sec", row.get("source_start_sec", 0.0)))
    end = float(row.get("end_sec", row.get("source_end_sec", start)))
    match_text = "LLM confirmed" if row.get("matches_locked_reference") is True else status
    media = ""
    if row.get("removed_video"):
        media = (
            '<div class="smedia"><div><div class="vlabel">Removed section</div>'
            '<video controls preload="none" src="{removed}"></video></div>'
            '<div><div class="vlabel">Flow with cut omitted</div>'
            '<video controls preload="none" src="{flow}"></video></div></div>'
        ).format(removed=html.escape(row["removed_video"]), flow=html.escape(row["flow_video"]))
    return (
        '<div class="scut"><div><b>{label}</b> <span>{match}</span></div>'
        '<div class="stime">source {start:.3f}s -> {end:.3f}s &middot; duration {dur:.3f}s</div>'
        '<div class="sreason">{reason}</div>{media}</div>'
    ).format(
        label=label,
        match=html.escape(match_text),
        start=start,
        end=end,
        dur=max(0.0, end - start),
        reason=reason,
        media=media,
    )


def is_livestream_candidate(candidate: dict) -> bool:
    text = " ".join(
        str(candidate.get(key) or "").lower()
        for key in ("type", "category", "source", "thread", "thread_label", "narrative_thread")
    )
    return any(token in text for token in ("livestream", "chat", "stream_", "stream meta", "aside"))


for index, group in enumerate(structural_review_groups):
    if index >= len(structural_meta):
        continue
    enriched = maybe_build_structural_assets(group, index)
    structural_meta[index].update(
        {
            "structural_label": group.get("label") or f"structural_{index}",
            "reason": group.get("reason") or "",
            "status": group.get("status") or "review",
            "removed_video": enriched.get("removed_video"),
            "flow_video": enriched.get("flow_video"),
            "before": "%.2fs" % float(group.get("start_sec", group.get("source_start_sec", 0.0))),
            "after": "%.2fs" % float(group.get("end_sec", group.get("source_end_sec", 0.0))),
        }
    )


def livestream_note_html() -> str:
    if not livestream_review.get("enabled"):
        return ""
    chat_candidates = [candidate for candidate in manual_review_candidates if is_livestream_candidate(candidate)]
    thread_counts: dict[str, int] = {}
    for candidate in chat_candidates:
        thread = (
            candidate.get("thread")
            or candidate.get("thread_label")
            or candidate.get("narrative_thread")
            or candidate.get("category")
            or candidate.get("type")
            or "uncategorized"
        )
        thread_counts[str(thread)] = thread_counts.get(str(thread), 0) + 1
    thread_text = ", ".join(
        f"{html.escape(thread)} ({count})"
        for thread, count in sorted(thread_counts.items(), key=lambda item: item[0].lower())
    )
    if not thread_text:
        thread_text = "No livestream/chat candidates in the current compiled manifest."
    bypass = "on" if livestream_review.get("bypass_gameplay_narrative_cuts") else "off"
    chat = "on" if livestream_review.get("cut_chat_interactions") else "off"
    return (
        '<div class="live-note"><b>Livestream edit mode</b> '
        f'chat/asides: {chat} &middot; gameplay narrative bypass: {bypass}'
        f'<div>Threads: {thread_text}</div></div>'
    )


if structural_reviews and not structural_review_groups:
    structural_reviews = [maybe_build_structural_assets(row, i) for i, row in enumerate(structural_reviews)]

LIVESTREAM_NOTE = livestream_note_html()
MANUAL_CARDS = "".join(review_card(group) for group in manual_meta) or '<p class="empty">No manual review candidates.</p>'
AUTO_CARDS = "".join(review_card(group) for group in auto_meta) or '<p class="empty">No automatic cuts.</p>'
STRUCTURAL_HTML = (
    "".join(review_card(group) for group in structural_meta)
    if structural_meta
    else "".join(structural_card(row) for row in structural_reviews)
    if structural_reviews
    else '<p class="empty">No structural narrative cuts.</p>'
)
MANUAL_GROUPS_JS = json.dumps({m["g"]: {"dur": m["dur"], "active": m["active_ranges"]} for m in manual_meta})
AUTO_GROUPS_JS = json.dumps({m["g"]: {"dur": m["dur"], "active": m["active_ranges"]} for m in auto_meta})
STRUCTURAL_GROUPS_JS = json.dumps({m["g"]: {"dur": m["dur"], "active": m["active_ranges"]} for m in structural_meta})

T = """<!doctype html><html><head><meta charset="utf-8"><title>Cut Review</title><style>
body{background:#15151a;color:#e8e8ee;font:14px/1.4 system-ui,Arial;margin:0;padding:18px 18px 92px}
h1{font-size:20px;margin:0 0 4px}.sub{color:#9aa;margin:0 0 12px}.empty{color:#aeb;margin:12px 2px}
.live-note{background:#20262b;border:1px solid #3d5962;border-left:4px solid #48a6b8;border-radius:8px;color:#dceff3;margin:0 0 12px;padding:9px 11px}.live-note div{color:#aac6cc;font-size:12px;margin-top:3px}
.tabs{display:flex;gap:8px;margin:0 0 14px;position:sticky;top:0;background:#15151a;padding:8px 0;z-index:10}.tabbtn{background:#262630;color:#dedeec;border:1px solid #393948;border-radius:7px;padding:8px 12px;font-weight:700;cursor:pointer}.tabbtn.on{background:#3b6fc2;color:#fff;border-color:#6d95d6}.panel{display:none}.panel.on{display:block}
.structural{background:#22242b;border:1px solid #4b4b58;border-radius:10px;padding:12px;margin:0 0 16px}.structural h2{font-size:16px;margin:0 0 4px}.structural p{color:#b8b8c8;margin:0 0 10px}.scut{background:#191a20;border-left:4px solid #d29044;border-radius:6px;padding:9px 10px;margin:8px 0}.scut span{color:#ffd39b;font-size:12px;margin-left:8px}.stime{color:#eee;margin-top:2px}.sreason{color:#b8b8c8;font-size:13px;margin-top:3px}.smedia{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:10px}.smedia video{width:100%;max-height:260px;background:#000;border-radius:6px}.vlabel{font-size:12px;color:#d5d5e0;margin:0 0 4px}
.card{background:#1e1e26;border:1px solid #33333f;border-radius:10px;padding:12px;margin:0 0 14px}.hd{font-weight:600;margin-bottom:8px;color:#cdd}
.wavewrap{position:relative;cursor:crosshair;user-select:none;overflow:hidden}.card img{width:100%;display:block;border-radius:6px;background:#000;pointer-events:none}.clips{position:absolute;inset:0;z-index:2;pointer-events:none}.clipseg{position:absolute;top:0;bottom:0;border-left:2px solid rgba(255,255,255,.72);border-right:1px solid rgba(255,255,255,.32);box-sizing:border-box}.clipseg span{position:absolute;z-index:2;left:3px;top:4px;background:rgba(0,0,0,.62);color:#f3f3f6;border-radius:3px;padding:1px 4px;font-size:11px;max-width:calc(100% - 6px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.clipseg.ctx{background:rgba(190,190,210,.08)}.clipseg.manual{background:rgba(232,171,73,.18)}.clipseg.manual.keep{background:rgba(46,155,84,.38);border-left-color:#68e089}.clipseg.manual.cut{background:rgba(194,59,59,.52);border-left-color:#ff7878}.clipseg.auto,.clipseg.structural{background:rgba(194,59,59,.42);border-left-color:#ff7878}.clipseg.auto.cut,.clipseg.structural.cut{background:rgba(194,59,59,.55)}.clipseg.auto.restore,.clipseg.structural.restore{background:rgba(46,155,84,.42);border-left-color:#68e089}.clipseg.play-current{outline:2px solid rgba(255,236,140,.9);outline-offset:-2px;box-shadow:inset 0 0 0 999px rgba(255,255,255,.10);z-index:3}.clipseg.play-current span{background:rgba(0,0,0,.82);color:#fff4a6}.clipseg.manual.cut:after,.clipseg.auto.cut:after,.clipseg.structural.cut:after{content:"";position:absolute;inset:0;background:repeating-linear-gradient(135deg,rgba(0,0,0,0) 0 7px,rgba(0,0,0,.24) 7px 10px)}
.playhead{position:absolute;top:0;bottom:0;width:2px;background:#fff;left:0;opacity:0;pointer-events:none;box-shadow:0 0 5px rgba(255,255,255,.8);z-index:4}.playhead.vis{opacity:.95}.playhead.red{background:#ff5252;box-shadow:0 0 8px #ff5252}.nowpink{position:absolute;top:6px;right:8px;background:#c23b3b;color:#fff;font-weight:700;font-size:12px;padding:3px 9px;border-radius:5px;opacity:0;pointer-events:none;z-index:5}.nowpink.show{opacity:1}
.cutbox{position:absolute;top:0;bottom:0;background:rgba(255,60,60,.30);border-left:3px solid #fd0;border-right:3px solid #fd0;cursor:move;z-index:3}.cutbox.restorebox{background:rgba(64,210,118,.28);border-left-color:#7dff98;border-right-color:#7dff98}.cutbox.prov{background:rgba(255,210,60,.25);pointer-events:none}.cutbox.restorebox.prov{background:rgba(64,210,118,.20)}.cutbox .cbx{position:absolute;top:2px;right:3px;width:16px;height:16px;line-height:14px;text-align:center;background:#000a;color:#fff;border-radius:3px;font-size:13px;cursor:pointer}
.bulkbar{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 10px}.bulkbar button{border:0;border-radius:7px;color:#fff;cursor:pointer;font-weight:700;padding:8px 12px}.bulkbar .restore-all{background:#2e9b54}.bulkbar .cut-all{background:#8b2d39}.cap{color:#9a9ab0;font-size:12px;margin:6px 2px 2px}.row{display:flex;gap:10px;align-items:center;margin:8px 0}audio{flex:1}.prev{background:#3b6fc2;color:#fff;border:0;border-radius:7px;padding:8px 14px;font-weight:700;cursor:pointer;white-space:nowrap}.segs{display:flex;flex-direction:column;gap:6px}.seg{display:flex;justify-content:space-between;align-items:center;background:#262630;border-radius:8px;gap:10px;padding:8px 10px}.seg.play-current{background:#30303d;box-shadow:inset 3px 0 0 #f2d95c,0 0 0 1px rgba(242,217,92,.38)}.lab{color:#e6e6ee;flex:1 1 360px;min-width:0}.st{color:#8a8aa0;font-size:12px;margin-left:6px}.reason{color:#c0a878;font-size:12px;margin-top:3px}.tg{display:flex;flex:0 1 430px;flex-wrap:wrap;justify-content:flex-end;gap:6px}.tg button{border:0;border-radius:6px;padding:7px 14px;font-weight:700;cursor:pointer;color:#fff;opacity:.35}.tg .restorefrom,.tg .cutfrom{font-size:11px;padding:7px 9px;opacity:.85}.tg .keep,.tg .restore,.tg .restorefrom{background:#2e9b54}.tg .cut,.tg .cutfrom{background:#c23b3b}.tg button.on{opacity:1;outline:2px solid #fff}
footer{position:fixed;left:0;right:0;bottom:0;background:#0e0e12;border-top:1px solid #33333f;padding:12px 18px;display:flex;gap:14px;align-items:center}#save{background:#3b6fc2;color:#fff;border:0;border-radius:8px;padding:10px 22px;font-weight:700;font-size:15px;cursor:pointer}#cnt{color:#bbb}#savehint{color:#8da3bf;max-width:30%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#savehint.ok{color:#8ed69d}#savehint.warn{color:#d9bb78}#out{flex:1;height:34px;background:#1a1a22;color:#9c9;border:1px solid #333;border-radius:6px;padding:6px;font-family:monospace;font-size:11px}
</style></head><body><h1>Cut Review</h1>
<p class="sub">Manual review defaults to keep. Automatic cuts default to cut. Save writes one project-specific decision JSON with all decisions.</p>
__LIVESTREAM_NOTE__
<div class="tabs"><button class="tabbtn on" data-tab="manual">Manual review (__MANUAL_COUNT__)</button><button class="tabbtn" data-tab="auto">Automatic cuts (__AUTO_COUNT__)</button><button class="tabbtn" data-tab="structural">Structural cuts (__STRUCT_COUNT__)</button></div>
<section id="manual" class="panel on">__MANUAL_CARDS__</section>
<section id="auto" class="panel">__AUTO_CARDS__</section>
<section id="structural" class="panel structural"><h2>Structural Narrative Cut Review</h2><p>These proposed restart/remake ranges default to cut. Restore whole FCPXML sections or drag green restore boxes to keep partial sections.</p>__STRUCTURAL__</section>
<footer><button id="save">Save decisions</button><span id="cnt"></span><span id="savehint"></span><input id="out" readonly></footer>
<script>
var MANUAL_GROUPS=__MANUAL_GROUPS__, AUTO_GROUPS=__AUTO_GROUPS__, STRUCTURAL_GROUPS=__STRUCTURAL_GROUPS__, INITIAL=__INITIAL__, SAVE_TARGET=__SAVE_TARGET__;
var dec={}, autoDec={}, structDec={}, CUTS={}, RESTORES={}, STRUCTURAL_RESTORES={}, boxDrag=null, decisionFileHandle=null;
function activeGroups(mode){return mode==='auto'?AUTO_GROUPS:(mode==='structural'?STRUCTURAL_GROUPS:MANUAL_GROUPS);}
function boxStore(mode){return mode==='auto'?RESTORES:(mode==='structural'?STRUCTURAL_RESTORES:CUTS);}
function decisionStore(mode){return mode==='auto'?autoDec:(mode==='structural'?structDec:dec);}
function defaultState(mode){return mode==='auto'||mode==='structural'?'cut':'keep';}
function setSegState(mode,idx,state){document.querySelectorAll('.clipseg.'+mode+'[data-idx="'+idx+'"]').forEach(function(n){n.classList.remove('keep','cut','restore');n.classList.add(state);n.setAttribute('data-state',state);});}
function setRowDecision(s,state){var mode=s.dataset.mode,idx=s.dataset.idx,store=decisionStore(mode);store[idx]=state;s.querySelectorAll('button[data-v]').forEach(function(b){b.classList.toggle('on',store[idx]===b.dataset.v);});setSegState(mode,idx,store[idx]);}
function setRowsFrom(s,state){var rows=Array.prototype.slice.call(s.closest('.card').querySelectorAll('.seg')),start=rows.indexOf(s);for(var i=start;i<rows.length;i++)setRowDecision(rows[i],state);upd();}
function upd(){var mc=0,mk=0,ac=0,ar=0,sc=0,sr=0,ct=0,rt=0,srt=0;for(var i in dec){if(dec[i]==='cut')mc++;else mk++;}for(var a in autoDec){if(autoDec[a]==='restore')ar++;else ac++;}for(var s in structDec){if(structDec[s]==='restore')sr++;else sc++;}for(var g in CUTS)ct+=CUTS[g].length;for(var h in RESTORES)rt+=RESTORES[h].length;for(var sg in STRUCTURAL_RESTORES)srt+=STRUCTURAL_RESTORES[sg].length;document.getElementById('cnt').textContent=mk+' manual keep / '+mc+' manual cut / '+ac+' auto cut / '+ar+' auto restore / '+sc+' structural cut / '+sr+' structural restore / '+ct+' trims / '+rt+' auto restore boxes / '+srt+' structural restore boxes';}
function saveStatus(text,kind){var el=document.getElementById('savehint');el.classList.remove('ok','warn');if(kind)el.classList.add(kind);el.textContent=text;}
function defaultSaveHint(){return SAVE_TARGET.sourceExists&&SAVE_TARGET.sourceDir?'Target: '+SAVE_TARGET.sourceDir+'\\\\'+SAVE_TARGET.filename:'Source video path unavailable; choose a save path for '+SAVE_TARGET.filename;}
function decisionJson(){var cuts={},restores={},structuralRestores={};for(var g in CUTS)if(CUTS[g].length)cuts[g]=CUTS[g];for(var h in RESTORES)if(RESTORES[h].length)restores[h]=RESTORES[h];for(var sg in STRUCTURAL_RESTORES)if(STRUCTURAL_RESTORES[sg].length)structuralRestores[sg]=STRUCTURAL_RESTORES[sg];return JSON.stringify({pink:dec,cuts:cuts,auto:autoDec,restores:restores,structural:structDec,structural_restores:structuralRestores},null,1);}
function downloadDecisionJson(text){var b=new Blob([text],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=SAVE_TARGET.filename||'cut_review_decisions.json';a.click();setTimeout(function(){URL.revokeObjectURL(a.href);},1000);}
async function writeDecisionJson(text){document.getElementById('out').value=text;if(window.showSaveFilePicker){try{if(!decisionFileHandle){if(!SAVE_TARGET.sourceExists)saveStatus('Source video path unavailable; choose a save location.','warn');decisionFileHandle=await window.showSaveFilePicker({suggestedName:SAVE_TARGET.filename,types:[{description:'JSON decisions',accept:{'application/json':['.json']}}]});}var w=await decisionFileHandle.createWritable();await w.write(text);await w.close();saveStatus('Saved '+(decisionFileHandle.name||SAVE_TARGET.filename),'ok');return;}catch(e){if(e&&e.name==='AbortError'){saveStatus('Save canceled.','warn');return;}saveStatus('Direct save unavailable; downloaded '+SAVE_TARGET.filename,'warn');}}downloadDecisionJson(text);}
function subtractRanges(base,keep){var out=[];base.forEach(function(r){var pieces=[r.slice()];keep.forEach(function(k){var next=[];pieces.forEach(function(p){var s=Math.max(p[0],k[0]),e=Math.min(p[1],k[1]);if(e<=s){next.push(p);return;}if(p[0]<s)next.push([p[0],s]);if(e<p[1])next.push([e,p[1]]);});pieces=next;});out=out.concat(pieces);});return out.filter(function(r){return r[1]-r[0]>0.005;});}
document.querySelectorAll('.tabbtn').forEach(function(b){b.onclick=function(){document.querySelectorAll('.tabbtn').forEach(function(x){x.classList.toggle('on',x===b);});document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('on',p.id===b.dataset.tab);});};});
document.querySelectorAll('.seg').forEach(function(s){var mode=s.dataset.mode, idx=s.dataset.idx, start=(mode==='auto'?(INITIAL.auto&&INITIAL.auto[idx]):(mode==='structural'?(INITIAL.structural&&INITIAL.structural[idx]):(INITIAL.pink&&INITIAL.pink[idx])))||defaultState(mode);setRowDecision(s,start);s.querySelectorAll('button[data-v]').forEach(function(b){b.onclick=function(){setRowDecision(s,b.dataset.v);upd();};});s.querySelectorAll('button[data-bulk]').forEach(function(b){b.onclick=function(){setRowsFrom(s,b.dataset.bulk==='restore_from'?'restore':'cut');};});});
document.querySelectorAll('.card').forEach(function(card){var mode=card.dataset.mode,g=card.dataset.g,info=(activeGroups(mode)[g]||{dur:0,active:[]});var audio=card.querySelector('audio'),ph=card.querySelector('.playhead'),badge=card.querySelector('.nowpink'),ww=card.querySelector('.wavewrap'),boxes=boxStore(mode);var initialBoxes=(mode==='auto'?INITIAL.restores:(mode==='structural'?INITIAL.structural_restores:INITIAL.cuts))||{};boxes[g]=initialBoxes[g]?initialBoxes[g].map(function(c){return c.slice();}):[];var prevMode=false,skips=[];
  var clipEls=Array.prototype.slice.call(card.querySelectorAll('.clipseg')),currentPlayIdx='';
  function setAllRows(state){card.querySelectorAll('.seg').forEach(function(row){setRowDecision(row,state);});upd();}
  var restoreAll=card.querySelector('.restore-all'),cutAll=card.querySelector('.cut-all');if(restoreAll)restoreAll.onclick=function(){setAllRows('restore');};if(cutAll)cutAll.onclick=function(){setAllRows('cut');};
  function dur(){return audio.duration||info.dur||1;}
  function clearPlaybackHighlight(){card.querySelectorAll('.clipseg.play-current,.seg.play-current').forEach(function(n){n.classList.remove('play-current');});currentPlayIdx='';}
  function paintPlayback(){var t=audio.currentTime,f=t/dur();if(f>1)f=1;ph.style.left=(f*100)+'%';var inA=info.active.some(function(r){return t>=r[0]&&t<=r[1];});ph.classList.toggle('red',inA);badge.classList.toggle('show',inA);var active=null,activeIdx='';for(var i=0;i<clipEls.length;i++){var s=Number(clipEls[i].dataset.snipStart||0),e=Number(clipEls[i].dataset.snipEnd||0);if(t>=s&&t<e){active=clipEls[i];activeIdx=active.dataset.idx||'';break;}}if(activeIdx===currentPlayIdx)return;clearPlaybackHighlight();currentPlayIdx=activeIdx;if(active){active.classList.add('play-current');var row=card.querySelector('.seg[data-idx="'+activeIdx+'"]');if(row)row.classList.add('play-current');}}
  function loop(){if(audio.paused)return;if(prevMode){for(var i=0;i<skips.length;i++){if(audio.currentTime>=skips[i][0]&&audio.currentTime<skips[i][1]-0.005){audio.currentTime=skips[i][1];break;}}}paintPlayback();requestAnimationFrame(loop);}
  audio.addEventListener('play',function(){ph.classList.add('vis');paintPlayback();requestAnimationFrame(loop);});audio.addEventListener('pause',function(){prevMode=false;paintPlayback();});audio.addEventListener('seeked',paintPlayback);audio.addEventListener('timeupdate',paintPlayback);audio.addEventListener('ended',function(){prevMode=false;badge.classList.remove('show');clearPlaybackHighlight();});audio.addEventListener('loadedmetadata',function(){render();paintPlayback();});
  card.querySelector('.prev').onclick=function(){if(mode==='manual'){skips=boxes[g].map(function(c){return c.slice();});info.active.forEach(function(r,i){var el=card.querySelectorAll('.seg')[i];if(el&&dec[el.dataset.idx]==='cut')skips.push(r.slice());});}else{var keep=boxes[g].map(function(c){return c.slice();});var store=decisionStore(mode);info.active.forEach(function(r,i){var el=card.querySelectorAll('.seg')[i];if(el&&store[el.dataset.idx]==='restore')keep.push(r.slice());});skips=subtractRanges(info.active,keep);}skips.sort(function(a,b){return a[0]-b[0];});prevMode=true;audio.currentTime=0;audio.play();};
  function pxSec(px){var r=ww.getBoundingClientRect();return Math.max(0,Math.min(1,(px-r.left)/r.width))*dur();}
  function render(){ww.querySelectorAll('.cutbox:not(.prov)').forEach(function(n){n.remove();});boxes[g].forEach(function(c,ci){var d=document.createElement('div');d.className='cutbox '+(mode==='auto'||mode==='structural'?'restorebox':'');d.style.left=(c[0]/dur()*100)+'%';d.style.width=(Math.max(0,c[1]-c[0])/dur()*100)+'%';var rm=document.createElement('div');rm.className='cbx';rm.textContent='x';d.appendChild(rm);rm.onclick=function(ev){ev.stopPropagation();boxes[g].splice(ci,1);render();upd();};d.addEventListener('mousedown',function(ev){ev.stopPropagation();ev.preventDefault();var r=d.getBoundingClientRect();var off=ev.clientX-r.left;boxDrag={mode:mode,g:g,ci:ci,edge:off<8?'L':(off>r.width-8?'R':'M'),mx:ev.clientX,s0:c[0],e0:c[1],ww:ww,dur:dur(),render:render};});ww.appendChild(d);});}
  var down=false,sx=0,prov=null;ww.addEventListener('mousedown',function(e){if(e.target.classList.contains('cutbox')||e.target.classList.contains('cbx'))return;if(e.button!==0)return;down=true;sx=e.clientX;});ww.addEventListener('contextmenu',function(e){e.preventDefault();boxes[g]=[];render();upd();});ww.addEventListener('mousemove',function(e){if(!down||boxDrag)return;if(!prov){prov=document.createElement('div');prov.className='cutbox prov '+(mode==='auto'||mode==='structural'?'restorebox':'');ww.appendChild(prov);}var r=ww.getBoundingClientRect();var x0=Math.min(sx,e.clientX)-r.left,x1=Math.max(sx,e.clientX)-r.left;prov.style.left=(x0/r.width*100)+'%';prov.style.width=((x1-x0)/r.width*100)+'%';});
  window.addEventListener('mouseup',function(e){if(boxDrag||!down)return;down=false;if(prov){ww.removeChild(prov);prov=null;}if(Math.abs(e.clientX-sx)<6){audio.currentTime=pxSec(e.clientX);ph.classList.add('vis');loop();return;}var a=pxSec(sx),b=pxSec(e.clientX);boxes[g].push([+Math.min(a,b).toFixed(3),+Math.max(a,b).toFixed(3)]);render();upd();});render();});
window.addEventListener('mousemove',function(e){if(!boxDrag)return;var store=boxStore(boxDrag.mode),dsec=(e.clientX-boxDrag.mx)/boxDrag.ww.getBoundingClientRect().width*boxDrag.dur,s=boxDrag.s0,en=boxDrag.e0,D=boxDrag.dur;if(boxDrag.edge==='M'){s+=dsec;en+=dsec;if(s<0){en-=s;s=0;}if(en>D){s-=(en-D);en=D;}}else if(boxDrag.edge==='L'){s=Math.max(0,Math.min(boxDrag.s0+dsec,en-0.02));}else{en=Math.min(D,Math.max(boxDrag.e0+dsec,s+0.02));}store[boxDrag.g][boxDrag.ci]=[+s.toFixed(3),+en.toFixed(3)];boxDrag.render();upd();});
window.addEventListener('mouseup',function(){boxDrag=null;});upd();saveStatus(defaultSaveHint(),SAVE_TARGET.sourceExists?'':'warn');
document.getElementById('save').onclick=function(){writeDecisionJson(decisionJson());};
</script></body></html>"""

(REV / "index.html").write_text(
    T.replace("__MANUAL_CARDS__", MANUAL_CARDS)
    .replace("__AUTO_CARDS__", AUTO_CARDS)
    .replace("__STRUCTURAL__", STRUCTURAL_HTML)
    .replace("__LIVESTREAM_NOTE__", LIVESTREAM_NOTE)
    .replace("__MANUAL_GROUPS__", MANUAL_GROUPS_JS)
    .replace("__AUTO_GROUPS__", AUTO_GROUPS_JS)
    .replace("__STRUCTURAL_GROUPS__", STRUCTURAL_GROUPS_JS)
    .replace("__INITIAL__", json.dumps(INITIAL))
    .replace("__SAVE_TARGET__", json.dumps(save_target))
    .replace("__MANUAL_COUNT__", str(sum(len(m["active_rows"]) for m in manual_meta)))
    .replace("__AUTO_COUNT__", str(sum(len(m["active_rows"]) for m in auto_meta)))
    .replace("__STRUCT_COUNT__", str(sum(len(m["active_rows"]) for m in structural_meta) or len(structural_reviews))),
    encoding="utf-8",
)
print(
    "manual groups:",
    len(manual_meta),
    "manual sections:",
    sum(len(m["active_rows"]) for m in manual_meta),
    "| auto groups:",
    len(auto_meta),
    "auto sections:",
    sum(len(m["active_rows"]) for m in auto_meta),
    "| structural groups:",
    len(structural_meta),
    "structural sections:",
    sum(len(m["active_rows"]) for m in structural_meta),
    "| wrote",
    str(REV / "index.html"),
    "+ segmap.json + auto_segmap.json + structural_segmap.json",
)
