"""Domain Skill loader (phase H1, DEV_SPEC §H1 / §6).

Implements **business skill-package loading**: each supported :class:`TaskType`
ships as a directory under ``fiat_agent/skills/<package>/`` containing a
``SKILL.md`` with YAML frontmatter describing the skill and a Markdown body that
is the domain system prompt.

The loader turns those files into :class:`DomainSkill` objects the orchestrator
/ context builder can consume. A skill declares three things the acceptance
criteria require to differ per ``task_type``:

* ``system_prompt`` — the domain-specific system prompt (the SKILL.md body);
* ``tools``        — the tool names the skill is allowed to request;
* ``output_schema``— a JSON schema describing the skill's expected answer shape.

Discovery is filesystem-based and deterministic (no LLM). Skills are parsed
lazily on first access and cached per :class:`SkillLoader` instance.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Iterable, Optional

from fiat_agent.schemas.common import FiatModel, TaskType

# Default location: the package directory that holds this module
# (fiat_agent/skills/), where each sub-directory is a skill package.
_DEFAULT_SKILLS_DIR = Path(__file__).parent
_SKILL_FILE = "SKILL.md"


class SkillError(Exception):
    """Base class for skill-loading failures."""


class SkillParseError(SkillError):
    """Raised when a SKILL.md file cannot be parsed."""


class SkillNotFound(SkillError):
    """Raised when no skill is registered for a requested task type."""


class DomainSkill(FiatModel):
    """A parsed domain skill package.

    Carries everything the orchestrator needs to specialise behaviour for one
    :class:`TaskType`: the domain system prompt, the set of tools the skill may
    request, and the JSON schema describing the answer it must produce.
    """

    task_type: TaskType
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = []
    output_schema: Optional[dict[str, Any]] = None
    version: str = "1.0.0"
    source_path: Optional[str] = None

    def __eq__(self, other: Any) -> bool:
        # Compare on identity fields so tests can assert distrinctness clearly.
        if not isinstance(other, DomainSkill):
            return NotImplemented
        return (
            self.task_type == other.task_type
            and self.name == other.name
            and self.system_prompt == other.system_prompt
            and self.tools == other.tools
            and self.output_schema == other.output_schema
        )


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md document into (frontmatter dict, body string).

    Expects standard Markdown frontmatter: a leading line ``---``, a closing
    line ``---``, YAML between them, and the body afterwards.
    """
    if not text.lstrip().startswith("---"):
        raise SkillParseError("SKILL.md must start with a '---' frontmatter block")
    lines = text.splitlines()
    # lines[0] is the opening '---'; find the closing '---'.
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise SkillParseError("SKILL.md frontmatter has no closing '---'")
    try:
        fm = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise SkillParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(fm, dict):
        raise SkillParseError("frontmatter must be a YAML mapping")
    body = "\n".join(lines[end + 1 :]).strip()
    return fm, body


def _parse_skill(path: Path) -> DomainSkill:
    """Parse a single SKILL.md file into a :class:`DomainSkill`."""
    raw = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(raw)

    task_type_raw = fm.get("task_type")
    if not task_type_raw:
        raise SkillParseError(f"{path}: frontmatter missing 'task_type'")
    try:
        task_type = TaskType(task_type_raw)
    except ValueError as exc:
        raise SkillParseError(
            f"{path}: unknown task_type '{task_type_raw}'"
        ) from exc

    name = fm.get("name") or task_type.value
    tools = fm.get("tools") or []
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise SkillParseError(f"{path}: 'tools' must be a list of strings")

    output_schema = fm.get("output_schema")
    if output_schema is not None and not isinstance(output_schema, dict):
        raise SkillParseError(f"{path}: 'output_schema' must be a mapping")

    return DomainSkill(
        task_type=task_type,
        name=name,
        description=fm.get("description", ""),
        system_prompt=body,
        tools=tools,
        output_schema=output_schema,
        version=str(fm.get("version", "1.0.0")),
        source_path=str(path),
    )


class SkillLoader:
    """Discovers and loads domain skill packages from a skills directory."""

    def __init__(self, skills_dir: Optional[Path | str] = None) -> None:
        self._dir = Path(skills_dir) if skills_dir is not None else _DEFAULT_SKILLS_DIR
        self._cache: dict[TaskType, DomainSkill] = {}

    # --- discovery ----------------------------------------------------
    def _discover_paths(self) -> list[Path]:
        """Return SKILL.md paths for every skill package in the directory."""
        if not self._dir.is_dir():
            return []
        found: list[Path] = []
        for child in sorted(self._dir.iterdir()):
            if child.is_dir():
                skill_file = child / _SKILL_FILE
                if skill_file.is_file():
                    found.append(skill_file)
        return found

    def _load_all(self) -> dict[TaskType, DomainSkill]:
        if self._cache:
            return self._cache
        for path in self._discover_paths():
            skill = _parse_skill(path)
            self._cache[skill.task_type] = skill
        return self._cache

    # --- queries ------------------------------------------------------
    def all(self) -> list[DomainSkill]:
        """All loaded skills (insertion order from filesystem sort)."""
        return list(self._load_all().values())

    def task_types(self) -> list[TaskType]:
        """Task types that have a registered skill."""
        return list(self._load_all().keys())

    def get(self, task_type: TaskType) -> DomainSkill:
        """Return the skill for ``task_type``.

        Raises:
            SkillNotFound: if no skill is registered for ``task_type``.
        """
        skills = self._load_all()
        skill = skills.get(task_type)
        if skill is None:
            raise SkillNotFound(f"no skill registered for task_type '{task_type.value}'")
        return skill

    def get_or_none(self, task_type: TaskType) -> Optional[DomainSkill]:
        """Like :meth:`get` but returns ``None`` instead of raising."""
        try:
            return self.get(task_type)
        except SkillNotFound:
            return None


def load_skill(task_type: TaskType, skills_dir: Optional[Path | str] = None) -> DomainSkill:
    """Convenience: load a single skill for ``task_type``.

    Builds a fresh :class:`SkillLoader`, so this is safe to call from tests and
    single-shot callers without worrying about cross-call caching.
    """
    return SkillLoader(skills_dir).get(task_type)


def load_all(skills_dir: Optional[Path | str] = None) -> list[DomainSkill]:
    """Convenience: load every skill package."""
    return SkillLoader(skills_dir).all()
