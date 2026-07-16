"""Resolve local GGUF files and optional Hugging Face cache downloads."""

from __future__ import annotations

import fnmatch
import hashlib
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class GGUFSource:
    repo_id: str | None
    filename: str
    revision: str | None
    local_path: Path
    size_bytes: int
    sha256: str
    provenance: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["local_path"] = str(self.local_path)
        return data


class GGUFSourceResolver:
    def resolve_local(self, path: str | Path, *, repo_id: str | None = None) -> GGUFSource:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"GGUF file not found: {resolved}")
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return GGUFSource(
            repo_id,
            resolved.name,
            None,
            resolved,
            resolved.stat().st_size,
            digest.hexdigest(),
            "local",
        )

    def download(self, repo_id: str, pattern: str, *, revision: str | None = None) -> GGUFSource:
        command = ["hf", "download", repo_id, "--include", pattern]
        if revision:
            command.extend(["--revision", revision])
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if completed.returncode:
            raise RuntimeError(f"hf download failed: {completed.stderr.strip()}")
        reported = [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip()]
        candidates: list[Path] = []
        for path in reported:
            if path.is_file() and path.suffix.lower() == ".gguf":
                candidates.append(path)
            elif path.is_dir():
                candidates.extend(
                    item for item in path.rglob("*.gguf") if fnmatch.fnmatch(item.name, pattern)
                )
        if len(candidates) != 1:
            raise RuntimeError(
                f"Expected exactly one GGUF for pattern {pattern!r}; found {len(candidates)}"
            )
        source = self.resolve_local(candidates[0], repo_id=repo_id)
        return GGUFSource(
            repo_id,
            source.filename,
            revision,
            source.local_path,
            source.size_bytes,
            source.sha256,
            "huggingface",
        )
