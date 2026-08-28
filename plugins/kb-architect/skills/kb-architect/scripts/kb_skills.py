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
import os
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
ACCEPTANCE_OUTCOMES = {
    "STRUCTURAL_PASS", "DISCOVERY_PASS", "BEHAVIOR_PASS", "OWNER_ACCEPTED",
}
PORTABLE_TOP_LEVEL = {
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
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


def frontmatter(skill_md: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return {}, {}, ["SKILL.md is unreadable"]
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}, {}, ["SKILL.md has no YAML frontmatter"]
    block = text[4:text.find("\n---\n", 4)]
    top: dict[str, str] = {}
    metadata: dict[str, str] = {}
    in_metadata = False
    errors: list[str] = []
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[:1].isspace():
            if in_metadata:
                match = re.match(r"^\s+([A-Za-z0-9_-]+):\s*(.*)$", raw)
                if match:
                    metadata[match.group(1)] = match.group(2).strip().strip("'\"")
            continue
        in_metadata = False
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if not match:
            errors.append(f"invalid top-level frontmatter line: {raw}")
            continue
        key, value = match.groups()
        top[key] = value.strip().strip("'\"")
        in_metadata = key == "metadata"
    return top, metadata, errors


def frontmatter_value(skill_md: Path, key: str) -> Optional[str]:
    top, metadata, _errors = frontmatter(skill_md)
    if key == "version":
        return metadata.get("version")
    return top.get(key)


def portable_frontmatter_errors(skill_md: Path, name: str,
                                expected_version: object) -> list[str]:
    top, metadata, errors = frontmatter(skill_md)
    result = [f"{name}: platform validator: {error}" for error in errors]
    unsupported = sorted(set(top) - PORTABLE_TOP_LEVEL)
    if unsupported:
        result.append(f"{name}: platform validator rejects top-level " +
                      ", ".join(unsupported))
    if top.get("name") != name:
        result.append(f"{name}: platform validator requires exact name")
    if not top.get("description"):
        result.append(f"{name}: platform validator requires description")
    version = metadata.get("version")
    if not version:
        result.append(f"{name}: platform validator requires metadata.version")
    elif str(expected_version) != version:
        result.append(f"{name}: registry version {expected_version} != "
                      f"SKILL.md metadata.version {version}")
    return result


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
    required = (("canonical", "owner", "quality_owner", "quality_review",
                 "version", "validation", "failure_policy", "recovery_cost",
                 "discovery") if strict_version else
                ("canonical", "owner", "version", "validation",
                 "failure_policy", "recovery_cost", "discovery"))
    missing = [key for key in required if not entry.get(key)]
    if missing:
        errors.append(f"{name}: missing {', '.join(missing)}")
        return name, 0
    if entry.get("failure_policy") != "fail-closed":
        errors.append(f"{name}: project role must be fail-closed")
    validation = entry.get("validation")
    if not isinstance(validation, dict):
        errors.append(f"{name}: validation needs platform and project gates")
    elif strict_version:
        for gate in ("platform", "project"):
            declaration = validation.get(gate)
            if not isinstance(declaration, dict) or not declaration.get("command") \
                    or not declaration.get("environment"):
                errors.append(f"{name}: validation.{gate} needs command and environment")
    elif not validation.get("command") or not validation.get("environment"):
        errors.append(f"{name}: validation needs command and environment")
    raw = Path(str(entry["canonical"])).expanduser()
    canonical = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
    if global_install(canonical):
        errors.append(f"{name}: required skill is user-global only")
    skill_md = canonical / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"{name}: canonical SKILL.md is missing")
        return name, 0
    if strict_version:
        errors.extend(portable_frontmatter_errors(skill_md, name, entry.get("version")))
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


def evidence_errors(root: Path, value: object, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list) or not value:
        return [f"{label}: evidence must be a non-empty array"]
    for index, item in enumerate(value):
        item_label = f"{label}.evidence[{index}]"
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            errors.append(f"{item_label}: path and sha256 are required")
            continue
        raw = Path(str(item["path"]))
        path = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
        if outside(root, path):
            errors.append(f"{item_label}: path leaves project root")
        elif not path.is_file():
            errors.append(f"{item_label}: evidence file is missing")
        elif not tracked(root, path):
            errors.append(f"{item_label}: evidence file is not Git-tracked")
        elif file_sha256(path) != item["sha256"]:
            errors.append(f"{item_label}: evidence hash does not match")
    return errors


def quality_review(root: Path, entry: dict, errors: list[str]) -> str | None:
    name = str(entry.get("name", "<unknown>"))
    canonical_raw = Path(str(entry.get("canonical", ""))).expanduser()
    canonical = (canonical_raw if canonical_raw.is_absolute()
                 else root / canonical_raw).resolve(strict=False)
    raw = Path(str(entry.get("quality_review", "")))
    path = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
    if not entry.get("quality_owner"):
        errors.append(f"{name}: quality_owner is required")
    if not entry.get("quality_review") or outside(canonical, path):
        errors.append(f"{name}: quality review must be inside the canonical role tree")
        return None
    repo_probe = git(path.parent, "rev-parse", "--show-toplevel")
    review_repo = Path(repo_probe.stdout.strip()).resolve() if not repo_probe.returncode else root
    if not path.is_file() or not tracked(review_repo, path):
        errors.append(f"{name}: quality review is missing or not Git-tracked")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{name}: quality review unreadable: {exc}")
        return None
    if data.get("schema") != 1 or data.get("result") != "PASS":
        errors.append(f"{name}: ROLE_QUALITY_REVIEW is not PASS")
    if data.get("skill") != name or data.get("quality_owner") != entry.get("quality_owner"):
        errors.append(f"{name}: quality review identity/owner mismatch")
    if not data.get("reviewed_at"):
        errors.append(f"{name}: quality review has no reviewed_at")
    review = data.get("external_practice_review")
    allowed = {"performed", "deferred", "not-applicable"}
    if not isinstance(review, dict) or review.get("status") not in allowed \
            or not review.get("rationale"):
        errors.append(f"{name}: external practice review needs status and rationale")
    errors.extend(evidence_errors(review_repo, data.get("evidence"),
                                  f"{name}.ROLE_QUALITY_REVIEW"))
    return file_sha256(path)


def default_runtime_roots() -> list[Path]:
    home = Path(os.path.expanduser("~")).resolve()
    roots = [home / ".codex/skills", home / ".claude/skills", home / ".agents/skills"]
    extra = os.environ.get("KB_ROLE_RUNTIME_ROOTS", "")
    roots.extend(Path(os.path.expanduser(value)).resolve()
                 for value in extra.split(os.pathsep) if value)
    return roots


def runtime_inventory(name: str, roots: list[Path]) -> list[dict]:
    found: list[dict] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        candidates = list(root.rglob("SKILL.md"))
        for skill_md in candidates:
            resolved = skill_md.resolve(strict=False)
            if resolved in seen or frontmatter_value(skill_md, "name") != name:
                continue
            seen.add(resolved)
            found.append({
                "id": name,
                "path": str(skill_md),
                "resolved_path": str(resolved),
                "sha256": file_sha256(skill_md),
                "version": frontmatter_value(skill_md, "version"),
            })
    return found


def check_runtime_collisions(name: str, canonical: Path, roots: list[Path],
                             errors: list[str], notes: list[str]) -> None:
    canonical_file = canonical / "SKILL.md"
    if not canonical_file.is_file():
        return
    canonical_hash = file_sha256(canonical_file)
    collisions = []
    for item in runtime_inventory(name, roots):
        if Path(item["resolved_path"]) == canonical_file.resolve(strict=False):
            continue
        if item["sha256"] != canonical_hash:
            collisions.append(item)
        else:
            notes.append(f"{name}: identical active runtime copy at {item['path']}")
    for item in collisions:
        errors.append(
            f"{name}: ACTIVE_RUNTIME_COLLISION path={item['path']} "
            f"hash={item['sha256']} version={item['version'] or 'UNKNOWN'}")


def route_file(root: Path, value: object, label: str,
               errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label}: route file path is missing")
        return None
    path = (root / value).resolve(strict=False)
    if outside(root, path):
        errors.append(f"{label}: route file leaves project root: {value}")
    elif not path.is_file():
        errors.append(f"{label}: route file is missing: {value}")
    elif not tracked(root, path):
        errors.append(f"{label}: route file is not Git-tracked: {value}")
    else:
        return path
    return None


def validate_visible(root: Path, data: dict, registry: Path,
                     runtime_roots: list[Path] | None = None
                     ) -> tuple[list[str], list[str], int]:
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
        expected = {"unmatched_material_work": "stop", "multiple_matches": "load-all",
                    "conflict": "preserve-and-escalate"}
        for key, value in expected.items():
            if policy.get(key) != value:
                errors.append(f"role_posture.{key} must be {value}")
        if not data["roles"]:
            errors.append("required role posture has no roles")
        if status == "transitioning":
            transition = policy.get("transition")
            needed = ("target_roles", "covered_work", "open_gaps")
            if not isinstance(transition, dict) or any(not transition.get(k) for k in needed):
                errors.append("transitioning posture requires target_roles, covered_work and open_gaps")
            else:
                errors.append("role posture is transitioning; uncovered material work remains "
                              "fail-closed: " + "; ".join(map(str, transition["open_gaps"])))
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
        if not isinstance(role["load_when"], list) or not role["load_when"] or not all(
                isinstance(item, str) and item for item in role["load_when"]):
            errors.append(f"{role_id}: load_when must be a non-empty string array")
        routes = role.get("knowledge_routes")
        if not isinstance(routes, list) or not routes or not all(
                isinstance(item, str) and item for item in routes):
            errors.append(f"{role_id}: knowledge_routes must be a non-empty string array")
        role_by_id[role_id] = role

    roots = runtime_roots if runtime_roots is not None else default_runtime_roots()
    notes.append("runtime discovery roots checked: " +
                 (", ".join(str(path) for path in roots) if roots else "none"))
    skill_by_name: dict[str, dict] = {}
    skill_sizes: dict[str, int] = {}
    quality_hashes: dict[str, str | None] = {}
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
        if not checked_name:
            continue
        skill_by_name[checked_name] = entry
        skill_sizes[checked_name] = size
        project_gate = entry.get("validation", {}).get("project", {}) \
            if isinstance(entry.get("validation"), dict) else {}
        covers = set(project_gate.get("covers", [])) if isinstance(project_gate, dict) else set()
        missing_coverage = sorted(BEHAVIOURAL_COVERAGE - covers)
        if missing_coverage:
            errors.append(f"{checked_name}: validation.project does not cover " +
                          ", ".join(missing_coverage))
        quality_hashes[checked_name] = quality_review(root, entry, errors)
        raw = Path(str(entry.get("canonical", ""))).expanduser()
        canonical = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
        check_runtime_collisions(checked_name, canonical, roots, errors, notes)
    for role_id, role in role_by_id.items():
        if role.get("skill") not in skill_by_name:
            errors.append(f"{role_id}: referenced skill is not declared: {role.get('skill')}")

    index_path = root / kb_index.DEFAULT_INDEX
    index_routes: dict[str, dict] = {}
    if role_by_id:
        if not index_path.exists():
            errors.append("required roles need visible KNOWLEDGE_INDEX.json")
        else:
            index_routes, index_errors, _ = kb_index.validate(root, index_path)
            errors.extend(index_errors)
        for role_id, role in role_by_id.items():
            for route_id in role.get("knowledge_routes", []):
                if route_id not in index_routes:
                    errors.append(f"{role_id}: unknown knowledge route {route_id}")

    scenario_by_id: dict[str, dict] = {}
    measured_costs: dict[str, dict] = {}
    if status in {"required", "transitioning"}:
        cost = data.get("cost_policy")
        covered_roles: set[str] = set()
        if not isinstance(cost, dict) or not isinstance(cost.get("scenarios"), list):
            errors.append("required roles need cost_policy.scenarios")
        else:
            threshold = cost.get("review_above_bytes", 8192)
            if not isinstance(threshold, int) or threshold <= 0:
                errors.append("cost_policy.review_above_bytes must be a positive integer")
                threshold = 8192
            for scenario in cost["scenarios"]:
                if not isinstance(scenario, dict):
                    errors.append("cost scenario is not an object")
                    continue
                scenario_id = scenario.get("id")
                selected = scenario.get("roles")
                if not isinstance(scenario_id, str) or not scenario_id:
                    errors.append("cost scenario has no id")
                    continue
                if scenario_id in scenario_by_id:
                    errors.append(f"duplicate cost scenario: {scenario_id}")
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
                entry_bytes = sum(skill_sizes.get(name, 0) for name in unique_skills)
                required_routes = {route for role in selected
                                   for route in role_by_id[role].get("knowledge_routes", [])}
                required_paths = {path for route in required_routes
                                  for path in index_routes.get(route, {}).get("paths", [])}
                declared_files = scenario.get("route_files")
                if not isinstance(declared_files, list) or not all(
                        isinstance(item, str) and item for item in declared_files):
                    errors.append(f"{scenario_id}: route_files must be a string array")
                    declared_files = []
                missing_paths = sorted(required_paths - set(declared_files))
                if missing_paths:
                    errors.append(f"{scenario_id}: route_files omit routed knowledge " +
                                  ", ".join(missing_paths))
                paths = [route_file(root, value, scenario_id, errors)
                         for value in dict.fromkeys(declared_files)]
                static_bytes = entry_bytes + sum(path.stat().st_size for path in paths if path)
                accepted_entry = scenario.get("accepted_role_entry_bytes")
                accepted_static = scenario.get("accepted_static_route_bytes")
                for label, accepted, actual in (
                        ("accepted_role_entry_bytes", accepted_entry, entry_bytes),
                        ("accepted_static_route_bytes", accepted_static, static_bytes)):
                    if not isinstance(accepted, int) or accepted < 0:
                        errors.append(f"{scenario_id}: {label} must be a non-negative integer")
                    elif actual > accepted:
                        errors.append(f"OPTIMIZATION_REQUIRED {scenario_id}: {label} grew "
                                      f"{accepted} -> {actual} bytes")
                if static_bytes > threshold and not scenario.get("accepted_reason"):
                    errors.append(f"{scenario_id}: {static_bytes} bytes exceeds review threshold "
                                  "without accepted_reason")
                elif static_bytes > threshold:
                    notes.append(f"COST_SIGNAL {scenario_id}: {static_bytes} static bytes; "
                                 f"accepted because {scenario['accepted_reason']}")
                measured_costs[scenario_id] = {
                    "accepted_role_entry_bytes": accepted_entry,
                    "accepted_static_route_bytes": accepted_static,
                    "route_files": declared_files,
                }
                notes.append(f"route-cost {scenario_id}: role-entry={entry_bytes}; "
                             f"static-end-to-end={static_bytes}; actual-usage=receipt")
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
            receipt_path = (root / str(receipt_raw or "")).resolve(strict=False)
            if not receipt_raw or outside(root, receipt_path):
                errors.append("role acceptance receipt path is missing or leaves project root")
            elif not receipt_path.is_file() or not tracked(root, receipt_path):
                errors.append("role acceptance receipt is missing or not Git-tracked")
            else:
                before_receipt = len(errors)
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"role acceptance receipt unreadable: {exc}")
                    receipt = {}
                outcomes = receipt.get("outcomes", {})
                if receipt.get("schema") != 2 or not isinstance(outcomes, dict):
                    errors.append("ROLE_ACCEPTANCE_SCHEMA_2_REQUIRED")
                    outcomes = {}
                if set(outcomes) != ACCEPTANCE_OUTCOMES:
                    errors.append("role acceptance must separate STRUCTURAL_PASS, "
                                  "DISCOVERY_PASS, BEHAVIOR_PASS and OWNER_ACCEPTED")
                for outcome in ACCEPTANCE_OUTCOMES:
                    gate = outcomes.get(outcome, {})
                    if not isinstance(gate, dict) or gate.get("status") != "PASS":
                        errors.append(f"{outcome}: status must be PASS")
                    else:
                        errors.extend(evidence_errors(root, gate.get("evidence"), outcome))

                structural = outcomes.get("STRUCTURAL_PASS", {})
                validators = structural.get("validators", {}) \
                    if isinstance(structural, dict) else {}
                for name, entry in skill_by_name.items():
                    skill_validators = validators.get(name, {}) \
                        if isinstance(validators, dict) else {}
                    declarations = entry.get("validation", {})
                    for gate_name in ("platform", "project"):
                        result = skill_validators.get(gate_name, {}) \
                            if isinstance(skill_validators, dict) else {}
                        declared = declarations.get(gate_name, {}) \
                            if isinstance(declarations, dict) else {}
                        if result.get("result") != "PASS" \
                                or result.get("command") != declared.get("command"):
                            errors.append(f"STRUCTURAL_PASS.{name}.{gate_name}: "
                                          "PASS must bind the declared validator command")
                        else:
                            errors.extend(evidence_errors(
                                root, result.get("evidence"),
                                f"STRUCTURAL_PASS.{name}.{gate_name}"))

                discovery_gate = outcomes.get("DISCOVERY_PASS", {})
                discovered_agents = discovery_gate.get("agents", {}) \
                    if isinstance(discovery_gate, dict) else {}
                for agent in agents:
                    result = discovered_agents.get(agent, {}) \
                        if isinstance(discovered_agents, dict) else {}
                    if result.get("fresh_context") is not True or result.get("unforced") is not True:
                        errors.append(f"DISCOVERY_PASS.{agent}: fresh_context and unforced are required")
                    if result.get("new_session_required") is not True \
                            or result.get("session_boundary") != "new-session":
                        errors.append(f"DISCOVERY_PASS.{agent}: new-session boundary is required")
                    inventory = result.get("inventory", [])
                    selected = result.get("selected", [])
                    if not isinstance(inventory, list) or not isinstance(selected, list):
                        errors.append(f"DISCOVERY_PASS.{agent}: inventory and selected arrays required")
                        continue
                    for item_index, item in enumerate(inventory):
                        if not isinstance(item, dict) or any(
                                item.get(field) in (None, "")
                                for field in ("id", "path", "sha256", "version")):
                            errors.append(f"DISCOVERY_PASS.{agent}.inventory[{item_index}] "
                                          "needs id/path/hash/version")
                    for name, entry in skill_by_name.items():
                        point = root / str(entry.get("discovery", {}).get(agent, "")) / "SKILL.md"
                        try:
                            point_path = point.relative_to(root).as_posix()
                        except ValueError:
                            errors.append(f"DISCOVERY_PASS.{agent}: {name} path leaves project root")
                            continue
                        expected_item = {
                            "id": name, "path": point_path,
                            "sha256": file_sha256(point) if point.is_file() else None,
                            "version": str(entry.get("version")),
                        }
                        if expected_item not in inventory or expected_item not in selected:
                            errors.append(f"DISCOVERY_PASS.{agent}: selected inventory does not "
                                          f"match {name} id/path/hash/version")

                behavior = outcomes.get("BEHAVIOR_PASS", {})
                cases = behavior.get("cases", {}) if isinstance(behavior, dict) else {}
                if behavior.get("proof_mode") != "synthetic-first":
                    errors.append("BEHAVIOR_PASS: proof_mode must be synthetic-first")
                for case in BEHAVIOURAL_COVERAGE:
                    result = cases.get(case, {}) if isinstance(cases, dict) else {}
                    if result.get("result") != "PASS":
                        errors.append(f"BEHAVIOR_PASS.{case}: result must be PASS")
                    else:
                        errors.extend(evidence_errors(root, result.get("evidence"),
                                                      f"BEHAVIOR_PASS.{case}"))
                private = behavior.get("private_real_data", {}) \
                    if isinstance(behavior, dict) else {}
                if private.get("authority") == "not-granted":
                    if private.get("result") != "UNKNOWN" or not private.get("reason"):
                        errors.append("private real-data proof without authority must remain UNKNOWN")
                elif private.get("authority") != "granted":
                    errors.append("private_real_data authority must be granted or not-granted")

                owner = outcomes.get("OWNER_ACCEPTED", {})
                if not owner.get("accepted_by") or not owner.get("accepted_at"):
                    errors.append("OWNER_ACCEPTED lacks accepted_by/accepted_at")
                accepted_skills = receipt.get("skills", {})
                if not isinstance(accepted_skills, dict):
                    errors.append("role acceptance receipt skills must be an object")
                    accepted_skills = {}
                for name, entry in skill_by_name.items():
                    accepted = accepted_skills.get(name, {})
                    raw = Path(str(entry.get("canonical", ""))).expanduser()
                    canonical = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
                    skill_file = canonical / "SKILL.md"
                    if skill_file.is_file() and accepted.get("skill_sha256") != file_sha256(skill_file):
                        errors.append(f"{name}: accepted skill hash does not match loaded bytes")
                    tree_digest = tracked_tree_sha256(canonical)
                    if not tree_digest or accepted.get("skill_tree_sha256") != tree_digest:
                        errors.append(f"{name}: accepted skill tree hash does not match loaded files")
                    if accepted.get("quality_review_sha256") != quality_hashes.get(name):
                        errors.append(f"{name}: accepted quality review hash does not match")
                if receipt.get("scenario_baselines") != measured_costs:
                    errors.append("role acceptance receipt does not match split cost baselines")
                usage = receipt.get("actual_usage")
                if not isinstance(usage, dict) or usage.get("status") not in {"PASS", "UNKNOWN"}:
                    errors.append("actual_usage must be separate PASS or UNKNOWN evidence")
                elif usage.get("status") == "UNKNOWN":
                    if not usage.get("reason"):
                        errors.append("actual_usage UNKNOWN requires reason")
                else:
                    runs = usage.get("runs")
                    if not isinstance(runs, list) or not runs:
                        errors.append("actual_usage PASS requires runs")
                    else:
                        for index, run in enumerate(runs):
                            fields = ("input_tokens", "cached_input_tokens", "output_tokens",
                                      "orchestration_tokens")
                            if not isinstance(run, dict) or not run.get("scenario_id") \
                                    or not run.get("source") or any(
                                    not isinstance(run.get(field), int) or run[field] < 0
                                    for field in fields):
                                errors.append(f"actual_usage.runs[{index}] needs scenario/source "
                                              "and four token counters")
                            else:
                                errors.extend(evidence_errors(root, run.get("evidence"),
                                                              f"actual_usage.runs[{index}]"))
                if receipt.get("project_roles_sha256") != file_sha256(registry):
                    errors.append("role acceptance receipt does not match PROJECT_ROLES.json")
                if not index_path.is_file() or receipt.get("knowledge_index_sha256") != file_sha256(index_path):
                    errors.append("role acceptance receipt does not match KNOWLEDGE_INDEX.json")
                if len(errors) == before_receipt:
                    notes.append(f"role acceptance: {receipt_path.relative_to(root)}; "
                                 f"accepted_by={owner.get('accepted_by')}")
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


def validate(root: Path, registry: Path, runtime_roots: list[Path] | None = None
             ) -> tuple[list[str], list[str], int]:
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
        errors, notes, count = validate(root, target, runtime_roots)
        return errors, [f"ROLE_REGISTRY_MOVED: {registry.name} -> "
                        f"{target.relative_to(root)}"] + notes, count
    if registry.name == VISIBLE_REGISTRY or "role_posture" in data:
        return validate_visible(root, data, registry, runtime_roots)
    return validate_legacy(root, data, registry)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--runtime-root", action="append", default=[], type=Path,
                        help="additional active skill root to inventory for collisions")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    registry = choose_registry(root, args.registry)
    runtime_roots = default_runtime_roots()
    runtime_roots.extend(path.expanduser().resolve() for path in args.runtime_root)
    # Preserve order while making the stated coverage exact.
    runtime_roots = list(dict.fromkeys(runtime_roots))
    errors, notes, count = validate(root, registry, runtime_roots)
    for note in notes:
        print("OK:", note)
    print(f"coverage: registry={registry} declared={count} errors={len(errors)}")
    for error in errors:
        print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
