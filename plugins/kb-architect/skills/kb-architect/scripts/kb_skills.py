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
from urllib.parse import unquote

import kb_index
import kb_paths


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

# Exact public 6.1.4 runner. Schema 4 is legacy-readable only with this released
# implementation, never with an arbitrary historical or project-provided hash.
LEGACY_BEHAVIOR_RUNNER_HASHES = {
    ("kb-behavior-run/v2", "2"): {
        "07e880689a46ec742d935375a697ee9f0d0fb7e89a2da6e592c5ace7a9e935f9",
    },
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
    repo = Path(kb_paths.git_record(probe.stdout))
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
    repo = Path(kb_paths.git_record(probe.stdout))
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


def behavior_run_errors(root: Path, case: str, value: object,
                        receipt_schema: int = 3) -> list[str]:
    """Bind a green behavior case to an executed, inspectable run.

    A tracked Markdown assertion can describe the expected behavior without
    proving that anything ran. Schema 3 records distinct artifacts and execution;
    Schema 4 additionally requires mutation sensitivity; schema 5 binds the
    failure to exactly one declared case.
    """
    label = f"BEHAVIOR_PASS.{case}"
    if not isinstance(value, dict):
        return [f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: run receipt is required"]
    required = ("run_id", "executed_at", "runtime")
    if any(not isinstance(value.get(field), str) or not value[field].strip()
           for field in required):
        return [f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                "run_id/executed_at/runtime are required"]
    if value.get("case") != case or value.get("result") != "PASS":
        return [f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: case/result do not bind PASS"]
    errors: list[str] = []
    paths: list[str] = []
    artifact_hashes: dict[str, str] = {}
    for field in ("input", "expected", "observed"):
        item = value.get(field)
        errors.extend(evidence_errors(root, [item], f"{label}.run.{field}"))
        if isinstance(item, dict) and isinstance(item.get("path"), str) \
                and isinstance(item.get("sha256"), str):
            paths.append(item["path"])
            artifact_hashes[item["path"]] = item["sha256"]
    if len(paths) != 3 or len(set(paths)) != 3:
        errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                      "input/expected/observed artifacts must be distinct")

    harness = value.get("harness")
    if not isinstance(harness, dict):
        errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                      "structured tracked harness is required")
    else:
        errors.extend(evidence_errors(root, [harness], f"{label}.run.harness"))
        argv = harness.get("argv")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "harness.argv must be a string array")
        elif receipt_schema == 5 and any(
                item.startswith(("/", "~", "\\"))
                or re.match(r"^[A-Za-z]:[\\/]", item)
                or re.search(r"(^|=)(?:[/\\]|file:/)", item, re.IGNORECASE)
                for item in argv):
            errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                          "schema-5 harness.argv cannot contain host-absolute paths")

    execution = value.get("execution_receipt")
    before_execution = len(errors)
    errors.extend(evidence_errors(root, [execution], f"{label}.run.execution_receipt"))
    if len(errors) == before_execution and isinstance(execution, dict):
        receipt_path = (root / str(execution["path"])).resolve(strict=False)
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          f"execution receipt unreadable: {exc}")
            receipt = {}
        if not isinstance(receipt, dict):
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "execution receipt must be an object")
            receipt = {}
        raw_protocol = (receipt.get("protocol"), receipt.get("runner_version"))
        protocol = raw_protocol if all(isinstance(item, str) for item in raw_protocol) \
            else (None, None)
        allowed_protocols = (("kb-behavior-run/v1", "1"),
                             ("kb-behavior-run/v2", "2"),
                             ("kb-behavior-run/v3", "3"))
        if receipt.get("schema") != 1 or protocol not in allowed_protocols:
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "canonical behavior-run receipt is required")
        if receipt_schema == 4 and protocol != ("kb-behavior-run/v2", "2"):
            if protocol != ("kb-behavior-run/v3", "3"):
                errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                              "schema 4 requires behavior-run v2+ sensitivity evidence")
        if receipt_schema == 5 and protocol != ("kb-behavior-run/v3", "3"):
            errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                          "schema 5 requires behavior-run v3 case attribution")
        runner_hash = receipt.get("runner_sha256")
        if not isinstance(runner_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", runner_hash):
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "runner_sha256 is invalid")
        elif receipt_schema in (4, 5):
            runner_path = Path(__file__).with_name("kb_behavior.py")
            current_hash = file_sha256(runner_path) if runner_path.is_file() else None
            allowed_hashes = {current_hash} if protocol == ("kb-behavior-run/v3", "3") \
                else LEGACY_BEHAVIOR_RUNNER_HASHES.get(protocol, set())
            if runner_hash not in allowed_hashes:
                errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                              "execution receipt does not bind the installed runner")
        if receipt.get("exit_code") != 0:
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "recorded harness exit must be zero")
        if not receipt.get("started_at") or receipt.get("finished_at") != value.get("executed_at"):
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "run time must bind the recorded execution")
        if receipt.get("harness") != harness:
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "execution receipt does not bind the harness")
        run_ids = receipt.get("case_run_ids", {})
        if not isinstance(run_ids, dict) or run_ids.get(case) != value.get("run_id"):
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "execution receipt does not bind case run_id")
        recorded_artifacts = receipt.get("artifacts", {})
        if not isinstance(recorded_artifacts, dict) or any(
                recorded_artifacts.get(path) != digest
                for path, digest in artifact_hashes.items()):
            errors.append(f"BEHAVIOR_EVIDENCE_UNEXECUTED {label}: "
                          "execution receipt does not bind behavior artifacts")
        if receipt_schema in (4, 5):
            control = value.get("negative_control")
            if not isinstance(control, dict):
                errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                              "negative_control is required")
            else:
                control_id = control.get("id")
                if not isinstance(control_id, str) or not control_id.strip():
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                  "negative_control.id is required")
                target = control.get("target")
                target_valid = isinstance(target, dict)
                if target_valid:
                    errors.extend(evidence_errors(
                        root, [target], f"{label}.run.negative_control.target"))
                else:
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                  "negative_control.target evidence is required")
                mutation = control.get("mutation")
                neutral_mutation = control.get("neutral_mutation")
                def valid_mutation(item: object) -> bool:
                    return isinstance(item, dict) \
                        and item.get("kind") == "replace-text" \
                        and isinstance(item.get("find"), str) \
                        and bool(item.get("find")) \
                        and isinstance(item.get("replace"), str) \
                        and item.get("find") != item.get("replace") \
                        and item.get("count") == 1

                mutation_valid = valid_mutation(mutation)
                neutral_valid = valid_mutation(neutral_mutation)
                if not mutation_valid:
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: mutation "
                                  "requires replace-text, distinct find/replace and count=1")
                if not neutral_valid:
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: neutral_mutation "
                                  "requires replace-text, distinct find/replace and count=1")
                elif mutation_valid and mutation == neutral_mutation:
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: harmful and "
                                  "neutral mutations must differ")
                expected_exit = control.get("expected_exit")
                if expected_exit != 10:
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                  "negative_control.expected_exit must be 10")
                expected_record = None
                neutral_record = None
                if target_valid and mutation_valid and neutral_valid:
                    raw_target = Path(str(target.get("path", "")))
                    target_path = (raw_target if raw_target.is_absolute()
                                   else root / raw_target).resolve(strict=False)
                    if not outside(root, target_path) and target_path.is_file():
                        harness_raw = Path(str(harness.get("path", ""))) \
                            if isinstance(harness, dict) else Path()
                        harness_path = (harness_raw if harness_raw.is_absolute()
                                        else root / harness_raw).resolve(strict=False)
                        if target_path == harness_path:
                            errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                          "negative-control target cannot be the harness")
                        try:
                            original = target_path.read_text(encoding="utf-8")
                        except (OSError, UnicodeDecodeError):
                            errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                          "mutation target must be UTF-8 text")
                        else:
                            for mutation_label, item in (
                                    ("mutation", mutation),
                                    ("neutral_mutation", neutral_mutation)):
                                if original.count(item["find"]) != 1:
                                    errors.append(
                                        f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                        f"{mutation_label} find text must occur exactly once")
                            if original.count(mutation["find"]) == 1 \
                                    and original.count(neutral_mutation["find"]) == 1 \
                                    and target_path != harness_path:
                                mutated = original.replace(
                                    mutation["find"], mutation["replace"], 1)
                                expected_record = {
                                    "id": control_id,
                                    "target_path": target_path.relative_to(root).as_posix(),
                                    "target_sha256": target.get("sha256"),
                                    "mutation": mutation,
                                    "mutated_sha256": hashlib.sha256(
                                        mutated.encode("utf-8")).hexdigest(),
                                    "expected_exit": expected_exit,
                                }
                                neutral = original.replace(
                                    neutral_mutation["find"],
                                    neutral_mutation["replace"], 1)
                                neutral_record = {
                                    "id": str(control_id) + ":neutral",
                                    "target_path": target_path.relative_to(root).as_posix(),
                                    "target_sha256": target.get("sha256"),
                                    "mutation": neutral_mutation,
                                    "mutated_sha256": hashlib.sha256(
                                        neutral.encode("utf-8")).hexdigest(),
                                    "expected_exit": 0,
                                }
                recorded = receipt.get("negative_controls", {})
                observed = recorded.get(case, {}) if isinstance(recorded, dict) else {}
                if expected_record is None or not isinstance(observed, dict) or any(
                        observed.get(key) != expected
                        for key, expected in expected_record.items()) \
                        or observed.get("actual_exit") != expected_exit:
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                  "runner-owned mutation did not fail as declared")
                neutral_recorded = receipt.get("neutral_controls", {})
                neutral_observed = neutral_recorded.get(case, {}) \
                    if isinstance(neutral_recorded, dict) else {}
                if neutral_record is None or not isinstance(neutral_observed, dict) or any(
                        neutral_observed.get(key) != expected
                        for key, expected in neutral_record.items()) \
                        or neutral_observed.get("actual_exit") != 0:
                    errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                  "runner-owned neutral mutation did not stay green")
                if receipt_schema == 5:
                    all_cases = set(run_ids) if isinstance(run_ids, dict) else set()
                    normal_expected = {name: "PASS" for name in all_cases}
                    harmful_expected = {
                        name: ("FAIL" if name == case else "PASS")
                        for name in all_cases}
                    if receipt.get("reported_results") != normal_expected \
                            or observed.get("reported_results") != harmful_expected \
                            or neutral_observed.get("reported_results") != normal_expected:
                        errors.append(f"BEHAVIOR_EVIDENCE_INADEQUATE {label}: "
                                      "receipt does not attribute failure to this case only")
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
    review_repo = (Path(kb_paths.git_record(repo_probe.stdout)).resolve()
                   if not repo_probe.returncode else root)
    if not path.is_file() or not tracked(review_repo, path):
        errors.append(f"{name}: quality review is missing or not Git-tracked")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{name}: quality review unreadable: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append(f"{name}: quality review must be an object")
        return file_sha256(path)
    if data.get("schema") != 1 or data.get("result") != "PASS":
        errors.append(f"{name}: ROLE_QUALITY_REVIEW is not PASS")
    if data.get("skill") != name or data.get("quality_owner") != entry.get("quality_owner"):
        errors.append(f"{name}: quality review identity/owner mismatch")
    if not data.get("reviewed_at"):
        errors.append(f"{name}: quality review has no reviewed_at")
    review_scope = data.get("review_scope")
    allowed_scopes = {"packaging-only", "internal-method", "external-benchmark",
                      "licensed-review"}
    if review_scope not in allowed_scopes:
        errors.append(f"{name}: ROLE_QUALITY_REVIEW needs explicit review_scope")
    elif review_scope == "packaging-only":
        errors.append(f"{name}: packaging-only review cannot be professional-method PASS")
    review = data.get("external_practice_review")
    allowed = {"performed", "deferred", "not-applicable"}
    if not isinstance(review, dict) or review.get("status") not in allowed \
            or not review.get("rationale"):
        errors.append(f"{name}: external practice review needs status and rationale")
    boundary = data.get("role_knowledge_boundary")
    if boundary is not None:
        outcomes = {"method-only", "extraction-applied", "deferred", "declined"}
        if not isinstance(boundary, dict) or boundary.get("outcome") not in outcomes:
            errors.append(f"{name}: role_knowledge_boundary has an unknown outcome")
        elif not boundary.get("reason") or not boundary.get("safe_current_mode"):
            errors.append(f"{name}: role_knowledge_boundary needs reason and safe_current_mode")
        elif boundary["outcome"] == "deferred" and not boundary.get("return_condition"):
            errors.append(f"{name}: deferred role boundary needs return_condition")
        elif boundary["outcome"] == "extraction-applied" \
                and not isinstance(boundary.get("extracted_to"), list):
            errors.append(f"{name}: applied extraction needs extracted_to array")
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


def markdown_link_targets(text: str) -> list[str]:
    """Return local-looking destinations used by Markdown links.

    Fenced and inline code are excluded.  Both inline links (including angle-bracket
    destinations with spaces) and reference-style links are recognised.  This is
    deliberately a small Markdown extractor, not a path guesser.
    """
    visible: list[str] = []
    fence_char = ""
    fence_size = 0
    for line in text.splitlines():
        marker = re.match(r"^[ ]{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if not fence_char:
                fence_char, fence_size = token[0], len(token)
            elif token[0] == fence_char and len(token) >= fence_size:
                fence_char, fence_size = "", 0
            continue
        if not fence_char:
            visible.append(line)
    source = "\n".join(visible)
    source = re.sub(r"`+[^`\n]*`+", "", source)

    destinations: list[str] = []
    inline_start = re.compile(r"!?\[[^\]\n]*\]\([ \t]*")
    for match in inline_start.finditer(source):
        cursor = match.end()
        if cursor < len(source) and source[cursor] == "<":
            end = source.find(">", cursor + 1)
            if end >= 0 and "\n" not in source[cursor + 1:end]:
                destinations.append(source[cursor + 1:end])
            continue
        start = cursor
        depth = 0
        escaped = False
        while cursor < len(source):
            char = source[cursor]
            if char == "\n" or (char.isspace() and depth == 0):
                break
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            cursor += 1
        if cursor > start and depth == 0:
            destinations.append(source[start:cursor])

    definitions: dict[str, str] = {}
    definition = re.compile(
        r"(?m)^[ ]{0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|((?:\\.|\S)+))")
    for match in definition.finditer(source):
        label = " ".join(match.group(1).split()).casefold()
        definitions[label] = match.group(2) or match.group(3)

    used: set[str] = set()
    for match in re.finditer(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]", source):
        label = match.group(2) or match.group(1)
        used.add(" ".join(label.split()).casefold())
    for match in re.finditer(r"(?<![!\[])\[([^\]\n]+)\](?![\[(])", source):
        if source[match.end():].lstrip(" \t").startswith(":"):
            continue
        used.add(" ".join(match.group(1).split()).casefold())
    destinations.extend(definitions[label] for label in used if label in definitions)
    return destinations


def role_linked_files(canonical: Path, name: str,
                      errors: list[str]) -> set[Path]:
    """Find existing local support files directly linked by the role entry.

    This is intentionally narrow.  It catches actual Markdown links without guessing
    from inline-code path mentions, which produced excessive false positives in an
    earlier live experiment.  Linked files are included automatically in cost.
    """
    skill_md = canonical / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return set()
    found: set[Path] = set()
    for raw in markdown_link_targets(text):
        value = raw.strip().strip("'\"")
        value = re.sub(r"\\([\\`*{}\[\]()#+.!_<>\- ])", r"\1", value)
        value = value.split("#", 1)[0].split("?", 1)[0]
        value = unquote(value)
        if not value or value.startswith("#") or re.match(
                r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
            continue
        if any(mark in value for mark in ("<", ">", "{", "}", "*", "$")):
            continue
        relative = Path(value)
        if relative.is_absolute():
            continue
        path = (canonical / relative).resolve(strict=False)
        if outside(canonical, path) or not path.is_file() or path == skill_md:
            continue
        probe = git(path.parent, "rev-parse", "--show-toplevel")
        repo = (Path(kb_paths.git_record(probe.stdout)).resolve()
                if not probe.returncode else canonical)
        if not tracked(repo, path):
            errors.append(f"{name}: linked role support file is not Git-tracked: {value}")
            continue
        found.add(path)
    return found


def acceptance_schema_hint(root: Path, data: dict) -> int | None:
    """Read candidate/accepted schema needed for compatibility costing."""
    acceptance = data.get("acceptance")
    if not isinstance(acceptance, dict):
        return None
    status = acceptance.get("status")
    raw = acceptance.get("receipt")
    if status != "accepted" and raw:
        # New work cannot opt out of current cost gates by downgrading its
        # receipt or misspelling its status. Legacy schemas remain readable
        # only after prior acceptance.
        return 5
    if status != "accepted":
        return None
    path = (root / str(raw or "")).resolve(strict=False)
    if not raw or outside(root, path) or not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(receipt, dict):
        return None
    return receipt.get("schema") if isinstance(receipt.get("schema"), int) else None


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
    if status not in ("required", "transitioning", "not-applicable"):
        errors.append("role_posture.status must be required, transitioning or not-applicable")
    if not policy.get("rationale"):
        errors.append("role_posture requires rationale")
    if status in ("required", "transitioning"):
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

    receipt_schema_hint = acceptance_schema_hint(root, data)

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
    skill_supports: dict[str, set[Path]] = {}
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
        link_errors = errors if receipt_schema_hint != 2 else []
        skill_supports[checked_name] = role_linked_files(
            canonical, checked_name, link_errors)
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
    control_plane_bytes = registry.stat().st_size + (
        index_path.stat().st_size if index_path.is_file() else 0)
    if status in ("required", "transitioning"):
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
                support_paths = {path for name in unique_skills
                                 for path in skill_supports.get(name, set())}
                support_bytes = sum(path.stat().st_size for path in support_paths)
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
                routed_bytes = sum(path.stat().st_size for path in paths if path)
                static_bytes = entry_bytes + support_bytes + routed_bytes
                end_to_end_bytes = static_bytes + control_plane_bytes
                accepted_semantics_bytes = (entry_bytes + routed_bytes
                                            if receipt_schema_hint == 2 else static_bytes)
                accepted_entry = scenario.get("accepted_role_entry_bytes")
                accepted_static = scenario.get("accepted_static_route_bytes")
                for label, accepted, actual in (
                        ("accepted_role_entry_bytes", accepted_entry, entry_bytes),
                        ("accepted_static_route_bytes", accepted_static,
                         accepted_semantics_bytes)):
                    if not isinstance(accepted, int) or accepted < 0:
                        errors.append(f"{scenario_id}: {label} must be a non-negative integer")
                    elif actual > accepted:
                        errors.append(f"OPTIMIZATION_REQUIRED {scenario_id}: {label} grew "
                                      f"{accepted} -> {actual} bytes")
                accepted_control = scenario.get("accepted_control_plane_bytes")
                accepted_end_to_end = scenario.get("accepted_end_to_end_bytes")
                if receipt_schema_hint == 5:
                    for label, accepted, actual in (
                            ("accepted_control_plane_bytes", accepted_control,
                             control_plane_bytes),
                            ("accepted_end_to_end_bytes", accepted_end_to_end,
                             end_to_end_bytes)):
                        if not isinstance(accepted, int) or accepted < 0:
                            errors.append(f"{scenario_id}: {label} must be a non-negative integer")
                        elif actual > accepted:
                            errors.append(f"OPTIMIZATION_REQUIRED {scenario_id}: {label} grew "
                                          f"{accepted} -> {actual} bytes")
                review_bytes = end_to_end_bytes if receipt_schema_hint == 5 \
                    else accepted_semantics_bytes
                if review_bytes > threshold and not scenario.get("accepted_reason"):
                    errors.append(f"{scenario_id}: {review_bytes} bytes exceeds review threshold "
                                  "without accepted_reason")
                elif review_bytes > threshold:
                    notes.append(f"COST_SIGNAL {scenario_id}: {review_bytes} static bytes; "
                                 f"accepted because {scenario['accepted_reason']}")
                if receipt_schema_hint == 2 and support_bytes:
                    notes.append(f"ROLE_COST_SCHEMA_2_LEGACY {scenario_id}: "
                                 f"linked-role-support={support_bytes} is migration delta; "
                                 "schema-2 accepted cost remains valid until schema 4 migration")
                measured_costs[scenario_id] = {
                    "accepted_role_entry_bytes": accepted_entry,
                    "accepted_static_route_bytes": accepted_static,
                    "route_files": declared_files,
                }
                if receipt_schema_hint == 5:
                    measured_costs[scenario_id].update({
                        "accepted_control_plane_bytes": accepted_control,
                        "accepted_end_to_end_bytes": accepted_end_to_end,
                    })
                notes.append(f"route-cost {scenario_id}: role-entry={entry_bytes}; "
                             f"linked-role-support={support_bytes}; "
                             f"static-route={static_bytes}; "
                             f"control-plane={control_plane_bytes}; "
                             f"static-end-to-end={end_to_end_bytes}")
            missing = sorted(set(role_by_id) - covered_roles)
            if missing:
                errors.append("roles absent from cost scenarios: " + ", ".join(missing))
            upper_id = cost.get("all_roles_scenario")
            upper = scenario_by_id.get(upper_id) if isinstance(upper_id, str) else None
            if upper is None or set(upper.get("roles", [])) != set(role_by_id):
                errors.append("cost_policy.all_roles_scenario must name a scenario "
                              "containing every declared role")

        acceptance = data.get("acceptance")
        acceptance_status = acceptance.get("status") \
            if isinstance(acceptance, dict) else None
        accepted_mode = acceptance_status == "accepted"
        candidate_mode = acceptance_status == "candidate"
        invalid_status = not isinstance(acceptance_status, str) \
            or acceptance_status not in ("candidate", "accepted")
        receipt_supplied = isinstance(acceptance, dict) and bool(acceptance.get("receipt"))
        pre_owner_mode = candidate_mode or (invalid_status and receipt_supplied)
        if not accepted_mode:
            errors.append("ROLE_ACCEPTANCE_REQUIRED: role manifest is not owner-accepted")
        if invalid_status:
            errors.append("ROLE_ACCEPTANCE_STATUS_INVALID: status must be candidate or accepted")
        if accepted_mode or pre_owner_mode:
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
                if not isinstance(receipt, dict):
                    errors.append("role acceptance receipt must be an object")
                    receipt = {}
                receipt_schema = receipt.get("schema")
                outcomes = receipt.get("outcomes", {})
                if receipt_schema not in (2, 3, 4, 5) or not isinstance(outcomes, dict):
                    errors.append("ROLE_ACCEPTANCE_SCHEMA_2_3_4_OR_5_REQUIRED")
                    outcomes = {}
                elif pre_owner_mode and receipt_schema != 5:
                    errors.append("ROLE_ACCEPTANCE_CANDIDATE_SCHEMA_5_REQUIRED")
                elif receipt_schema == 2:
                    notes.append("ROLE_ACCEPTANCE_SCHEMA_2_LEGACY: accepted for "
                                 "backward compatibility; migrate to schema 4 for "
                                 "machine-readable behavior and sensitivity")
                elif receipt_schema == 3:
                    notes.append("ROLE_ACCEPTANCE_SCHEMA_3_LEGACY: execution provenance "
                                 "is readable; migrate to schema 4 for negative-control "
                                 "sensitivity evidence")
                elif receipt_schema == 4:
                    notes.append("ROLE_ACCEPTANCE_SCHEMA_4_LEGACY: mutation sensitivity "
                                 "is readable; migrate to schema 5 for per-case attribution "
                                 "and portable cost evidence")
                if set(outcomes) != ACCEPTANCE_OUTCOMES:
                    errors.append("role acceptance must separate STRUCTURAL_PASS, "
                                  "DISCOVERY_PASS, BEHAVIOR_PASS and OWNER_ACCEPTED")
                for outcome in ACCEPTANCE_OUTCOMES:
                    gate = outcomes.get(outcome, {})
                    if not isinstance(gate, dict):
                        errors.append(f"{outcome}: gate must be an object")
                        continue
                    gate_status = gate.get("status")
                    if accepted_mode and gate_status != "PASS":
                        errors.append(f"{outcome}: status must be PASS")
                    elif pre_owner_mode and gate_status not in ("PASS", "PENDING", "UNKNOWN"):
                        errors.append(f"{outcome}: candidate status must be PASS, PENDING or UNKNOWN")
                    elif pre_owner_mode and gate_status in ("PENDING", "UNKNOWN"):
                        notes.append(f"candidate outcome {outcome}={gate_status}")
                    if gate_status == "PASS":
                        errors.extend(evidence_errors(root, gate.get("evidence"), outcome))

                structural = outcomes.get("STRUCTURAL_PASS", {})
                structural_pass = isinstance(structural, dict) \
                    and structural.get("status") == "PASS"
                validators = structural.get("validators", {}) if structural_pass else {}
                for name, entry in skill_by_name.items() if structural_pass else ():
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
                discovery_pass = isinstance(discovery_gate, dict) \
                    and discovery_gate.get("status") == "PASS"
                discovered_agents = discovery_gate.get("agents", {}) \
                    if discovery_pass else {}
                for agent in agents if discovery_pass else ():
                    result = discovered_agents.get(agent, {}) \
                        if isinstance(discovered_agents, dict) else {}
                    label = f"DISCOVERY_PASS.{agent}"
                    if not isinstance(result, dict):
                        errors.append(f"{label}: agent result must be an object")
                        continue
                    if result.get("fresh_context") is not True or result.get("unforced") is not True:
                        errors.append(f"{label}: fresh_context and unforced are required")
                    if result.get("new_session_required") is not True \
                            or result.get("session_boundary") != "new-session":
                        errors.append(f"{label}: new-session boundary is required")
                    inventory = result.get("inventory", [])
                    selected = result.get("selected", [])
                    if not isinstance(inventory, list) or not isinstance(selected, list):
                        errors.append(f"{label}: inventory and selected arrays required")
                        continue
                    for item_index, item in enumerate(inventory):
                        if not isinstance(item, dict) or any(
                                item.get(field) in (None, "")
                                for field in ("id", "path", "sha256", "version")):
                            errors.append(f"{label}.inventory[{item_index}] "
                                          "needs id/path/hash/version")
                    for name, entry in skill_by_name.items():
                        point = root / str(entry.get("discovery", {}).get(agent, "")) / "SKILL.md"
                        try:
                            point_path = point.relative_to(root).as_posix()
                        except ValueError:
                            errors.append(f"{label}: {name} path leaves project root")
                            continue
                        expected_item = {
                            "id": name, "path": point_path,
                            "sha256": file_sha256(point) if point.is_file() else None,
                            "version": str(entry.get("version")),
                        }
                        if expected_item not in inventory or expected_item not in selected:
                            errors.append(f"{label}: selected inventory does not "
                                          f"match {name} id/path/hash/version")

                behavior = outcomes.get("BEHAVIOR_PASS", {})
                behavior_pass = isinstance(behavior, dict) \
                    and behavior.get("status") == "PASS"
                cases = behavior.get("cases", {}) if behavior_pass else {}
                if behavior_pass and not isinstance(cases, dict):
                    errors.append("BEHAVIOR_PASS.cases must be an object")
                    cases = {}
                if behavior_pass and behavior.get("proof_mode") != "synthetic-first":
                    errors.append("BEHAVIOR_PASS: proof_mode must be synthetic-first")
                if behavior_pass and receipt_schema in (3, 4, 5):
                    declared_scope = acceptance.get("behavior_scope")
                    if declared_scope != "shared":
                        errors.append("acceptance.behavior_scope must be shared")
                    if behavior.get("runtime_scope") != declared_scope:
                        errors.append("BEHAVIOR_PASS.runtime_scope must match "
                                      "acceptance.behavior_scope")
                for case in BEHAVIOURAL_COVERAGE if behavior_pass else ():
                    result = cases.get(case, {})
                    if not isinstance(result, dict):
                        errors.append(f"BEHAVIOR_PASS.{case}: case must be an object")
                        continue
                    if result.get("result") != "PASS":
                        errors.append(f"BEHAVIOR_PASS.{case}: result must be PASS")
                    elif receipt_schema in (3, 4, 5):
                        errors.extend(behavior_run_errors(
                            root, case, result.get("run"), receipt_schema))
                    else:
                        errors.extend(evidence_errors(root, result.get("evidence"),
                                                      f"BEHAVIOR_PASS.{case}"))
                if behavior_pass and receipt_schema in (4, 5) and isinstance(cases, dict):
                    controls = []
                    for case in BEHAVIOURAL_COVERAGE:
                        result = cases.get(case, {})
                        run = result.get("run", {}) if isinstance(result, dict) else {}
                        controls.append(run.get("negative_control", {})
                                        if isinstance(run, dict) else {})
                    ids = [item.get("id") for item in controls
                           if isinstance(item, dict) and isinstance(item.get("id"), str)]
                    mutations = [json.dumps(
                        {"target": item.get("target"), "mutation": item.get("mutation")},
                        sort_keys=True) for item in controls if isinstance(item, dict)]
                    if len(ids) != len(set(ids)) or len(mutations) != len(set(mutations)):
                        errors.append("BEHAVIOR_EVIDENCE_INADEQUATE: schema-4/5 negative "
                                      "controls require unique ids and target/mutation per case")
                private = behavior.get("private_real_data", {}) \
                    if behavior_pass else {}
                if behavior_pass and not isinstance(private, dict):
                    errors.append("BEHAVIOR_PASS.private_real_data must be an object")
                    private = {}
                if behavior_pass and private.get("authority") == "not-granted":
                    if private.get("result") != "UNKNOWN" or not private.get("reason"):
                        errors.append("private real-data proof without authority must remain UNKNOWN")
                elif behavior_pass and private.get("authority") != "granted":
                    errors.append("private_real_data authority must be granted or not-granted")

                owner = outcomes.get("OWNER_ACCEPTED", {})
                if isinstance(owner, dict) and owner.get("status") == "PASS" \
                        and (not owner.get("accepted_by") or not owner.get("accepted_at")):
                    errors.append("OWNER_ACCEPTED lacks accepted_by/accepted_at")
                accepted_skills = receipt.get("skills", {})
                if not isinstance(accepted_skills, dict):
                    errors.append("role acceptance receipt skills must be an object")
                    accepted_skills = {}
                for name, entry in skill_by_name.items():
                    accepted = accepted_skills.get(name, {})
                    if not isinstance(accepted, dict):
                        errors.append(f"{name}: accepted skill binding must be an object")
                        accepted = {}
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
                if not isinstance(usage, dict) or usage.get("status") not in ("PASS", "UNKNOWN"):
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
                if isinstance(usage, dict) and usage.get("status") in ("PASS", "UNKNOWN"):
                    notes.append(f"actual-usage={usage['status']}")
                if receipt.get("project_roles_sha256") != file_sha256(registry):
                    errors.append("role acceptance receipt does not match PROJECT_ROLES.json")
                if not index_path.is_file() or receipt.get("knowledge_index_sha256") != file_sha256(index_path):
                    errors.append("role acceptance receipt does not match KNOWLEDGE_INDEX.json")
                if len(errors) == before_receipt:
                    if accepted_mode:
                        notes.append(f"role acceptance: {receipt_path.relative_to(root)}; "
                                     f"accepted_by={owner.get('accepted_by')}")
                    else:
                        notes.append(f"pre-owner receipt checked independently: "
                                     f"{receipt_path.relative_to(root)}")
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
    if data.get("schema") not in (1, 2) or not isinstance(data.get("skills"), list):
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
