from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_deterministic import (
    GscGymDeterministicError,
    build_overlay_intro_plan,
)
from resolve_mcp.orchestrator.gsc_gym_intro_library import (
    EXPECTED_MASTER_MEDIA,
    EXPECTED_TECHNICAL_CONTRACT,
    GscGymIntroLibraryError,
    INTRO_LIBRARY_SCHEMA,
    load_gsc_gym_intro_library,
)


class GscGymIntroLibraryTests(unittest.TestCase):
    @staticmethod
    def _variant(
        root: Path,
        *,
        variant_id: str,
        category: str,
        relative_path: str,
        payload: bytes,
    ) -> dict:
        path = root / Path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {
            "variant_id": variant_id,
            "category": category,
            "master_path": relative_path.replace("\\", "/"),
            "master_bytes": len(payload),
            "master_sha256": hashlib.sha256(payload).hexdigest().upper(),
            "media": dict(EXPECTED_MASTER_MEDIA),
            "qa_status": "pass",
        }

    @staticmethod
    def _write_manifest(root: Path, variants: list[dict]) -> Path:
        path = root / "LIBRARY-MANIFEST.json"
        path.write_text(
            json.dumps(
                {
                    "schema": INTRO_LIBRARY_SCHEMA,
                    "status": "pass",
                    "library_root": str(root.resolve()),
                    "technical_contract": dict(EXPECTED_TECHNICAL_CONTRACT),
                    "variants": variants,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_selected_master_is_exactly_hash_and_contract_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            variant = self._variant(
                root,
                variant_id="silver-initial-cyndaquil",
                category="rival",
                relative_path="01 Resolve-Ready Masters/Rivals/"
                "silver-initial-cyndaquil-battle-intro.mov",
                payload=b"approved-cyndaquil-master",
            )
            manifest = self._write_manifest(root, [variant])

            resolved = load_gsc_gym_intro_library(manifest).resolve(
                "silver-initial-cyndaquil",
                expected_category="rival",
            )

            self.assertEqual(resolved.path.read_bytes(), b"approved-cyndaquil-master")
            evidence = resolved.approval_evidence()
            self.assertEqual(evidence["status"], "pass")
            self.assertEqual(evidence["master_sha256"], variant["master_sha256"])
            self.assertRegex(evidence["library_manifest_sha256"], r"^[0-9A-F]{64}$")

    def test_selected_master_fails_closed_on_hash_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            variant = self._variant(
                root,
                variant_id="falkner",
                category="leader",
                relative_path="01 Resolve-Ready Masters/Johto Leaders/"
                "falkner-battle-intro.mov",
                payload=b"approved-falkner-master",
            )
            manifest = self._write_manifest(root, [variant])
            master = root / variant["master_path"]
            master.write_bytes(b"unapproved-falkner")
            variant["master_bytes"] = len(b"unapproved-falkner")
            self._write_manifest(root, [variant])

            with self.assertRaisesRegex(GscGymIntroLibraryError, "SHA-256 changed"):
                load_gsc_gym_intro_library(manifest).resolve(
                    "falkner",
                    expected_category="leader",
                )

    def test_manifest_and_selected_media_contracts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            variant = self._variant(
                root,
                variant_id="falkner",
                category="leader",
                relative_path="masters/falkner-battle-intro.mov",
                payload=b"falkner",
            )
            manifest = self._write_manifest(root, [variant])
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["technical_contract"]["frames"] = 299
            manifest.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(GscGymIntroLibraryError, "technical_contract"):
                load_gsc_gym_intro_library(manifest)

            manifest = self._write_manifest(root, [variant])
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["variants"][0]["media"]["audio_stream_count"] = 1
            manifest.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(GscGymIntroLibraryError, "audio_stream_count"):
                load_gsc_gym_intro_library(manifest).resolve(
                    "falkner",
                    expected_category="leader",
                )

    def test_master_path_may_not_escape_declared_library_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            variant = {
                "variant_id": "falkner",
                "category": "leader",
                "master_path": "../falkner-battle-intro.mov",
                "master_bytes": 1,
                "master_sha256": "0" * 64,
                "media": dict(EXPECTED_MASTER_MEDIA),
                "qa_status": "pass",
            }
            manifest = self._write_manifest(root, [variant])
            with self.assertRaisesRegex(GscGymIntroLibraryError, "escapes library_root"):
                load_gsc_gym_intro_library(manifest).resolve(
                    "falkner",
                    expected_category="leader",
                )

    def test_overlay_plan_uses_exact_manifest_variants_and_deduplicates_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            variants = [
                self._variant(
                    root,
                    variant_id="falkner",
                    category="leader",
                    relative_path="masters/falkner-battle-intro.mov",
                    payload=b"falkner",
                ),
                self._variant(
                    root,
                    variant_id="silver-burnedtower-fire",
                    category="rival",
                    relative_path="masters/silver-burnedtower-fire-battle-intro.mov",
                    payload=b"burned-tower-fire",
                ),
            ]
            manifest = self._write_manifest(root, variants)
            battles = [
                {
                    "session_start_frame": 1_000,
                    "role": "leader",
                    "identity": "Falkner",
                    "checkpoint_key": "falkner",
                    "battle_key": "leader:falkner",
                    "trainer_class": "FALKNER",
                    "trainer_id": 1,
                },
                {
                    "session_start_frame": 2_000,
                    "role": "rival",
                    "identity": "Silver",
                    "battle_key": "RIVAL1:8",
                    "trainer_class": "RIVAL1",
                    "trainer_id": 8,
                },
                {
                    "session_start_frame": 3_000,
                    "role": "rival",
                    "identity": "Silver",
                    "battle_key": "RIVAL1:8",
                    "trainer_class": "RIVAL1",
                    "trainer_id": 8,
                },
            ]

            rows = build_overlay_intro_plan(
                battles,
                intro_library_manifest=manifest,
                boundary_is_final_timeline=False,
            )

            self.assertEqual(len(rows), 2)
            self.assertEqual(
                [row["asset_approval"]["variant_id"] for row in rows],
                ["falkner", "silver-burnedtower-fire"],
            )
            self.assertTrue(all(row["asset_approval"]["status"] == "pass" for row in rows))

    def test_manifest_and_legacy_directories_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(root, [])
            with self.assertRaisesRegex(GscGymDeterministicError, "either"):
                build_overlay_intro_plan(
                    [],
                    leaders_dir=root / "leaders",
                    rivals_dir=root / "rivals",
                    intro_library_manifest=manifest,
                    boundary_is_final_timeline=False,
                )


if __name__ == "__main__":
    unittest.main()
