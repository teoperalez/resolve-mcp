from __future__ import annotations

"""Manifest-backed access to the approved Gen 2 battle-intro masters.

The release manifest is the authority for both variant identity and media
bytes.  The workflow validates only the masters selected for the current run,
which keeps the check deterministic without hashing the complete 67 GB
library on every invocation.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


INTRO_LIBRARY_SCHEMA = "gsc_gen2_battle_intro_library_v2"
DEFAULT_GSC_INTRO_LIBRARY_MANIFEST = Path(
    "F:/GSC Assets/Gen 2 Battle Intros/LIBRARY-MANIFEST.json"
)

EXPECTED_TECHNICAL_CONTRACT: dict[str, Any] = {
    "container": "MOV",
    "codec": "Apple ProRes 4444",
    "pixel_format": "yuva444p12le",
    "alpha": "straight",
    "width": 3840,
    "height": 2160,
    "fps": 60,
    "frames": 300,
    "duration_sec": 5,
    "audio": "none",
    "final_frame": "fully transparent",
}

EXPECTED_MASTER_MEDIA: dict[str, Any] = {
    "codec_name": "prores",
    "profile": "4444",
    "pixel_format": "yuva444p12le",
    "width": 3840,
    "height": 2160,
    "frame_rate": "60/1",
    "frame_count": 300,
    "duration_sec": 5.0,
    "audio_stream_count": 0,
    "probe_verified": True,
    "global_flash_candidate_count": 0,
    "last_frame_fully_transparent": True,
    "straight_alpha_verified": True,
}


class GscGymIntroLibraryError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GscGymIntroLibraryError(f"{label} must be a JSON object.")
    return value


def _validate_exact_fields(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    label: str,
) -> None:
    mismatches = {
        key: {"expected": expected_value, "actual": actual.get(key)}
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
        or type(actual.get(key)) is not type(expected_value)
    }
    if mismatches:
        rendered = ", ".join(
            f"{key}={row['actual']!r} (expected {row['expected']!r})"
            for key, row in sorted(mismatches.items())
        )
        raise GscGymIntroLibraryError(f"{label} violates the approved contract: {rendered}.")


@dataclass(frozen=True)
class ResolvedGscGymIntroMaster:
    variant_id: str
    category: str
    path: Path
    master_bytes: int
    master_sha256: str
    manifest_path: Path
    manifest_sha256: str

    def approval_evidence(self) -> dict[str, Any]:
        return {
            "schema": "gsc_gym_intro_master_approval_v1",
            "status": "pass",
            "variant_id": self.variant_id,
            "category": self.category,
            "master_path": str(self.path),
            "master_bytes": self.master_bytes,
            "master_sha256": self.master_sha256,
            "library_manifest": str(self.manifest_path),
            "library_manifest_sha256": self.manifest_sha256,
            "technical_contract": dict(EXPECTED_TECHNICAL_CONTRACT),
        }


class GscGymIntroLibrary:
    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path.resolve()
        if not self.manifest_path.is_file():
            raise GscGymIntroLibraryError(
                f"Approved Gen 2 intro library manifest is missing: {self.manifest_path}"
            )
        try:
            manifest_bytes = self.manifest_path.read_bytes()
            payload = json.loads(manifest_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GscGymIntroLibraryError(
                f"Approved Gen 2 intro library manifest is unreadable: {self.manifest_path}"
            ) from exc
        self.payload = _require_object(payload, "Gen 2 intro library manifest")
        if self.payload.get("schema") != INTRO_LIBRARY_SCHEMA:
            raise GscGymIntroLibraryError(
                "Gen 2 intro library manifest has unsupported schema: "
                f"{self.payload.get('schema')!r}."
            )
        if self.payload.get("status") != "pass":
            raise GscGymIntroLibraryError("Gen 2 intro library manifest is not approved/pass.")

        declared_root = self.payload.get("library_root")
        if not isinstance(declared_root, str) or not declared_root.strip():
            raise GscGymIntroLibraryError("Gen 2 intro library manifest lacks library_root.")
        self.library_root = Path(declared_root).resolve()
        if self.library_root != self.manifest_path.parent.resolve():
            raise GscGymIntroLibraryError(
                "Gen 2 intro library manifest is not located at its declared library_root."
            )
        _validate_exact_fields(
            _require_object(
                self.payload.get("technical_contract"),
                "Gen 2 intro library technical_contract",
            ),
            EXPECTED_TECHNICAL_CONTRACT,
            label="Gen 2 intro library technical_contract",
        )

        variants = self.payload.get("variants")
        if not isinstance(variants, list) or not variants:
            raise GscGymIntroLibraryError("Gen 2 intro library manifest contains no variants.")
        self._variants: dict[str, dict[str, Any]] = {}
        for index, value in enumerate(variants):
            row = _require_object(value, f"Gen 2 intro library variants[{index}]")
            variant_id = row.get("variant_id")
            if not isinstance(variant_id, str) or not variant_id.strip():
                raise GscGymIntroLibraryError(
                    f"Gen 2 intro library variants[{index}] lacks variant_id."
                )
            if variant_id in self._variants:
                raise GscGymIntroLibraryError(
                    f"Gen 2 intro library repeats variant_id {variant_id!r}."
                )
            self._variants[variant_id] = row
        self.manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest().upper()
        self._resolved: dict[tuple[str, str], ResolvedGscGymIntroMaster] = {}

    def resolve(
        self,
        variant_id: str,
        *,
        expected_category: str,
    ) -> ResolvedGscGymIntroMaster:
        cache_key = (variant_id, expected_category)
        cached = self._resolved.get(cache_key)
        if cached is not None:
            return cached
        row = self._variants.get(variant_id)
        if row is None:
            raise GscGymIntroLibraryError(
                f"Approved Gen 2 intro variant is missing: {variant_id!r}."
            )
        category = row.get("category")
        if category != expected_category:
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} has category {category!r}; "
                f"expected {expected_category!r}."
            )
        if row.get("qa_status") != "pass":
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} is not approved/pass."
            )
        _validate_exact_fields(
            _require_object(row.get("media"), f"Gen 2 intro variant {variant_id!r} media"),
            EXPECTED_MASTER_MEDIA,
            label=f"Gen 2 intro variant {variant_id!r} media",
        )

        relative_value = row.get("master_path")
        if not isinstance(relative_value, str) or not relative_value.strip():
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} lacks master_path."
            )
        relative = Path(relative_value)
        if relative.is_absolute() or relative.drive:
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} master_path must be relative."
            )
        path = (self.library_root / relative).resolve()
        try:
            path.relative_to(self.library_root)
        except ValueError as exc:
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} escapes library_root."
            ) from exc
        if path.suffix.casefold() != ".mov" or not path.is_file():
            raise GscGymIntroLibraryError(
                f"Approved Gen 2 intro master is missing: {path}"
            )

        master_bytes = row.get("master_bytes")
        if isinstance(master_bytes, bool) or not isinstance(master_bytes, int) or master_bytes <= 0:
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} has invalid master_bytes."
            )
        actual_bytes = path.stat().st_size
        if actual_bytes != master_bytes:
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} byte count changed: "
                f"{actual_bytes} != {master_bytes}."
            )
        master_sha256 = row.get("master_sha256")
        if not isinstance(master_sha256, str) or re.fullmatch(
            r"[0-9A-Fa-f]{64}", master_sha256
        ) is None:
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} has invalid master_sha256."
            )
        expected_sha256 = master_sha256.upper()
        actual_sha256 = _sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise GscGymIntroLibraryError(
                f"Gen 2 intro variant {variant_id!r} SHA-256 changed: "
                f"{actual_sha256} != {expected_sha256}."
            )

        resolved = ResolvedGscGymIntroMaster(
            variant_id=variant_id,
            category=expected_category,
            path=path,
            master_bytes=master_bytes,
            master_sha256=expected_sha256,
            manifest_path=self.manifest_path,
            manifest_sha256=self.manifest_sha256,
        )
        self._resolved[cache_key] = resolved
        return resolved


def load_gsc_gym_intro_library(manifest_path: Path) -> GscGymIntroLibrary:
    return GscGymIntroLibrary(manifest_path)
