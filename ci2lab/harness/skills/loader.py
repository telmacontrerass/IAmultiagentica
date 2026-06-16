"""Load built-in, workspace and user skills from SKILL.md files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_SKILL_BODY_CHARS = 16_000
MAX_CATALOG_CHARS = 8_000
SKILL_FILENAME = "SKILL.md"


@dataclass
class Skill:
    name: str
    description: str
    body: str
    source: str  # "builtin" | "workspace" | "user"
    path: Path
    when_to_use: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    user_invocable: bool = True


def _user_skills_root() -> Path:
    return Path.home() / ".ci2lab" / "skills"


def _workspace_skills_root(cwd: str) -> Path:
    return Path(cwd).resolve() / ".ci2lab" / "skills"


def _builtin_skills_root() -> Path:
    return Path(__file__).resolve().parent / "builtin"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-like frontmatter between --- markers."""
    if not text.startswith("---"):
        return {}, text.strip()
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    raw_fm = match.group(1)
    body = text[match.end() :].strip()
    meta: dict[str, str] = {}
    for line in raw_fm.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace("-", "_")
        value = value.strip().strip("'\"")
        if value:
            meta[key] = value
    return meta, body


def _parse_allowed_tools(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[\s,]+", raw) if part.strip()]


def _parse_bool(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_skill_file(path: Path, source: str) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = parse_frontmatter(text)
    name = meta.get("name") or path.parent.name
    description = meta.get("description") or f"Skill {name}"
    if len(body) > MAX_SKILL_BODY_CHARS:
        body = body[:MAX_SKILL_BODY_CHARS] + "\n... (skill body truncated)"
    return Skill(
        name=name,
        description=description,
        body=body,
        source=source,
        path=path,
        when_to_use=meta.get("when_to_use"),
        allowed_tools=_parse_allowed_tools(meta.get("allowed_tools")),
        disable_model_invocation=_parse_bool(meta.get("disable_model_invocation")),
        user_invocable=not _parse_bool(meta.get("user_invocable")) or meta.get("user_invocable", "").lower() != "false",
    )


def _scan_skills_dir(root: Path, source: str) -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    if not root.is_dir():
        return skills
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        skill_path = entry / SKILL_FILENAME
        if not skill_path.is_file():
            continue
        skill = _load_skill_file(skill_path, source)
        if skill:
            skills[skill.name] = skill
    return skills


def load_skills(cwd: str) -> dict[str, Skill]:
    """Load skills; user overrides built-in, workspace overrides both."""
    merged: dict[str, Skill] = {}
    merged.update(_scan_skills_dir(_builtin_skills_root(), "builtin"))
    merged.update(_scan_skills_dir(_user_skills_root(), "user"))
    merged.update(_scan_skills_dir(_workspace_skills_root(cwd), "workspace"))
    return merged


def skills_for_model(skills: dict[str, Skill]) -> dict[str, Skill]:
    """Skills the model may invoke via the skill tool."""
    return {
        name: skill
        for name, skill in skills.items()
        if not skill.disable_model_invocation
    }


def format_skill_catalog(skills: dict[str, Skill], *, budget_chars: int = MAX_CATALOG_CHARS) -> str:
    if not skills:
        return ""
    lines: list[str] = []
    for skill in sorted(skills.values(), key=lambda s: s.name):
        desc = skill.description
        if skill.when_to_use:
            desc = f"{desc} — {skill.when_to_use}"
        if len(desc) > 200:
            desc = desc[:199] + "…"
        lines.append(f"- `{skill.name}`: {desc}")
    text = "\n".join(lines)
    if len(text) > budget_chars:
        text = text[: budget_chars - 20] + "\n... (catalog truncated)"
    return text


def get_skill(skills: dict[str, Skill], name: str) -> Skill | None:
    return skills.get(name)
