#!/usr/bin/env python3
"""Check project roles, knowledge routing, cost and cross-agent recovery.

Version 6 uses the visible ``PROJECT_ROLES.json``. Existing
``.kb-skills.json`` schema 1/2 registries remain readable during interactive
migration; they are reported as legacy, not rejected merely for being old.
The checker reads files and Git metadata but never executes project code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Optional

import kb_index


DISCOVERY = {"codex": ".agents/skills", "claude": ".claude/skills"}
VISIBLE_REGISTRY = "PROJECT_ROLES.json"
LEGACY_REGISTRY = ".kb-skills.json"
BEHAVIOURAL_COVERAGE = {
    "role-selection", "knowledge-recall", "authority-stop",
    "source-conflict", "context-cost",
}


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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_tree_sha256(folder: Path) -> str | None:
    probe = git(folder, "rev-parse", "--show-toplevel")
    if probe.returncode:
        return None
    repo = Path(probe.stdout.strip())
    try:
        relative = folder.relative_to(repo).as_posix()
    except ValueError:
        return None
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--", relative],
        capture_output=True)
    if listing.returncode:
        return None
    names = sorted(name for name in listing.stdout.split(b"\0") if name)
    if not names:
        return None
    digest = hashlib.sha256()
    for raw_name in names:
        path = repo / raw_name.decode("utf-8", "surrogateescape")
        if not path.is_file():
            continue
        local = path.relative_to(folder).as_posix().encode("utf-8")
        digest.update(local + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def frontmatter_value(skill_md: Path, key: str) -> Optional[str]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return None
    frontmatter = text[4:text.find("\n---\n", 4)]
    match = re.search(rf"^\s*{re.escape(key)}:\s*['\"]?([^'\"\n]+)",
                      frontmatter, re.MULTILINE)
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


def check_external(path: Path, dependency: object,
                   errors: list[str], name: str) -> None:
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
    pinned = git(repo, "rev-parse", pin + "^{commit}")
    if pinned.returncode:
        errors.append(f"{name}: dependency pin is unavailable locally")
        return
    head = git(repo, "rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != pinned.stdout.strip():
        errors.append(f"{name}: external checkout HEAD does not match dependency pin")
        return
    try:
        relative = path.relative_to(repo).as_posix()
    except ValueError:
        errors.append(f"{name}: external canonical is outside its Git checkout")
        return
    if git(repo, "ls-files", "--error-unmatch", relative + "/SKILL.md").returncode:
        errors.append(f"{name}: external SKILL.md is not tracked at dependency pin")
    if git(repo, "diff", "--quiet", pin, "--", relative).returncode:
        errors.append(f"{name}: external canonical differs from dependency pin")
    status = git(repo, "status", "--porcelain", "--untracked-files=all", "--", relative)
    if status.returncode or status.stdout.strip():
        errors.append(f"{name}: external canonical has local or untracked delta")


def check_skill_source(root: Path, entry: dict, agents: list[str],
                       errors: list[str], notes: list[str],
                       resolved_by_name: dict[str, Path],
                       strict_version: bool = True) -> tuple[str | None, int]:
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        errors.append("skill entry has no name")
        return None, 0
    required = ("canonical", "owner", "version", "validation",
                "failure_policy", "recovery_cost", "discovery")
    missing = [key for key in required if not entry.get(key)]
    if missing:
        errors.append(f"{name}: missing {', '.join(missing)}")
        return name, 0
    if entry.get("failure_policy") != "fail-closed":
        errors.append(f"{name}: project role must be fail-closed")
    validation = entry.get("validation")
    if not isinstance(validation, dict) or not validation.get("command") \
            or not validation.get("environment"):
        errors.append(f"{name}: validation needs command and environment")
    raw = Path(str(entry["canonical"])).expanduser()
    canonical = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
    if global_install(canonical):
        errors.append(f"{name}: required skill is user-global only")
    skill_md = canonical / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"{name}: canonical SKILL.md is missing")
        return name, 0
    declared_name = frontmatter_value(skill_md, "name")
    if declared_name and declared_name != name:
        errors.append(f"{name}: SKILL.md declares name {declared_name}")
    if strict_version:
        declared_version = frontmatter_value(skill_md, "version")
        if not declared_version:
            errors.append(f"{name}: SKILL.md has no frontmatter version")
        elif str(entry.get("version")) != declared_version:
            errors.append(f"{name}: registry version {entry.get('version')} != "
                          f"SKILL.md version {declared_version}")
    if outside(root, canonical):
        check_external(canonical, entry.get("dependency"), errors, name)
    elif not tracked(root, canonical):
        errors.append(f"{name}: repo-local canonical is not Git-tracked")
    discovery = entry.get("discovery")
    if not isinstance(discovery, dict):
        errors.append(f"{name}: discovery is not an object")
        return name, len(skill_md.read_bytes())
    for agent in agents:
        declared = discovery.get(agent)
        if not declared:
            errors.append(f"{name}: missing {agent} discovery point")
            continue
        point = root / str(declared)
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
    size = len(skill_md.read_bytes())
    notes.append(f"{name}: entry={size} bytes (~{round(size / 3.3)} tokens); "
                 f"canonical={entry['canonical']}")
    return name, size


def validate_visible(root: Path, data: dict,
                     registry: Path) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    notes: list[str] = []
    if data.get("schema") != 1 or not isinstance(data.get("roles"), list) \
            or not isinstance(data.get("skills"), list):
        return ["PROJECT_ROLES.json requires schema 1, roles and skills arrays"], notes, 0
    if not tracked(root, registry):
        errors.append("PROJECT_ROLES.json is not Git-tracked and recoverable")
    agents = data.get("supported_agents", [])
    if not agents or any(agent not in DISCOVERY for agent in agents):
        errors.append("supported_agents must name claude and/or codex")
    policy = data.get("role_posture")
    if not isinstance(policy, dict):
        return ["PROJECT_ROLES.json requires role_posture"], notes, 0
    status = policy.get("status")
    if status not in {"required", "transitioning", "not-applicable"}:
        errors.append("role_posture.status must be required, transitioning or not-applicable")
    if not policy.get("rationale"):
        errors.append("role_posture requires rationale")
    if status in {"required", "transitioning"}:
        expected = {"unmatched_material_work": "stop",
                    "multiple_matches": "load-all",
                    "conflict": "preserve-and-escalate"}
        for key, value in expected.items():
            if policy.get(key) != value:
                errors.append(f"role_posture.{key} must be {value}")
        if not data["roles"]:
            errors.append("required role posture has no roles")
        if status == "transitioning":
            transition = policy.get("transition")
            needed = ("target_roles", "covered_work", "open_gaps")
            if not isinstance(transition, dict) or any(
                    not transition.get(key) for key in needed):
                errors.append("transitioning posture requires target_roles, covered_work and open_gaps")
            else:
                errors.append("role posture is transitioning; uncovered material work remains fail-closed: " +
                              "; ".join(map(str, transition["open_gaps"])))
    elif status == "not-applicable" and (data["roles"] or data["skills"]):
        errors.append("not-applicable posture must have empty roles and skills")

    role_by_id: dict[str, dict] = {}
    for role in data["roles"]:
        if not isinstance(role, dict):
            errors.append("role entry is not an object")
            continue
        missing = [key for key in ("id", "purpose", "load_when", "skill",
                                   "knowledge_routes") if role.get(key) in (None, "")]
        if missing:
            errors.append("role missing " + ", ".join(missing))
            continue
        role_id = str(role["id"])
        if role_id in role_by_id:
            errors.append(f"duplicate role id: {role_id}")
            continue
        if not isinstance(role["load_when"], list) or not all(
                isinstance(item, str) and item for item in role["load_when"]):
            errors.append(f"{role_id}: load_when must be a non-empty string array")
        routes = role.get("knowledge_routes")
        if not isinstance(routes, list) or not routes or not all(
                isinstance(item, str) and item for item in routes):
            errors.append(f"{role_id}: knowledge_routes must be a non-empty string array")
        role_by_id[role_id] = role

    skill_by_name: dict[str, dict] = {}
    skill_sizes: dict[str, int] = {}
    resolved_by_name: dict[str, Path] = {}
    for entry in data["skills"]:
        if not isinstance(entry, dict):
            errors.append("skill entry is not an object")
            continue
        name = entry.get("name")
        if isinstance(name, str) and name in skill_by_name:
            errors.append(f"duplicate skill name: {name}")
            continue
        checked_name, size = check_skill_source(
            root, entry, agents, errors, notes, resolved_by_name)
        if checked_name:
            skill_by_name[checked_name] = entry
            skill_sizes[checked_name] = size
        validation = entry.get("validation", {})
        covers = set(validation.get("covers", [])) if isinstance(validation, dict) else set()
        missing_coverage = sorted(BEHAVIOURAL_COVERAGE - covers)
        if missing_coverage and checked_name:
            errors.append(f"{checked_name}: validation does not cover " +
                          ", ".join(missing_coverage))
    for role_id, role in role_by_id.items():
        if role.get("skill") not in skill_by_name:
            errors.append(f"{role_id}: referenced skill is not declared: {role.get('skill')}")

    route_ids: set[str] = set()
    if role_by_id:
        index_path = root / kb_index.DEFAULT_INDEX
        if not index_path.exists():
            errors.append("required roles need visible KNOWLEDGE_INDEX.json")
        else:
            index_routes, index_errors, _ = kb_index.validate(root, index_path)
            errors.extend(index_errors)
            route_ids = set(index_routes)
        for role_id, role in role_by_id.items():
            for route_id in role.get("knowledge_routes", []):
                if route_id not in route_ids:
                    errors.append(f"{role_id}: unknown knowledge route {route_id}")

    cost = data.get("cost_policy")
    covered_roles: set[str] = set()
    scenario_by_id: dict[str, dict] = {}
    if status in {"required", "transitioning"}:
        if not isinstance(cost, dict) or not isinstance(cost.get("scenarios"), list):
            errors.append("required roles need cost_policy.scenarios")
        else:
            threshold = cost.get("review_above_bytes", 8192)
            if not isinstance(threshold, int) or threshold <= 0:
                errors.append("cost_policy.review_above_bytes must be a positive integer")
                threshold = 8192
            seen_scenarios: set[str] = set()
            for scenario in cost["scenarios"]:
                if not isinstance(scenario, dict):
                    errors.append("cost scenario is not an object")
                    continue
                scenario_id = scenario.get("id")
                selected = scenario.get("roles")
                accepted = scenario.get("accepted_entry_bytes")
                if not isinstance(scenario_id, str) or not scenario_id:
                    errors.append("cost scenario has no id")
                    continue
                if scenario_id in seen_scenarios:
                    errors.append(f"duplicate cost scenario: {scenario_id}")
                seen_scenarios.add(scenario_id)
                scenario_by_id[scenario_id] = scenario
                if not isinstance(selected, list) or not selected:
                    errors.append(f"{scenario_id}: roles must be a non-empty array")
                    continue
                unknown = [role for role in selected if role not in role_by_id]
                if unknown:
                    errors.append(f"{scenario_id}: unknown roles {', '.join(unknown)}")
                    continue
                covered_roles.update(selected)
                unique_skills = {str(role_by_id[role]["skill"]) for role in selected}
                actual = sum(skill_sizes.get(name, 0) for name in unique_skills)
                if not isinstance(accepted, int) or accepted < 0:
                    errors.append(f"{scenario_id}: accepted_entry_bytes must be a non-negative integer")
                elif actual > accepted:
                    errors.append(f"OPTIMIZATION_REQUIRED {scenario_id}: role route grew "
                                  f"{accepted} -> {actual} bytes")
                if actual > threshold and not scenario.get("accepted_reason"):
                    errors.append(f"{scenario_id}: {actual} bytes exceeds review threshold "
                                  "without accepted_reason")
                elif actual > threshold:
                    notes.append(f"COST_SIGNAL {scenario_id}: {actual} bytes; "
                                 f"accepted because {scenario['accepted_reason']}")
                notes.append(f"route-cost {scenario_id}: {actual} bytes "
                             f"(~{round(actual / 3.3)} tokens); baseline={accepted}")
            missing = sorted(set(role_by_id) - covered_roles)
            if missing:
                errors.append("roles absent from cost scenarios: " + ", ".join(missing))
            upper_id = cost.get("all_roles_scenario")
            upper = scenario_by_id.get(upper_id) if isinstance(upper_id, str) else None
            if upper is None or set(upper.get("roles", [])) != set(role_by_id):
                errors.append("cost_policy.all_roles_scenario must name a scenario "
                              "containing every declared role")

        acceptance = data.get("acceptance")
        if not isinstance(acceptance, dict) or acceptance.get("status") != "accepted":
            errors.append("ROLE_ACCEPTANCE_REQUIRED: role manifest is not owner-accepted")
        else:
            receipt_raw = acceptance.get("receipt")
            receipt_path = root / str(receipt_raw or "")
            if not receipt_raw or outside(root, receipt_path.resolve(strict=False)):
                errors.append("role acceptance receipt path is missing or leaves project root")
            elif not receipt_path.is_file():
                errors.append("role acceptance receipt is missing")
            elif not tracked(root, receipt_path):
                errors.append("role acceptance receipt is not Git-tracked")
            else:
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"role acceptance receipt unreadable: {exc}")
                    receipt = {}
                if receipt.get("schema") != 1 or receipt.get("result") != "passed" \
                        or not receipt.get("accepted_by") or not receipt.get("accepted_at"):
                    errors.append("role acceptance receipt lacks passed owner acceptance")
                accepted_skills = receipt.get("skills", {})
                if not isinstance(accepted_skills, dict):
                    errors.append("role acceptance receipt skills must be an object")
                    accepted_skills = {}
                for name, entry in skill_by_name.items():
                    accepted = accepted_skills.get(name, {})
                    if not entry.get("canonical"):
                        continue
                    raw = Path(str(entry["canonical"])).expanduser()
                    canonical = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
                    skill_file = canonical / "SKILL.md"
                    if not skill_file.is_file():
                        continue
                    if accepted.get("skill_sha256") != file_sha256(skill_file):
                        errors.append(f"{name}: accepted skill hash does not match loaded bytes")
                    tree_digest = tracked_tree_sha256(canonical)
                    if not tree_digest or accepted.get("skill_tree_sha256") != tree_digest:
                        errors.append(f"{name}: accepted skill tree hash does not match loaded files")
                    accepted_covers = set(accepted.get("covers", [])) \
                        if isinstance(accepted, dict) else set()
                    missing = sorted(BEHAVIOURAL_COVERAGE - accepted_covers)
                    if missing:
                        errors.append(f"{name}: acceptance receipt does not cover " +
                                      ", ".join(missing))
                accepted_costs = receipt.get("scenario_baselines", {})
                expected_costs = {
                    key: value.get("accepted_entry_bytes")
                    for key, value in scenario_by_id.items()
                }
                if accepted_costs != expected_costs:
                    errors.append("role acceptance receipt does not match cost baselines")
                manifest_digest = receipt.get("project_roles_sha256")
                index_digest = receipt.get("knowledge_index_sha256")
                index_path = root / kb_index.DEFAULT_INDEX
                if manifest_digest != file_sha256(registry):
                    errors.append("role acceptance receipt does not match PROJECT_ROLES.json")
                if not index_path.is_file() or index_digest != file_sha256(index_path):
                    errors.append("role acceptance receipt does not match KNOWLEDGE_INDEX.json")
                if not errors:
                    notes.append(f"role acceptance: {receipt_path.relative_to(root)}; "
                                 f"accepted_by={receipt.get('accepted_by')}")
    notes.append(f"role posture: {status}; registry={registry.name}")
    return errors, notes, len(role_by_id)


def legacy_roles(data: dict) -> list[dict]:
    result = []
    for skill in data.get("skills", []):
        if not isinstance(skill, dict):
            continue
        if data.get("schema") == 1:
            result.append({"id": skill.get("name"), "skill": skill.get("name")})
        else:
            for role in skill.get("roles", []):
                if isinstance(role, dict):
                    result.append({"id": role.get("id"), "skill": skill.get("name")})
    return result


def validate_legacy(root: Path, data: dict,
                    registry: Path) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    notes = [f"LEGACY_ROLE_REGISTRY: {registry.name} schema {data.get('schema')} "
             "remains usable; migrate interactively to PROJECT_ROLES.json"]
    if (root / VISIBLE_REGISTRY).exists():
        notes.append("SHADOW_ROLE_REGISTRY: PROJECT_ROLES.json exists, but the "
                     "legacy registry remains authoritative until owner acceptance "
                     "replaces it with a superseded pointer")
    if data.get("schema") not in {1, 2} or not isinstance(data.get("skills"), list):
        return ["legacy registry requires schema 1 or 2 and a skills array"], notes, 0
    agents = data.get("supported_agents", [])
    if not agents or any(agent not in DISCOVERY for agent in agents):
        errors.append("supported_agents must name claude and/or codex")
    resolved: dict[str, Path] = {}
    seen: set[str] = set()
    for entry in data["skills"]:
        if not isinstance(entry, dict):
            errors.append("skill entry is not an object")
            continue
        name = entry.get("name")
        if isinstance(name, str) and name in seen:
            errors.append(f"duplicate skill name: {name}")
            continue
        if isinstance(name, str):
            seen.add(name)
        check_skill_source(root, entry, agents, errors, notes, resolved,
                           strict_version=False)
    roles = legacy_roles(data)
    notes.append(f"legacy role declarations: {len(roles)}")
    return errors, notes, len(roles)


def choose_registry(root: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit.resolve()
    legacy = root / LEGACY_REGISTRY
    if legacy.exists():
        # A shadow manifest must not preempt the accepted legacy role canon.
        # After owner acceptance the legacy file becomes a tombstone and
        # validate() follows its superseded_by pointer.
        return legacy
    visible = root / VISIBLE_REGISTRY
    return visible


def validate(root: Path, registry: Path) -> tuple[list[str], list[str], int]:
    if not registry.exists():
        observed = project_skills(root)
        detail = (": " + ", ".join(observed)) if observed else ""
        return ["professional role posture is undeclared: add PROJECT_ROLES.json "
                "or explicitly record not-applicable" + detail], [], 0
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"registry unreadable: {exc}"], [], 0
    if data.get("status") == "superseded":
        target_raw = data.get("superseded_by")
        if not isinstance(target_raw, str) or not target_raw:
            return ["superseded role registry has no superseded_by target"], [], 0
        target = (registry.parent / target_raw).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError:
            return ["superseded role registry target leaves project root"], [], 0
        if target == registry.resolve():
            return ["superseded role registry points to itself"], [], 0
        errors, notes, count = validate(root, target)
        return errors, [f"ROLE_REGISTRY_MOVED: {registry.name} -> "
                        f"{target.relative_to(root)}"] + notes, count
    if registry.name == VISIBLE_REGISTRY or "role_posture" in data:
        return validate_visible(root, data, registry)
    return validate_legacy(root, data, registry)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    registry = choose_registry(root, args.registry)
    errors, notes, count = validate(root, registry)
    for note in notes:
        print("OK:", note)
    print(f"coverage: registry={registry} declared={count} errors={len(errors)}")
    for error in errors:
        print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
