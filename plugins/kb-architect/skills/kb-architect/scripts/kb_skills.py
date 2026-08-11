#!/usr/bin/env python3
"""Check recoverability and agent discovery of declared project skills.

The optional registry lives at ``<project>/.kb-skills.json``.  No registry and
no project skill is a valid state.  This checker only reads the project and
local Git metadata; it never scans application JSON or installs anything.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Optional


DISCOVERY = {"codex": ".agents/skills", "claude": ".claude/skills"}


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def project_skills(root: Path) -> list[str]:
    found = set()
    for base in ("skills", "skill", ".agents/skills", ".claude/skills"):
        folder = root / base
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            if (item / "SKILL.md").is_file():
                found.add(item.name)
    return sorted(found)


def tracked(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return False
    result = git(root, "ls-files", "--error-unmatch", rel)
    if result.returncode == 0:
        return True
    result = git(root, "ls-files", rel + "/**")
    return result.returncode == 0 and bool(result.stdout.strip())


def frontmatter_name(skill_md: Path) -> Optional[str]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^name:\s*['\"]?([^'\"\n]+)", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def outside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return False
    except ValueError:
        return True


def global_install(path: Path) -> bool:
    home = Path.home().resolve()
    return any(path == home / base or (home / base) in path.parents for base in (
        ".codex/skills", ".agents/skills", ".claude/skills"
    ))


def check_external(path: Path, dependency: object, errors: list[str], name: str) -> None:
    if not isinstance(dependency, dict):
        errors.append(f"{name}: external canonical has no dependency recipe")
        return
    missing = [key for key in ("repository", "pin", "recovery")
               if not dependency.get(key)]
    if missing:
        errors.append(f"{name}: dependency missing {', '.join(missing)}")
        return
    probe = git(path, "rev-parse", "--show-toplevel")
    if probe.returncode:
        errors.append(f"{name}: external canonical is not in a Git checkout")
        return
    repo = Path(probe.stdout.strip())
    remotes = git(repo, "remote", "-v").stdout
    if str(dependency["repository"]) not in remotes:
        errors.append(f"{name}: dependency repository does not match local remote")
    pin = str(dependency["pin"])
    if git(repo, "cat-file", "-e", pin + "^{commit}").returncode:
        errors.append(f"{name}: dependency pin is unavailable locally")


def validate(root: Path, registry: Path) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    notes: list[str] = []
    if not registry.exists():
        observed = project_skills(root)
        if observed:
            errors.append("project skills found but .kb-skills.json is absent: " +
                          ", ".join(observed))
        else:
            notes.append("specialized project skills: not declared (valid)")
        return errors, notes, 0
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"registry unreadable: {exc}"], notes, 0
    if data.get("schema") != 1 or not isinstance(data.get("skills"), list):
        return ["registry requires schema 1 and a skills array"], notes, 0
    agents = data.get("supported_agents", [])
    if not agents or any(a not in DISCOVERY for a in agents):
        errors.append("supported_agents must name claude and/or codex")
    seen: set[str] = set()
    resolved_by_name: dict[str, Path] = {}
    for entry in data["skills"]:
        if not isinstance(entry, dict):
            errors.append("skill entry is not an object")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            errors.append("skill entry has no name")
            continue
        if name in seen:
            errors.append(f"{name}: duplicate registry name")
            continue
        seen.add(name)
        required = bool(entry.get("required"))
        required_fields = (
            "purpose", "required_when", "modality", "authority_ladder",
            "conflict_resolution", "evidence_threshold", "stop_conditions",
            "prohibited_actions", "canonical", "owner", "scope",
            "project_precedence", "version", "validation", "failure_policy",
            "recovery_cost", "discovery",
        )
        missing = [key for key in required_fields if not entry.get(key)]
        if missing:
            errors.append(f"{name}: missing {', '.join(missing)}")
            continue
        if required and entry.get("failure_policy") != "fail-closed":
            errors.append(f"{name}: required skill must be fail-closed")
        validation = entry.get("validation")
        if not isinstance(validation, dict) or not validation.get("command") or not validation.get("environment"):
            errors.append(f"{name}: validation needs command and environment")
        raw = Path(str(entry["canonical"])).expanduser()
        canonical = (raw if raw.is_absolute() else root / raw)
        canonical = canonical.resolve(strict=False)
        if global_install(canonical) and required:
            errors.append(f"{name}: required skill is user-global only")
        if not (canonical / "SKILL.md").is_file():
            errors.append(f"{name}: canonical SKILL.md is missing")
            continue
        declared_name = frontmatter_name(canonical / "SKILL.md")
        if declared_name and declared_name != name:
            errors.append(f"{name}: SKILL.md declares name {declared_name}")
        if outside(root, canonical):
            check_external(canonical, entry.get("dependency"), errors, name)
        elif not tracked(root, canonical):
            errors.append(f"{name}: repo-local canonical is not Git-tracked")
        discovery = entry.get("discovery")
        if not isinstance(discovery, dict):
            errors.append(f"{name}: discovery is not an object")
            continue
        for agent in agents:
            declared = discovery.get(agent)
            if not declared:
                errors.append(f"{name}: missing {agent} discovery point")
                continue
            point = (root / str(declared))
            if point.is_symlink() and not point.exists():
                errors.append(f"{name}: broken {agent} discovery symlink")
                continue
            if not point.exists():
                errors.append(f"{name}: missing {agent} discovery point")
                continue
            resolved = point.resolve()
            if resolved != canonical:
                errors.append(f"{name}: {agent} discovery resolves to another copy")
            if not tracked(root, point):
                errors.append(f"{name}: {agent} discovery point is not Git-tracked")
            previous = resolved_by_name.get(name)
            if previous is not None and previous != resolved:
                errors.append(f"{name}: name collision resolves to multiple copies")
            resolved_by_name[name] = resolved
        notes.append(f"{name}: {'required' if required else 'optional'}; canonical={entry['canonical']}")
    return errors, notes, len(data["skills"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    registry = args.registry.resolve() if args.registry else root / ".kb-skills.json"
    errors, notes, count = validate(root, registry)
    for note in notes:
        print("OK:", note)
    print(f"coverage: registry={registry} declared={count} errors={len(errors)}")
    for error in errors:
        print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
