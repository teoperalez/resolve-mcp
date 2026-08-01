import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from resolve_mcp.orchestrator.gsc_gym_bins import (
    EXPECTED_INTRO_CATEGORY_COUNTS,
    GscGymMediaPoolError,
    LIVE_AUDIT_SCHEMA,
    ORGANIZATION_SCHEMA,
    SHARED_BINS,
    TOP_LEVEL_BINS,
    audit_media_pool_organization,
    organize_media_pool,
)
from resolve_mcp.orchestrator.gsc_gym_intro_library import (
    EXPECTED_MASTER_MEDIA,
    EXPECTED_TECHNICAL_CONTRACT,
    INTRO_LIBRARY_SCHEMA,
)


class FakeTimeline:
    def __init__(self, name: str, uid: str) -> None:
        self.name = name
        self.uid = uid
        self.tracks: dict[str, list[list["FakeTimelineItem"]]] = {
            "video": [],
            "audio": [],
        }

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid

    def GetTrackCount(self, track_type: str):
        return len(self.tracks[track_type])

    def GetItemListInTrack(self, track_type: str, track_index: int):
        return list(self.tracks[track_type][track_index - 1])


class FakeTimelineItem:
    def __init__(self, name: str, media_pool_item: "FakeMediaPoolItem") -> None:
        self.name = name
        self.media_pool_item = media_pool_item

    def GetName(self):
        return self.name

    def GetMediaPoolItem(self):
        return self.media_pool_item


class FakeMediaPoolItem:
    serial = 0

    def __init__(
        self,
        name: str,
        *,
        item_type: str = "",
        file_path: str = "",
        uid: str | None = None,
    ) -> None:
        self.name = name
        self.item_type = item_type
        self.file_path = file_path
        type(self).serial += 1
        self.uid = uid or f"media-pool-item-{type(self).serial:04d}"

    def GetName(self):
        return self.name

    def GetClipProperty(self):
        return {"Type": self.item_type, "File Path": self.file_path}

    def GetUniqueId(self):
        return self.uid


class FakeFolder:
    def __init__(self, name: str) -> None:
        self.name = name
        self.items: list[FakeMediaPoolItem] = []
        self.children: list[FakeFolder] = []

    def GetName(self):
        return self.name

    def GetClipList(self):
        return list(self.items)

    def GetSubFolderList(self):
        return list(self.children)


class FakeMediaPool:
    def __init__(self) -> None:
        self.root = FakeFolder("Master")
        self.current_folder = self.root
        self.add_calls = 0
        self.move_calls = 0
        self.media_import_calls = 0
        self.media_import_arguments: list[list[str]] = []
        self.media_import_destinations: list[str] = []
        self.delete_calls = 0
        self.delete_clip_calls = 0
        self.deleted_clip_uids: list[str] = []

    def GetRootFolder(self):
        return self.root

    def GetCurrentFolder(self):
        return self.current_folder

    def SetCurrentFolder(self, folder: FakeFolder):
        self.current_folder = folder
        return True

    def AddSubFolder(self, parent: FakeFolder, name: str):
        self.add_calls += 1
        folder = FakeFolder(name)
        parent.children.append(folder)
        return folder

    def ImportMedia(self, paths: list[str]):
        self.media_import_calls += 1
        self.media_import_arguments.append(list(paths))
        self.media_import_destinations.append(self.current_folder.GetName())
        imported = []
        for value in paths:
            path = Path(value)
            item = FakeMediaPoolItem(
                path.name,
                item_type="Video" if path.suffix.casefold() == ".mov" else "Audio",
                file_path=str(path),
            )
            self.current_folder.items.append(item)
            imported.append(item)
        return imported

    def _remove(self, folder: FakeFolder, item: FakeMediaPoolItem) -> bool:
        if item in folder.items:
            folder.items.remove(item)
            return True
        return any(self._remove(child, item) for child in folder.children)

    def MoveClips(self, items: list[FakeMediaPoolItem], target: FakeFolder):
        self.move_calls += 1
        for item in items:
            if not self._remove(self.root, item):
                return False
            target.items.append(item)
        return True

    def DeleteClips(self, items: list[FakeMediaPoolItem]):
        self.delete_clip_calls += 1
        for item in items:
            if not self._remove(self.root, item):
                return False
            self.deleted_clip_uids.append(item.GetUniqueId())
        return True

    def DeleteFolders(self, folders: list[FakeFolder]):
        self.delete_calls += 1

        def remove(parent: FakeFolder, target: FakeFolder) -> bool:
            if target in parent.children:
                parent.children.remove(target)
                return True
            return any(remove(child, target) for child in parent.children)

        for folder in folders:
            if folder.items or folder.children or not remove(self.root, folder):
                return False
        return True


class FakeProject:
    def __init__(self, project_media: Path, preexisting_bgm: Path) -> None:
        self.uid = "gsc-project-uid"
        self.timelines = [
            FakeTimeline("Erika GSC GYM DETERMINISTIC", "timeline-newest-uid"),
            FakeTimeline("Erika Auto Editor", "timeline-original-uid"),
        ]
        self.media_pool = FakeMediaPool()
        self.media_pool.root.items.extend(
            [
                FakeMediaPoolItem(
                    "Erika GSC GYM DETERMINISTIC",
                    item_type="Timeline",
                ),
                FakeMediaPoolItem("Erika Auto Editor", item_type="Timeline"),
                FakeMediaPoolItem(
                    project_media.name,
                    item_type="Video + Audio",
                    file_path=str(project_media),
                ),
                FakeMediaPoolItem(
                    preexisting_bgm.name,
                    item_type="Audio",
                    file_path=str(preexisting_bgm),
                ),
            ]
        )

    def GetUniqueId(self):
        return self.uid

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index: int):
        return self.timelines[index - 1]

    def GetMediaPool(self):
        return self.media_pool


def _write_audio_library(root: Path, name: str, files: tuple[str, ...]) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    for index, filename in enumerate(files, start=1):
        path = directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes([index]))
    return directory


def _write_intro_manifest(root: Path) -> tuple[Path, list[Path]]:
    library = root / "Gen 2 Battle Intros"
    library.mkdir()
    variants = []
    paths: list[Path] = []
    category_rows = (
        ("leader", EXPECTED_INTRO_CATEGORY_COUNTS["leader"]),
        ("rival", EXPECTED_INTRO_CATEGORY_COUNTS["rival"]),
    )
    serial = 1
    for category, count in category_rows:
        directory_name = "Leaders" if category == "leader" else "Rivals"
        for index in range(count):
            variant_id = f"{category}-{index:02d}"
            relative = Path("01 Resolve-Ready Masters") / directory_name / (
                f"{variant_id}-battle-intro.mov"
            )
            path = library / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes([serial]))
            serial += 1
            paths.append(path.resolve())
            variants.append(
                {
                    "variant_id": variant_id,
                    "category": category,
                    "qa_status": "pass",
                    "master_path": str(relative).replace("\\", "/"),
                    "master_bytes": 1,
                    "master_sha256": f"{serial:064X}",
                    "media": dict(EXPECTED_MASTER_MEDIA),
                }
            )
    manifest = library / "LIBRARY-MANIFEST.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": INTRO_LIBRARY_SCHEMA,
                "status": "pass",
                "library_root": str(library.resolve()),
                "technical_contract": dict(EXPECTED_TECHNICAL_CONTRACT),
                "variants": variants,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # This physical file is deliberately outside the manifest.  The reusable
    # import must ignore it rather than broad-importing the directory.
    extra = library / "01 Resolve-Ready Masters" / "Rivals" / "unapproved.mov"
    extra.write_bytes(b"x")
    return manifest, paths


class GscGymBinsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project_dir = self.root / "Erika Project"
        self.project_dir.mkdir()
        self.project_media = self.project_dir / "Erika recording.mp4"
        self.project_media.write_bytes(b"video")
        self.nonbattle = _write_audio_library(
            self.root,
            "bgm",
            ("Dual Screen Lovelife.mp3", "Random Bed.mp3"),
        )
        self.battle = _write_audio_library(
            self.root,
            "Gen 2 battle audio",
            ("110 Battle Johto.mp3", "204 Battle Kanto.mp3"),
        )
        self.manifest, self.intro_paths = _write_intro_manifest(self.root)
        self.opening = self.root / "GSC Intro 4x.mp4"
        self.opening.write_bytes(b"intro")
        self.outro = self.root / "GSC Assets outro.mov"
        self.outro.write_bytes(b"outro")
        self.project = FakeProject(
            self.project_media,
            self.nonbattle / "Dual Screen Lovelife.mp3",
        )
        self.kwargs = {
            "newest_timeline_name": "Erika GSC GYM DETERMINISTIC",
            "project_dir": self.project_dir,
            "nonbattle_bgm_dir": self.nonbattle,
            "battle_bgm_dir": self.battle,
            "intro_manifest_path": self.manifest,
            "opening_intro_path": self.opening,
            "outro_path": self.outro,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_gamut_import_and_idempotent_rerun(self) -> None:
        first = organize_media_pool(self.project, **self.kwargs)
        self.assertEqual(ORGANIZATION_SCHEMA, first["schema"])
        self.assertEqual("pass", first["status"])
        self.assertEqual(0, first["timeline_creation_count"])
        self.assertEqual(4, first["imports"]["call_count"])
        # 37 intros + four library tracks + two show assets, with one BGM
        # already present in the project.
        self.assertEqual(42, first["imports"]["requested_count"])
        self.assertEqual(
            ["BGM", "Leader Intros", "Rival Intros", "Show Intros & Outros"],
            self.project.media_pool.media_import_destinations,
        )
        imported_paths = {
            str(Path(path).resolve())
            for call in self.project.media_pool.media_import_arguments
            for path in call
        }
        self.assertTrue(set(map(str, self.intro_paths)).issubset(imported_paths))
        self.assertNotIn(
            str(
                (
                    self.manifest.parent
                    / "01 Resolve-Ready Masters"
                    / "Rivals"
                    / "unapproved.mov"
                ).resolve()
            ),
            imported_paths,
        )
        live = first["live_audit"]
        self.assertEqual(LIVE_AUDIT_SCHEMA, live["schema"])
        self.assertEqual("pass", live["status"])
        self.assertEqual(
            16,
            live["required_asset_inventory"]["present_kind_counts"]["leader_intro"],
        )
        self.assertEqual(
            21,
            live["required_asset_inventory"]["present_kind_counts"]["rival_intro"],
        )
        self.assertEqual(
            list(TOP_LEVEL_BINS),
            first["layout"]["top_level"],
        )
        self.assertEqual(list(SHARED_BINS), first["layout"]["shared"])

        import_calls = self.project.media_pool.media_import_calls
        move_calls = self.project.media_pool.move_calls
        second = organize_media_pool(self.project, **self.kwargs)
        self.assertEqual("pass", second["status"])
        self.assertEqual(0, second["imports"]["call_count"])
        self.assertEqual(0, second["imports"]["requested_count"])
        self.assertEqual(import_calls, self.project.media_pool.media_import_calls)
        self.assertEqual(move_calls, self.project.media_pool.move_calls)
        read_only = audit_media_pool_organization(
            self.project,
            second,
            **self.kwargs,
        )
        self.assertEqual("pass", read_only["status"])

    def test_imported_unapproved_intro_path_fails_closed(self) -> None:
        unapproved = (
            self.manifest.parent
            / "01 Resolve-Ready Masters"
            / "Rivals"
            / "unapproved.mov"
        )
        self.project.media_pool.root.items.append(
            FakeMediaPoolItem(
                unapproved.name,
                item_type="Video",
                file_path=str(unapproved),
            )
        )
        with self.assertRaisesRegex(
            GscGymMediaPoolError,
            "unapproved/stale assets",
        ):
            organize_media_pool(self.project, **self.kwargs)
        self.assertEqual(0, self.project.media_pool.media_import_calls)

    def test_manifest_must_keep_exact_16_leader_21_rival_gamut(self) -> None:
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        payload["variants"][0]["category"] = "rival"
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(GscGymMediaPoolError, "category gamut changed"):
            organize_media_pool(self.project, **self.kwargs)

    def test_complete_rerun_makes_no_media_pool_mutation(self) -> None:
        report = organize_media_pool(self.project, **self.kwargs)
        counters = (
            self.project.media_pool.add_calls,
            self.project.media_pool.move_calls,
            self.project.media_pool.media_import_calls,
            self.project.media_pool.delete_calls,
        )
        audit = audit_media_pool_organization(
            self.project,
            report,
            **self.kwargs,
        )
        self.assertEqual("pass", audit["status"])
        self.assertEqual(
            counters,
            (
                self.project.media_pool.add_calls,
                self.project.media_pool.move_calls,
                self.project.media_pool.media_import_calls,
                self.project.media_pool.delete_calls,
            ),
        )

    @staticmethod
    def _child(parent: FakeFolder, name: str) -> FakeFolder:
        return next(folder for folder in parent.children if folder.name == name)

    def test_fcpxml_duplicate_keeps_referenced_item_and_deletes_only_unused(self) -> None:
        organize_media_pool(self.project, **self.kwargs)
        shared = self._child(self.project.media_pool.root, TOP_LEVEL_BINS[4])
        show = self._child(shared, SHARED_BINS[3])
        other = self._child(shared, SHARED_BINS[5])
        canonical = next(
            item
            for item in show.items
            if Path(item.file_path).resolve() == self.opening.resolve()
        )
        imported = FakeMediaPoolItem(
            self.opening.name,
            item_type="Video",
            file_path=str(self.opening.resolve()),
            uid="fcpxml-imported-opening",
        )
        other.items.append(imported)
        self.project.timelines[0].tracks["video"] = [
            [FakeTimelineItem("opening V1", imported)]
        ]

        report = organize_media_pool(self.project, **self.kwargs)

        self.assertEqual("pass", report["status"])
        self.assertEqual(1, report["deduplication"]["path_count"])
        self.assertEqual(1, report["deduplication"]["deleted_item_count"])
        self.assertEqual([canonical.GetUniqueId()], self.project.media_pool.deleted_clip_uids)
        self.assertIn(imported, show.items)
        self.assertNotIn(canonical, show.items)
        self.assertEqual(
            "fcpxml-imported-opening",
            report["deduplication"]["paths"][0]["retained_uid"],
        )
        self.assertTrue(
            report["deduplication"]["paths"][0]["retained_was_referenced"]
        )
        self.assertEqual(0, report["imports"]["requested_count"])

    def test_duplicate_items_referenced_by_two_uids_fail_closed(self) -> None:
        organize_media_pool(self.project, **self.kwargs)
        shared = self._child(self.project.media_pool.root, TOP_LEVEL_BINS[4])
        show = self._child(shared, SHARED_BINS[3])
        other = self._child(shared, SHARED_BINS[5])
        canonical = next(
            item
            for item in show.items
            if Path(item.file_path).resolve() == self.opening.resolve()
        )
        imported = FakeMediaPoolItem(
            self.opening.name,
            item_type="Video",
            file_path=str(self.opening.resolve()),
            uid="fcpxml-imported-opening-ambiguous",
        )
        other.items.append(imported)
        self.project.timelines[0].tracks["video"] = [[
            FakeTimelineItem("opening old reference", canonical),
            FakeTimelineItem("opening imported reference", imported),
        ]]

        with self.assertRaisesRegex(
            GscGymMediaPoolError,
            "Multiple duplicate Media Pool items are referenced",
        ):
            organize_media_pool(self.project, **self.kwargs)
        self.assertEqual(0, self.project.media_pool.delete_clip_calls)

    def test_duplicate_canonical_occurrences_fail_closed(self) -> None:
        organize_media_pool(self.project, **self.kwargs)
        shared = self._child(self.project.media_pool.root, TOP_LEVEL_BINS[4])
        show = self._child(shared, SHARED_BINS[3])
        show.items.append(
            FakeMediaPoolItem(
                self.opening.name,
                item_type="Video",
                file_path=str(self.opening.resolve()),
                uid="second-canonical-opening",
            )
        )
        with self.assertRaisesRegex(
            GscGymMediaPoolError,
            "exactly one existing canonical occurrence",
        ):
            organize_media_pool(self.project, **self.kwargs)
        self.assertEqual(0, self.project.media_pool.delete_clip_calls)


if __name__ == "__main__":
    unittest.main()
