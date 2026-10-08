"""
core/skill_loader.py — Generic Agent Skills and rules loader.

Discovers and loads:
  - .agents/rules/*.md
  - .agents/workflows/*.md
  - .agents/skills/*/SKILL.md
  - ~/.gemini/config/skills/*/SKILL.md (global user skills)

Extracts metadata (frontmatter or markdown headers) and formats skills
for system instruction injection and user inspection via /skills.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
from ui.console import console


@dataclass
class AgentSkill:
    name: str
    category: str  # "rule", "workflow", "skill"
    path: str
    description: str = ""
    trigger: str = "always_on"
    content: str = ""
    raw_content: str = ""


# In-memory store of loaded skills
_LOADED_SKILLS: List[AgentSkill] = []


def _parse_frontmatter(raw: str) -> tuple[Dict[str, str], str]:
    """
    Parse simple YAML frontmatter delimited by ^---\\n ... \\n---.
    Returns: (metadata_dict, body_content)
    """
    meta: Dict[str, str] = {}
    body = raw

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
    if m:
        fm_text = m.group(1)
        body = m.group(2).strip()
        for line in fm_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip("'\"")

    return meta, body


def _load_single_file(path: str, default_category: str) -> Optional[AgentSkill]:
    """Parse a single markdown rule or workflow file."""
    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception:
        return None

    meta, body = _parse_frontmatter(raw)
    base_name = os.path.splitext(os.path.basename(path))[0]

    name = meta.get("name") or base_name
    desc = meta.get("description", "")
    trigger = meta.get("trigger", "always_on")

    # If description missing, try reading first markdown heading or paragraph
    if not desc:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            if line:
                desc = line[:100]
                break

    return AgentSkill(
        name=name,
        category=default_category,
        path=path,
        description=desc or "Project rule or workflow",
        trigger=trigger,
        content=body,
        raw_content=raw,
    )


def load_skills(project_root: Optional[str] = None) -> List[AgentSkill]:
    """
    Scan and load all rules, workflows, and skills.
    Updates the global _LOADED_SKILLS cache.
    """
    global _LOADED_SKILLS
    skills: List[AgentSkill] = []
    seen_paths = set()

    root = project_root or getattr(config, "active_project_dir", None) or os.getcwd()

    # 1. Project .agents/rules/*.md
    rules_dir = os.path.join(root, ".agents", "rules")
    if os.path.isdir(rules_dir):
        for fname in sorted(os.listdir(rules_dir)):
            if fname.endswith(".md"):
                fpath = os.path.join(rules_dir, fname)
                if fpath not in seen_paths:
                    s = _load_single_file(fpath, "rule")
                    if s:
                        skills.append(s)
                        seen_paths.add(fpath)

    # 2. Project .agents/workflows/*.md
    wf_dir = os.path.join(root, ".agents", "workflows")
    if os.path.isdir(wf_dir):
        for fname in sorted(os.listdir(wf_dir)):
            if fname.endswith(".md"):
                fpath = os.path.join(wf_dir, fname)
                if fpath not in seen_paths:
                    s = _load_single_file(fpath, "workflow")
                    if s:
                        skills.append(s)
                        seen_paths.add(fpath)

    # 3. Project .agents/skills/*/SKILL.md
    proj_skills_dir = os.path.join(root, ".agents", "skills")
    if os.path.isdir(proj_skills_dir):
        for sdir in sorted(os.listdir(proj_skills_dir)):
            skill_md = os.path.join(proj_skills_dir, sdir, "SKILL.md")
            if os.path.isfile(skill_md) and skill_md not in seen_paths:
                s = _load_single_file(skill_md, "skill")
                if s:
                    s.name = s.name or sdir
                    skills.append(s)
                    seen_paths.add(skill_md)

    # 4. Global user skills ~/.gemini/config/skills/*/SKILL.md
    home_dir = os.path.expanduser("~")
    global_skills_dir = os.path.join(home_dir, ".gemini", "config", "skills")
    if os.path.isdir(global_skills_dir):
        for sdir in sorted(os.listdir(global_skills_dir)):
            skill_md = os.path.join(global_skills_dir, sdir, "SKILL.md")
            if os.path.isfile(skill_md) and skill_md not in seen_paths:
                s = _load_single_file(skill_md, "global skill")
                if s:
                    s.name = s.name or sdir
                    skills.append(s)
                    seen_paths.add(skill_md)

    _LOADED_SKILLS = skills
    return skills


def reload_skills(project_root: Optional[str] = None) -> List[AgentSkill]:
    """Force reload all skills from disk."""
    return load_skills(project_root)


def get_loaded_skills() -> List[AgentSkill]:
    """Return currently cached loaded skills."""
    if not _LOADED_SKILLS:
        return load_skills()
    return _LOADED_SKILLS


def build_skills_context() -> str:
    """
    Format active skills and rules into a system prompt section.
    """
    skills = get_loaded_skills()
    if not skills:
        return ""

    lines = [
        "## Active Project Rules and Skills",
        "The following project guidelines, rules, and workflows are active and must be strictly respected:\n"
    ]

    for s in skills:
        lines.append(f"### [{s.category.upper()}] {s.name}")
        if s.description:
            lines.append(f"*Description: {s.description}*")
        lines.append(f"*Source: {s.path}*")
        lines.append(s.content.strip())
        lines.append("")

    return "\n".join(lines)


def show_skills_table():
    """Display loaded skills and workflows in a Rich Table."""
    from rich.table import Table
    from rich.panel import Panel

    skills = get_loaded_skills()
    if not skills:
        console.print("[yellow]No skills or rules loaded.[/yellow] Add .agents/rules/*.md or .agents/workflows/*.md to your project.")
        return

    table = Table(title="Loaded Agent Skills & Rules")
    table.add_column("Category", style="cyan", justify="left")
    table.add_column("Name", style="bold green", justify="left")
    table.add_column("Description", style="white", justify="left")
    table.add_column("Path", style="dim", justify="left")

    for s in skills:
        rel_path = s.path
        try:
            rel_path = os.path.relpath(s.path, os.getcwd())
        except Exception:
            pass
        table.add_row(
            s.category.upper(),
            s.name,
            s.description[:80] + ("..." if len(s.description) > 80 else ""),
            rel_path,
        )

    console.print(table)
    console.print(f"[dim]Total loaded: {len(skills)} item(s). Use [cyan]/skills reload[/cyan] to rescan.[/dim]\n")
