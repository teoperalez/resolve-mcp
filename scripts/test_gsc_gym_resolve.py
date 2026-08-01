from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from resolve_mcp.orchestrator.gsc_gym_resolve import (
    audit_live_timeline,
    resolve_receipt_deployment_ready,
    run_resolve_dry_run,
)
from resolve_mcp.orchestrator.gsc_gym_resolve_audio import (
    GscGymResolveAudioError,
    audit_audio_placement,
    build_audio_placement_plan,
    repair_receipt_bound_audio,
)


START = 216_000


class FakeMedia:
    def __init__(self, path: str, duration: int = 10_000) -> None:
        self.path = path
        self.duration = duration

    def GetClipProperty(self, key=None):
        values = {"File Path": self.path, "FPS": "60"}
        return values.get(key, "") if key is not None else values

    def GetUniqueId(self):
        return "media-" + self.path.casefold()

    def GetName(self):
        return Path(self.path).name


class FakeItem:
    def __init__(
        self,
        name: str,
        start: int,
        end: int,
        path: str,
        *,
        crop: float = 0.0,
        source_start: int = 0,
        media: FakeMedia | None = None,
        left_offset: int | None = None,
        right_offset: int | None = None,
    ) -> None:
        self.name = name
        self.start = start
        self.end = end
        self.media = media or FakeMedia(path, end - start)
        self.crop = crop
        self.source_start = source_start
        self.left_offset = source_start if left_offset is None else left_offset
        self.right_offset = (
            max(0, self.media.duration - source_start - (end - start))
            if right_offset is None
            else right_offset
        )
        self.links: list[FakeItem] = []

    def GetStart(self):
        return self.start

    def GetDuration(self):
        return self.end - self.start

    def GetName(self):
        return self.name

    def GetMediaPoolItem(self):
        return self.media

    def GetClipEnabled(self):
        return True

    def GetProperty(self):
        return {"CropBottom": self.crop}

    def GetLinkedItems(self):
        return list(self.links)

    def GetLeftOffset(self):
        return self.left_offset

    def GetRightOffset(self):
        return self.right_offset

    def GetSourceStartFrame(self):
        return self.source_start

    def GetSourceEndFrame(self):
        return self.source_start + self.GetDuration()

    def GetUniqueId(self):
        return f"item-{id(self)}"


class FakeRemoteProxyView:
    """A distinct Python wrapper for the same stable Resolve item UID."""

    def __init__(self, target: FakeItem) -> None:
        self.target = target

    def GetUniqueId(self):
        return self.target.GetUniqueId()


class FakeTimeline:
    def __init__(self, name: str, uid: str, tracks: dict[tuple[str, int], list[FakeItem]]) -> None:
        self.name = name
        self.uid = uid
        self.tracks = tracks
        self.settings = {
            "timelineResolutionWidth": "3840",
            "timelineResolutionHeight": "2160",
            "timelineFrameRate": "60",
            "timelinePlaybackFrameRate": "60",
        }
        self.track_names = {1: "Dialogue", 2: "BGM", 3: "Outro"}

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid

    def GetStartFrame(self):
        return START

    def GetSetting(self, key):
        return self.settings.get(key)

    def GetTrackCount(self, kind):
        return max((index for (track_kind, index) in self.tracks if track_kind == kind), default=0)

    def GetItemListInTrack(self, kind, index):
        return list(self.tracks.get((kind, index), []))

    def GetTrackName(self, kind, index):
        return self.track_names.get(index, "") if kind == "audio" else ""

    def SetTrackName(self, kind, index, name):
        if kind != "audio" or index < 1 or index > self.GetTrackCount("audio"):
            return False
        self.track_names[index] = name
        return True

    def AddTrack(self, kind, *_args):
        index = self.GetTrackCount(kind) + 1
        self.tracks[(kind, index)] = []
        return True

    def DeleteTrack(self, kind, index):
        if self.tracks.get((kind, index)):
            return False
        self.tracks.pop((kind, index), None)
        if kind == "audio":
            self.track_names.pop(index, None)
        return True

    def DeleteClips(self, items, ripple):
        if ripple:
            return False
        targets = set(items)
        for key, values in list(self.tracks.items()):
            self.tracks[key] = [item for item in values if item not in targets]
        return True

    def SetClipsLinked(self, items, linked):
        if not linked or len(items) != 2:
            return False
        items[0].links = [items[1]]
        items[1].links = [items[0]]
        return True


class FakeTimelineNoneLinkReturn(FakeTimeline):
    def SetClipsLinked(self, items, linked):
        super().SetClipsLinked(items, linked)
        return None


class FakeTimelinePretendLink(FakeTimeline):
    def SetClipsLinked(self, _items, _linked):
        return True


class FakeFolder:
    def __init__(self, items):
        self.items = items

    def GetClipList(self):
        return list(self.items)

    def GetSubFolderList(self):
        return []


class FakePool:
    def __init__(self, project, timeline: FakeTimeline) -> None:
        self.project = project
        self.timeline = timeline
        self.import_calls = 0
        by_path = {}
        for values in timeline.tracks.values():
            for item in values:
                by_path.setdefault(item.media.path.casefold(), item.media)
        self.folder = FakeFolder(list(by_path.values()))
        self.current_folder = self.folder

    def ImportTimelineFromFile(self, _path, options):
        self.import_calls += 1
        if options.get("timelineName") != self.timeline.name:
            return None
        self.project.timelines.append(self.timeline)
        return self.timeline

    def GetRootFolder(self):
        return self.folder

    def GetCurrentFolder(self):
        return self.current_folder

    def SetCurrentFolder(self, folder):
        self.current_folder = folder
        return True

    def ImportMedia(self, _paths):
        return []

    def AppendToTimeline(self, specs):
        timeline = self.project.current
        if timeline is None:
            return []
        placed = []
        for spec in specs:
            media = spec["mediaPoolItem"]
            source_start = int(spec.get("startFrame", 0))
            duration = int(spec.get("endFrame", media.duration)) - source_start
            start = int(spec["recordFrame"])
            item = FakeItem(
                media.GetName(),
                start,
                start + duration,
                media.path,
                source_start=source_start,
                media=media,
            )
            timeline.tracks.setdefault(("audio", int(spec["trackIndex"])), []).append(item)
            placed.append(item)
        return placed


class FakeProject:
    def __init__(self, name: str, timeline: FakeTimeline) -> None:
        self.name = name
        self.uid = "project-uid"
        self.timelines: list[FakeTimeline] = []
        self.pool = FakePool(self, timeline)
        self.current = None
        self.fairlight_apply_calls = 0
        self.fairlight_apply_result = True
        self.call_order: list[str] = []

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index):
        return self.timelines[index - 1]

    def GetMediaPool(self):
        return self.pool

    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        return True

    def GetCurrentTimeline(self):
        return self.current

    def ApplyFairlightPresetToCurrentTimeline(self, preset):
        self.call_order.append("fairlight_apply")
        self.fairlight_apply_calls += 1
        if preset != "Standard Gameplay youtube" or self.current is None:
            return False
        return self.fairlight_apply_result


class FakeProjectRejectSelection(FakeProject):
    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        return False


class FakeManager:
    def __init__(self, project: FakeProject) -> None:
        self.project = project
        self.save_calls = 0
        self.save_result = True

    def GetCurrentProject(self):
        return self.project

    def SaveProject(self):
        self.project.call_order.append("save")
        self.save_calls += 1
        return self.save_result


class FakeResolve:
    def __init__(self, manager: FakeManager) -> None:
        self.manager = manager

    def GetProjectManager(self):
        return self.manager


def manifest() -> dict:
    a2_segments = [
        {
            "record_range": [0, 600],
            "source_range": [764, 1_364],
            "asset": {
                "path": "F:/music/nonbattle/Dual Screen Lovelife.mp3",
                "origin_path": "F:/music/nonbattle/Dual Screen Lovelife.mp3",
                "name": "Dual Screen Lovelife.mp3",
                "source_start_frame": 0,
                "duration_frames": 5_000,
            },
            "media_source_range": [0, 5_000],
            "available_handle_frames": {"left": 764, "right": 3_636},
            "source_trim_handles_editable": True,
            "role": "opening",
            "label": "opening bed",
            "battle_id": None,
            "gain_db": -8.4,
            "gain_policy": "editable_timeline_adjust_volume_not_baked",
            "fade_in_frames": 0,
            "fade_out_frames": 0,
            "fade_policy": "editable_timeline_metadata_not_baked",
            "derived_media": False,
        },
        {
            "record_range": [600, 700],
            "source_range": [0, 100],
            "asset": {
                "path": "F:/music/nonbattle/Aura.mp3",
                "origin_path": "F:/music/nonbattle/Aura.mp3",
                "name": "Aura.mp3",
                "source_start_frame": 0,
                "duration_frames": 4_000,
            },
            "media_source_range": [0, 4_000],
            "available_handle_frames": {"left": 0, "right": 3_900},
            "source_trim_handles_editable": True,
            "role": "carousel",
            "label": "carousel bed",
            "battle_id": None,
            "gain_db": -4.5,
            "gain_policy": "editable_timeline_adjust_volume_not_baked",
            "fade_in_frames": 0,
            "fade_out_frames": 30,
            "fade_policy": "editable_timeline_metadata_not_baked",
            "derived_media": False,
        },
    ]
    source_clips = [
        {
            "schema": "gsc_a2_original_source_clip_v1",
            "record_range": list(row["record_range"]),
            "source_path": row["asset"]["path"],
            "source_name": row["asset"]["name"],
            "source_sha256": "A" * 64,
            "source_range": list(row["source_range"]),
            "media_source_start_frame": row["asset"]["source_start_frame"],
            "media_duration_frames": row["asset"]["duration_frames"],
            "media_source_end_frame": (
                row["asset"]["source_start_frame"]
                + row["asset"]["duration_frames"]
            ),
            "available_handle_frames": dict(row["available_handle_frames"]),
            "source_trim_handles_editable": True,
            "role": row["role"],
            "battle_id": row["battle_id"],
            "label": row["label"],
            "fade_in_frames": row["fade_in_frames"],
            "fade_out_frames": row["fade_out_frames"],
            "fade_policy": "editable_timeline_metadata_not_baked",
            "gain_db": row["gain_db"],
            "gain_policy": "editable_timeline_adjust_volume_not_baked",
            "derived_media": False,
        }
        for row in a2_segments
    ]
    return {
        "timeline": {"name": "Erika deterministic dry run", "start_frame": START},
        "source_asset": {"path": "F:/media/source.mp4"},
        "opening": {
            "record_range": [0, 260],
            "asset": {"path": "F:/assets/opening.mp4"},
        },
        "body_v1": [{"record_range": [260, 600]}],
        "battles": [
            {
                "intro_range": [300, 600],
                "intro_asset": {"path": "F:/assets/erika-intro.mov"},
            }
        ],
        "a1": {
            "dialogue_asset": {
                "path": "F:/media/dialogue.wav",
                "name": "dialogue.wav",
            },
            "placed": [{"record_range": [260, 540], "source_range": [20, 300]}],
        },
        "a2": {
            "source_contract": "original_library_media_v1",
            "derived_media_allowed": False,
            "renamed_timeline_clips_allowed": False,
            "source_trim_handles_editable": True,
            "segments": a2_segments,
        },
        "a2_original_source_clips": source_clips,
        "a2_contract_audit": {
            "schema": "gsc_a2_original_source_contract_v1",
            "status": "pass",
            "segment_count": len(a2_segments),
            "original_source_clip_count": len(source_clips),
            "materialized_derivative_count": 0,
            "derived_media_allowed": False,
            "renamed_media_allowed": False,
            "source_trim_handles_editable": True,
            "source_clips": source_clips,
        },
        "carousel": {
            "v1_record_range": [600, 700],
            "v2_slices": [
                {"record_range": [600, 650]},
                {"record_range": [650, 700]},
            ],
        },
        "outro": {
            "record_range": [700, 800],
            "asset": {
                "path": "F:/assets/outro.mov",
                "name": "outro.mov",
                "duration_frames": 100,
            },
        },
        "audio_reservations": {
            "dual_screen_lovelife": "F:/music/nonbattle/Dual Screen Lovelife.mp3",
            "battle_library_root": "F:/music/battle",
        },
        "media_pool_bins": {
            "schema": "gsc_gym_media_pool_bin_inputs_v1",
            "project_dir": "F:/media",
            "nonbattle_bgm_dir": "F:/music/nonbattle",
            "battle_bgm_dir": "F:/music/battle",
            "intro_manifest_path": "F:/assets/intros/manifest.json",
            "opening_intro_path": "F:/assets/opening.mp4",
            "outro_path": "F:/assets/outro.mov",
            "full_reusable_library": True,
            "timeline_creation_count": 0,
        },
    }


def timeline_for(payload: dict, *, linked: bool = True, crop: float = 530.0) -> FakeTimeline:
    def item(name, bounds, path, **kwargs):
        return FakeItem(name, START + bounds[0], START + bounds[1], path, **kwargs)

    video_outro = item("outro", [700, 800], "F:/assets/outro.mov")
    audio_outro = item("outro audio", [700, 800], "F:/assets/outro.mov")
    if linked:
        video_outro.links = [audio_outro]
        audio_outro.links = [video_outro]
    tracks = {
        ("video", 1): [
            item("opening", [0, 260], "F:/assets/opening.mp4"),
            item("body", [260, 600], "F:/media/source.mp4"),
            item("carousel bed", [600, 700], "F:/media/source.mp4"),
            video_outro,
        ],
        ("video", 2): [
            item("intro", [300, 600], "F:/assets/erika-intro.mov"),
            item("carousel 1", [600, 650], "F:/media/source.mp4", crop=crop),
            item("carousel 2", [650, 700], "F:/media/source.mp4", crop=crop),
        ],
        ("audio", 1): [item("dialogue", [260, 540], "F:/media/dialogue.wav", source_start=20)],
        ("audio", 2): [
            item(
                "Dual Screen Lovelife.mp3",
                [0, 600],
                "F:/music/nonbattle/Dual Screen Lovelife.mp3",
                source_start=764,
                media=FakeMedia(
                    "F:/music/nonbattle/Dual Screen Lovelife.mp3", 5_000
                ),
            ),
            item(
                "Aura.mp3",
                [600, 700],
                "F:/music/nonbattle/Aura.mp3",
                media=FakeMedia("F:/music/nonbattle/Aura.mp3", 4_000),
            ),
        ],
        ("audio", 3): [audio_outro],
    }
    return FakeTimeline(payload["timeline"]["name"], "timeline-uid", tracks)


class GscGymResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organize_calls = 0
        self.fairlight_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.fairlight_temp.cleanup)
        fairlight_root = Path(self.fairlight_temp.name)
        self.repo_preset = fairlight_root / "repo" / "Standard Gameplay youtube.dat"
        self.host_preset = fairlight_root / "host" / "Standard Gameplay youtube.dat"
        self.repo_preset.parent.mkdir(parents=True)
        self.repo_preset.write_bytes(b"deterministic-fairlight-preset")

        def fake_organize(project, *, newest_timeline_name, **_kwargs):
            self.organize_calls += 1
            project.call_order.append("media_pool_organize")
            timeline = next(
                value
                for value in project.timelines
                if value.GetName() == newest_timeline_name
            )
            return {
                "schema": "gsc_gym_media_pool_bins_v1",
                "status": "pass",
                "project_uid": project.GetUniqueId(),
                "newest_timeline": {
                    "name": newest_timeline_name,
                    "timeline_uid": timeline.GetUniqueId(),
                },
                "asset_contract": {
                    "schema": "gsc_gym_reusable_asset_contract_v1",
                    "required_asset_count": 201,
                    "intro_library": {
                        "category_counts": {"leader": 16, "rival": 21}
                    },
                    "bgm_libraries": {"combined_file_count": 162},
                    "show_assets": [{"role": "opening_4x"}, {"role": "outro"}],
                },
                "timeline_creation_count": 0,
                "live_audit": {"status": "pass"},
            }

        def fake_audit(_project, _report, **_kwargs):
            _project.call_order.append("media_pool_audit")
            return {"status": "pass", "failed_checks": []}

        self.organize_patcher = patch(
            "resolve_mcp.orchestrator.gsc_gym_resolve.organize_media_pool",
            side_effect=fake_organize,
        )
        self.audit_bins_patcher = patch(
            "resolve_mcp.orchestrator.gsc_gym_resolve.audit_media_pool_organization",
            side_effect=fake_audit,
        )
        self.fairlight_paths_patcher = patch(
            "resolve_mcp.orchestrator.gsc_gym_resolve._fairlight_preset_paths",
            return_value=(self.repo_preset.resolve(), self.host_preset.resolve()),
        )
        self.organize_patcher.start()
        self.audit_bins_patcher.start()
        self.fairlight_paths_patcher.start()
        self.addCleanup(self.organize_patcher.stop)
        self.addCleanup(self.audit_bins_patcher.stop)
        self.addCleanup(self.fairlight_paths_patcher.stop)

    def test_live_audit_proves_exact_geometry_crop_and_link(self) -> None:
        payload = manifest()
        audit = audit_live_timeline(timeline_for(payload), payload)
        self.assertEqual(audit["status"], "pass")
        self.assertEqual(audit["passed_count"], audit["check_count"])

    def test_audio_plan_uses_original_names_ranges_and_rejects_derivatives(self) -> None:
        payload = manifest()
        plan = build_audio_placement_plan(payload)
        a2 = [row for row in plan if row.track_index == 2]
        self.assertEqual(
            [row.source_name for row in a2],
            ["Dual Screen Lovelife.mp3", "Aura.mp3"],
        )
        self.assertEqual(
            [[row.source_start, row.source_end] for row in a2],
            [[764, 1_364], [0, 100]],
        )
        self.assertEqual(
            [[row.left_handle, row.right_handle] for row in a2],
            [[764, 3_636], [0, 3_900]],
        )
        self.assertTrue(all(row.original_source for row in a2))

        forbidden = deepcopy(payload)
        forbidden["a2_fade_derivatives"] = []
        with self.assertRaisesRegex(
            GscGymResolveAudioError, "forbidden rendered fade derivatives"
        ):
            build_audio_placement_plan(forbidden)

        renamed = deepcopy(payload)
        renamed["a2"]["segments"][0]["asset"]["path"] = (
            "F:/build/a2-fades/Dual_Screen__s764_d600.wav"
        )
        with self.assertRaisesRegex(GscGymResolveAudioError, "renamed or rendered"):
            build_audio_placement_plan(renamed)

    def test_live_a2_audit_uses_source_getters_and_exact_trim_handles(self) -> None:
        payload = manifest()
        segment = payload["a2"]["segments"][0]
        segment["asset"]["source_start_frame"] = 752
        segment["asset"]["duration_frames"] = 4_248
        segment["media_source_range"] = [752, 5_000]
        segment["available_handle_frames"] = {"left": 12, "right": 3_636}
        source_clip = payload["a2_original_source_clips"][0]
        source_clip["media_source_start_frame"] = 752
        source_clip["media_duration_frames"] = 4_248
        source_clip["media_source_end_frame"] = 5_000
        source_clip["available_handle_frames"] = {"left": 12, "right": 3_636}
        payload["a2_contract_audit"]["source_clips"] = payload[
            "a2_original_source_clips"
        ]
        timeline = timeline_for(payload)
        opening = timeline.tracks[("audio", 2)][0]
        opening.left_offset = 12
        opening.right_offset = 3_636
        opening.source_start = 764

        report = audit_audio_placement(
            timeline,
            build_audio_placement_plan(payload),
        )

        self.assertEqual(report["status"], "pass")
        actual = next(
            row["evidence"]["actual"][0]
            for row in report["checks"]
            if row["name"] == "exact_a2_scripting_inventory"
        )
        self.assertEqual(actual["source_range"], [764, 1_364])
        self.assertEqual(
            actual["available_handle_frames"],
            {"left": 12, "right": 3_636},
        )

    def test_live_a2_audit_rejects_visible_timeline_clip_rename(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        timeline.tracks[("audio", 2)][0].name = "renamed timeline clip"

        report = audit_audio_placement(
            timeline,
            build_audio_placement_plan(payload),
        )

        self.assertEqual(report["status"], "fail")
        self.assertIn("exact_a2_scripting_inventory", report["failed_checks"])

    def test_live_audit_rejects_bad_crop_and_unlinked_outro(self) -> None:
        payload = manifest()
        audit = audit_live_timeline(timeline_for(payload, linked=False, crop=529.0), payload)
        self.assertEqual(audit["status"], "fail")
        self.assertIn("carousel_crop_bottom_only_contract", audit["failed_checks"])
        self.assertIn("outro_v1_a3_link_state", audit["failed_checks"])

    def test_live_audit_accepts_fresh_remote_proxies_for_linked_outro(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        video = timeline.tracks[("video", 1)][-1]
        audio = timeline.tracks[("audio", 3)][0]
        video.links = [FakeRemoteProxyView(audio)]
        audio.links = [FakeRemoteProxyView(video)]
        audit = audit_live_timeline(timeline, payload)
        self.assertEqual(audit["status"], "pass")

    def test_audio_repair_accepts_none_link_return_when_uid_postcondition_passes(self) -> None:
        payload = manifest()
        original = timeline_for(payload, linked=False)
        timeline = FakeTimelineNoneLinkReturn(original.name, original.uid, original.tracks)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        report = repair_receipt_bound_audio(
            project=project,
            timeline=timeline,
            manifest=payload,
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["outro_link_mutation"])

    def test_audio_repair_rejects_true_return_without_uid_link_postcondition(self) -> None:
        payload = manifest()
        original = timeline_for(payload, linked=False)
        timeline = FakeTimelinePretendLink(original.name, original.uid, original.tracks)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        with self.assertRaisesRegex(RuntimeError, "link postcondition"):
            repair_receipt_bound_audio(
                project=project,
                timeline=timeline,
                manifest=payload,
            )

    def test_receipt_prevents_second_import_and_repairs_swapped_audio_tracks(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload, linked=False)
        timeline.tracks[("audio", 1)], timeline.tracks[("audio", 2)] = (
            timeline.tracks[("audio", 2)],
            timeline.tracks[("audio", 1)],
        )
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        manager = FakeManager(project)
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            payload["fcpxml_sha256"] = hashlib.sha256(fcpxml.read_bytes()).hexdigest().upper()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path = root / "receipt.json"
            first = run_resolve_dry_run(
                resolve=resolve,
                fcpxml_path=fcpxml,
                manifest_path=manifest_path,
                manifest=payload,
                receipt_path=receipt_path,
                expected_project_name="Erika Crystal Gym Leader Challenge",
            )
            first_call_order = list(project.call_order)
            second = run_resolve_dry_run(
                resolve=resolve,
                fcpxml_path=fcpxml,
                manifest_path=manifest_path,
                manifest=payload,
                receipt_path=receipt_path,
                expected_project_name="Erika Crystal Gym Leader Challenge",
            )
        self.assertEqual(first["status"], "pass")
        self.assertTrue(first["outro_link_mutation"])
        self.assertEqual(
            first["audio_scripting_placement"]["mode"],
            "rebuilt_with_scripting_api",
        )
        self.assertEqual(first["audio_scripting_placement"]["placed_audio_item_count"], 4)
        self.assertEqual(
            second["audio_scripting_placement"]["mode"],
            "reused_exact_live_population",
        )
        self.assertEqual(second["timeline_uid"], "timeline-uid")
        self.assertEqual(project.pool.import_calls, 1)
        self.assertEqual(self.organize_calls, 1)
        self.assertEqual(first["media_pool_bins"]["required_reusable_asset_count"], 201)
        self.assertEqual(first["media_pool_bins"]["leader_intro_count"], 16)
        self.assertEqual(first["media_pool_bins"]["rival_intro_count"], 21)
        self.assertEqual(
            second["media_pool_bins"]["mode"],
            "reused_exact_bound_report",
        )
        self.assertEqual(first["fairlight_preset"]["current_run_apply_count"], 1)
        self.assertEqual(second["fairlight_preset"]["current_run_apply_count"], 0)
        self.assertEqual(second["fairlight_apply_count"], 1)
        self.assertEqual(project.fairlight_apply_calls, 1)
        self.assertEqual(
            first_call_order,
            [
                "media_pool_organize",
                "media_pool_audit",
                "fairlight_apply",
                "save",
            ],
        )
        self.assertEqual(manager.save_calls, 1)

    def test_receipt_rejects_fcpxml_not_bound_by_manifest(self) -> None:
        payload = manifest()
        payload["fcpxml_sha256"] = "0" * 64
        timeline = timeline_for(payload)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        manager = FakeManager(project)
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "not bound"):
                run_resolve_dry_run(
                    resolve=resolve,
                    fcpxml_path=fcpxml,
                    manifest_path=manifest_path,
                    manifest=payload,
                    receipt_path=root / "receipt.json",
                    expected_project_name="Erika Crystal Gym Leader Challenge",
                )
        self.assertEqual(project.pool.import_calls, 0)
        self.assertEqual(manager.save_calls, 0)

    def test_receipt_records_import_before_later_selection_failure(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        project = FakeProjectRejectSelection("Erika Crystal Gym Leader Challenge", timeline)
        manager = FakeManager(project)
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            payload["fcpxml_sha256"] = hashlib.sha256(fcpxml.read_bytes()).hexdigest().upper()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path = root / "receipt.json"
            with self.assertRaisesRegex(RuntimeError, "could not select"):
                run_resolve_dry_run(
                    resolve=resolve,
                    fcpxml_path=fcpxml,
                    manifest_path=manifest_path,
                    manifest=payload,
                    receipt_path=receipt_path,
                    expected_project_name="Erika Crystal Gym Leader Challenge",
                )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(project.pool.import_calls, 1)
        self.assertEqual(receipt["editorial_import_count"], 1)
        self.assertEqual(receipt["status"], "import_returned_pending_identity_validation")

    def test_pending_receipt_adopts_exact_sole_import_as_one_not_zero(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        project.timelines.append(timeline)
        manager = FakeManager(project)
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            payload["fcpxml_sha256"] = hashlib.sha256(fcpxml.read_bytes()).hexdigest().upper()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path = root / "receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema": "gsc_gym_resolve_dry_run_receipt_v1",
                        "status": "pending_import",
                        "project_name": "Erika Crystal Gym Leader Challenge",
                        "project_uid": "project-uid",
                        "timeline_name": payload["timeline"]["name"],
                        "timeline_uid": None,
                        "fcpxml_sha256": hashlib.sha256(fcpxml.read_bytes()).hexdigest().upper(),
                        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest().upper(),
                        "timeline_inventory_before_import": [],
                        "editorial_import_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            recovered = run_resolve_dry_run(
                resolve=resolve,
                fcpxml_path=fcpxml,
                manifest_path=manifest_path,
                manifest=payload,
                receipt_path=receipt_path,
                expected_project_name="Erika Crystal Gym Leader Challenge",
            )
        self.assertEqual(recovered["status"], "pass")
        self.assertEqual(recovered["editorial_import_count"], 1)
        self.assertEqual(project.pool.import_calls, 0)

    def test_fairlight_apply_failure_cannot_save_or_pass(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        project.fairlight_apply_result = False
        manager = FakeManager(project)
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            payload["fcpxml_sha256"] = hashlib.sha256(
                fcpxml.read_bytes()
            ).hexdigest().upper()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path = root / "receipt.json"
            with self.assertRaisesRegex(RuntimeError, "returned False"):
                run_resolve_dry_run(
                    resolve=resolve,
                    fcpxml_path=fcpxml,
                    manifest_path=manifest_path,
                    manifest=payload,
                    receipt_path=receipt_path,
                    expected_project_name="Erika Crystal Gym Leader Challenge",
                )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed_fairlight_apply")
        self.assertEqual(project.fairlight_apply_calls, 1)
        self.assertEqual(manager.save_calls, 0)
        self.assertFalse(resolve_receipt_deployment_ready(receipt))

    def test_failed_save_recovers_without_reapplying_fairlight(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        manager = FakeManager(project)
        manager.save_result = False
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            payload["fcpxml_sha256"] = hashlib.sha256(
                fcpxml.read_bytes()
            ).hexdigest().upper()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path = root / "receipt.json"
            report_path = root / "fairlight.json"
            with self.assertRaisesRegex(RuntimeError, "already-applied"):
                run_resolve_dry_run(
                    resolve=resolve,
                    fcpxml_path=fcpxml,
                    manifest_path=manifest_path,
                    manifest=payload,
                    receipt_path=receipt_path,
                    fairlight_report_path=report_path,
                    expected_project_name="Erika Crystal Gym Leader Challenge",
                )
            pending = json.loads(receipt_path.read_text(encoding="utf-8"))
            pending_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(pending["status"], "fairlight_applied_pending_save")
            self.assertEqual(pending_report["status"], "applied_pending_save")
            manager.save_result = True
            recovered = run_resolve_dry_run(
                resolve=resolve,
                fcpxml_path=fcpxml,
                manifest_path=manifest_path,
                manifest=payload,
                receipt_path=receipt_path,
                fairlight_report_path=report_path,
                expected_project_name="Erika Crystal Gym Leader Challenge",
            )
            deployment_ready = resolve_receipt_deployment_ready(recovered)
        self.assertTrue(deployment_ready)
        self.assertEqual(
            recovered["fairlight_preset"]["mode"],
            "saved_existing_applied_report_without_reapply",
        )
        self.assertEqual(project.fairlight_apply_calls, 1)
        self.assertEqual(manager.save_calls, 2)

    def test_legacy_pass_without_fairlight_upgrades_exact_uid_in_place(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        project.timelines.append(timeline)
        project.current = timeline
        manager = FakeManager(project)
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            payload["fcpxml_sha256"] = hashlib.sha256(
                fcpxml.read_bytes()
            ).hexdigest().upper()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path = root / "receipt.json"
            inventory = [
                {"index": 1, "name": timeline.GetName(), "uid": timeline.GetUniqueId()}
            ]
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema": "gsc_gym_resolve_dry_run_receipt_v1",
                        "status": "pass",
                        "project_name": project.GetName(),
                        "project_uid": project.GetUniqueId(),
                        "timeline_name": timeline.GetName(),
                        "timeline_uid": timeline.GetUniqueId(),
                        "fcpxml_sha256": payload["fcpxml_sha256"],
                        "manifest_sha256": hashlib.sha256(
                            manifest_path.read_bytes()
                        ).hexdigest().upper(),
                        "timeline_inventory_before_import": [],
                        "timeline_inventory_after_import": inventory,
                        "editorial_import_count": 1,
                        "project_saved": True,
                    }
                ),
                encoding="utf-8",
            )
            upgraded = run_resolve_dry_run(
                resolve=resolve,
                fcpxml_path=fcpxml,
                manifest_path=manifest_path,
                manifest=payload,
                receipt_path=receipt_path,
                expected_project_name="Erika Crystal Gym Leader Challenge",
            )
            deployment_ready = resolve_receipt_deployment_ready(upgraded)
        self.assertTrue(deployment_ready)
        self.assertEqual(upgraded["timeline_uid"], timeline.GetUniqueId())
        self.assertEqual(project.pool.import_calls, 0)
        self.assertEqual(project.fairlight_apply_calls, 1)
        self.assertEqual(manager.save_calls, 1)

    def test_top_level_pass_without_fairlight_is_not_deployment_ready(self) -> None:
        self.assertFalse(
            resolve_receipt_deployment_ready(
                {
                    "schema": "gsc_gym_resolve_dry_run_receipt_v1",
                    "status": "pass",
                    "project_saved": True,
                }
            )
        )

    def test_completed_fairlight_receipt_forbids_later_audio_repair(self) -> None:
        payload = manifest()
        timeline = timeline_for(payload)
        project = FakeProject("Erika Crystal Gym Leader Challenge", timeline)
        manager = FakeManager(project)
        resolve = FakeResolve(manager)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fcpxml = root / "final.fcpxml"
            fcpxml.write_text("<fcpxml/>", encoding="utf-8")
            payload["fcpxml_sha256"] = hashlib.sha256(
                fcpxml.read_bytes()
            ).hexdigest().upper()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path = root / "receipt.json"
            first = run_resolve_dry_run(
                resolve=resolve,
                fcpxml_path=fcpxml,
                manifest_path=manifest_path,
                manifest=payload,
                receipt_path=receipt_path,
                expected_project_name="Erika Crystal Gym Leader Challenge",
            )
            self.assertTrue(resolve_receipt_deployment_ready(first))
            timeline.tracks[("audio", 1)] = []
            with self.assertRaisesRegex(RuntimeError, "forbids any later audio mutation"):
                run_resolve_dry_run(
                    resolve=resolve,
                    fcpxml_path=fcpxml,
                    manifest_path=manifest_path,
                    manifest=payload,
                    receipt_path=receipt_path,
                    expected_project_name="Erika Crystal Gym Leader Challenge",
                )
        self.assertEqual(project.fairlight_apply_calls, 1)
        self.assertEqual(manager.save_calls, 1)


if __name__ == "__main__":
    unittest.main()
