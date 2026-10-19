import json
from pathlib import Path
from typing import Any

from app.sections import EXTRACTION_SECTION_KEYS, initial_section_states
from app.schemas import SectionStatus, SectionsManifest


def _sections_dir(doc_dir: Path) -> Path:
    d = doc_dir / "sections"
    d.mkdir(parents=True, exist_ok=True)
    return d


def manifest_path(doc_dir: Path) -> Path:
    return _sections_dir(doc_dir) / "manifest.json"


def section_path(doc_dir: Path, key: str) -> Path:
    return _sections_dir(doc_dir) / f"{key}.json"


def read_manifest(doc_dir: Path) -> SectionsManifest | None:
    path = manifest_path(doc_dir)
    if not path.exists():
        return None
    return SectionsManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_manifest(doc_dir: Path, manifest: SectionsManifest) -> None:
    manifest_path(doc_dir).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def init_manifest(doc_dir: Path) -> SectionsManifest:
    manifest = SectionsManifest(sections={k: v for k, v in initial_section_states().items()})
    write_manifest(doc_dir, manifest)
    return manifest


def set_section_status(
    doc_dir: Path,
    key: str,
    status: SectionStatus,
    error: str | None = None,
) -> SectionsManifest:
    manifest = read_manifest(doc_dir) or init_manifest(doc_dir)
    manifest.sections[key] = status
    if error:
        manifest.section_errors[key] = error
    elif key in manifest.section_errors and status == SectionStatus.completed:
        manifest.section_errors.pop(key, None)
    write_manifest(doc_dir, manifest)
    return manifest


def write_section_payload(doc_dir: Path, key: str, payload: Any) -> None:
    path = section_path(doc_dir, key)
    if payload is None:
        path.write_text("null", encoding="utf-8")
    elif isinstance(payload, list):
        data = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in payload
        ]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    elif hasattr(payload, "model_dump"):
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_section_payload(doc_dir: Path, key: str) -> Any | None:
    path = section_path(doc_dir, key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def all_sections_complete(manifest: SectionsManifest) -> bool:
    for key in EXTRACTION_SECTION_KEYS:
        if manifest.sections.get(key) != SectionStatus.completed:
            return False
    return True


def section_is_done(manifest: SectionsManifest, key: str) -> bool:
    return manifest.sections.get(key) == SectionStatus.completed
