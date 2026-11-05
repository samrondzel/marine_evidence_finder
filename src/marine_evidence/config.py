"""Explicit, testable application paths for local runs and future Docker volumes.

Environment variables are interpreted as filesystem paths. Relative paths are
resolved against MARINE_PROJECT_ROOT (or an explicitly supplied project root).
No secrets are stored in this configuration object.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class AppPaths:
    """Filesystem paths used when initializing CorpusStore."""

    project_root: Path
    base_chunks_path: Path
    base_papers_dir: Path
    uploads_dir: Path
    base_manifest_path: Path

    @classmethod
    def from_environment(
        cls,
        root: Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "AppPaths":
        env = os.environ if environ is None else environ
        root_value = root if root is not None else env.get("MARINE_PROJECT_ROOT") or Path.cwd()
        project_root = Path(root_value).expanduser().resolve()

        def resolve(name: str, default: str) -> Path:
            raw = env.get(name)
            candidate = Path(raw).expanduser() if raw else Path(default)
            if not candidate.is_absolute():
                candidate = project_root / candidate
            return candidate.resolve()

        return cls(
            project_root=project_root,
            base_chunks_path=resolve("MARINE_BASE_CHUNKS_PATH", "data/chunks/word_safe/chunks.jsonl"),
            base_papers_dir=resolve("MARINE_BASE_PAPERS_DIR", "papers"),
            uploads_dir=resolve("MARINE_UPLOADS_DIR", "data/app"),
            base_manifest_path=resolve("MARINE_BASE_MANIFEST_PATH", "evaluation/papers_manifest.json"),
        )
