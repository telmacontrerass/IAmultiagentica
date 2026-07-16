"""Load built-in, workspace and user skills from SKILL.md files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ci2lab.harness.frontmatter import parse_frontmatter

MAX_SKILL_BODY_CHARS = 16_000
MAX_CATALOG_CHARS = 8_000
SKILL_FILENAME = "SKILL.md"


@dataclass
class Skill:
    """A skill discovered from a ``SKILL.md`` file.

    Attributes:
        name: The skill's unique name.
        description: Short description shown in the catalog.
        body: The skill's instruction body, possibly truncated.
        source: Origin of the skill: ``"builtin"``, ``"workspace"`` or
            ``"user"``.
        path: Filesystem path to the ``SKILL.md`` file.
        when_to_use: Optional guidance on when the skill applies.
        allowed_tools: Tool names the skill restricts execution to.
        disable_model_invocation: When ``True``, the model may not invoke the
            skill via the skill tool.
        user_invocable: Whether a user may invoke the skill directly.
    """

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
    """Return the root directory for user-level skills."""
    return Path.home() / ".ci2lab" / "skills"


def _workspace_skills_root(cwd: str) -> Path:
    """Return the root directory for workspace skills under ``cwd``."""
    return Path(cwd).resolve() / ".ci2lab" / "skills"


def _builtin_skills_root() -> Path:
    """Return the root directory for built-in skills shipped with the package."""
    return Path(__file__).resolve().parent / "builtin"


def _parse_allowed_tools(raw: str | None) -> list[str]:
    """Split a whitespace/comma-separated tool list into individual names."""
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[\s,]+", raw) if part.strip()]


def _parse_bool(value: str | None) -> bool:
    """Interpret a frontmatter string as a boolean flag."""
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def render_skill(skill: Skill, args: str = "") -> str:
    """Render a skill's standard header, optional arguments and instruction body."""
    header = f"# Skill: {skill.name}\n\n{skill.description}\n"
    if args.strip():
        header += f"\n**User arguments:** {args.strip()}\n"
    if skill.allowed_tools:
        tools = ", ".join(f"`{tool}`" for tool in skill.allowed_tools)
        header += f"\n**Allowed tools for this skill:** {tools}\n"
    return f"{header}\n{skill.body}"


def _load_skill_file(path: Path, source: str) -> Skill | None:
    """Read and parse a single ``SKILL.md`` file into a :class:`Skill`.

    Returns ``None`` when the file cannot be read.
    """
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
        user_invocable=not _parse_bool(meta.get("user_invocable"))
        or meta.get("user_invocable", "").lower() != "false",
    )


def _scan_skills_dir(root: Path, source: str) -> dict[str, Skill]:
    """Discover skills under ``root``, keyed by skill name.

    Returns an empty mapping when ``root`` is not a directory.
    """
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
    """Load skills; user overrides built-in, workspace overrides both.

    Args:
        cwd: The current working directory used to locate workspace skills.

    Returns:
        A mapping of skill name to :class:`Skill`, merged across the built-in,
        user and workspace sources in increasing precedence.
    """
    merged: dict[str, Skill] = {}
    merged.update(_scan_skills_dir(_builtin_skills_root(), "builtin"))
    merged.update(_scan_skills_dir(_user_skills_root(), "user"))
    merged.update(_scan_skills_dir(_workspace_skills_root(cwd), "workspace"))
    return merged


def skills_for_model(skills: dict[str, Skill]) -> dict[str, Skill]:
    """Skills the model may invoke via the skill tool.

    Args:
        skills: All loaded skills keyed by name.

    Returns:
        The subset of ``skills`` whose model invocation is not disabled.
    """
    return {name: skill for name, skill in skills.items() if not skill.disable_model_invocation}


def format_skill_catalog(skills: dict[str, Skill], *, budget_chars: int = MAX_CATALOG_CHARS) -> str:
    """Render a skills catalog as a bullet list, bounded by a character budget.

    Args:
        skills: The skills to include, keyed by name.
        budget_chars: Maximum length of the rendered catalog before truncation.

    Returns:
        A newline-separated bullet list of skills, truncated to ``budget_chars``;
        an empty string when there are no skills.
    """
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
    """Look up a skill by name.

    Args:
        skills: The skills to search, keyed by name.
        name: The skill name to retrieve.

    Returns:
        The matching :class:`Skill`, or ``None`` when no skill has that name.
    """
    return skills.get(name)
