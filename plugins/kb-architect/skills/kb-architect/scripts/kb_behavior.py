#!/usr/bin/env python3
"""Record one explicit synthetic role-behavior harness execution.

The ordinary role checker never executes project code.  This command is the
separate, explicit execution boundary: it runs one tracked Python harness
without a shell, with a reduced environment, and writes a receipt binding the
harness and every input/expected/observed artifact declared by schema 3.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PROTOCOL = "kb-behavior-run/v1"
RUNNER_VERSION = "1"
OUTPUT_LIMIT = 32_768


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def inside(root: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label}: project-relative path is required")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError(f"{label}: absolute path is forbidden")
    path = (root / candidate).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}: path leaves project root") from exc
    return path


def tracked(root: Path, path: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", relative],
        capture_output=True, text=True)
    return result.returncode == 0


def load_plan(root: Path, acceptance_path: Path) -> tuple[dict, dict[str, str], dict[str, str]]:
    data = json.loads(acceptance_path.read_text(encoding="utf-8"))
    behavior = data.get("outcomes", {}).get("BEHAVIOR_PASS", {})
    cases = behavior.get("cases", {}) if isinstance(behavior, dict) else {}
    if data.get("schema") != 3 or not isinstance(cases, dict) or not cases:
        raise ValueError("schema-3 BEHAVIOR_PASS.cases are required")

    harnesses: list[dict] = []
    case_run_ids: dict[str, str] = {}
    artifacts: dict[str, str] = {}
    for case, result in cases.items():
        run = result.get("run", {}) if isinstance(result, dict) else {}
        harness = run.get("harness") if isinstance(run, dict) else None
        if not isinstance(harness, dict):
            raise ValueError(f"{case}: structured harness is required")
        harnesses.append(harness)
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"{case}: run_id is required")
        case_run_ids[str(case)] = run_id
        for field in ("input", "expected", "observed"):
            item = run.get(field)
            if not isinstance(item, dict):
                raise ValueError(f"{case}.{field}: artifact is required")
            path = inside(root, item.get("path"), f"{case}.{field}")
            artifacts[path.relative_to(root).as_posix()] = str(item.get("sha256", ""))

    harness = harnesses[0]
    if any(item != harness for item in harnesses[1:]):
        raise ValueError("all shared behavior cases must bind one identical harness")
    return harness, case_run_ids, artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="project Git root")
    parser.add_argument("--acceptance", default="ROLE_ACCEPTANCE.json")
    parser.add_argument("--receipt", default="role-acceptance/behavior-execution.json")
    parser.add_argument("--execute", action="store_true",
                        help="explicitly authorize the tracked synthetic harness")
    parser.add_argument("--replace", action="store_true",
                        help="replace an earlier execution receipt")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not args.execute:
        print("BEHAVIOR_EXECUTION_NOT_AUTHORIZED: add --execute", file=sys.stderr)
        return 2
    if not (1 <= args.timeout_seconds <= 600):
        print("timeout must be between 1 and 600 seconds", file=sys.stderr)
        return 2
    try:
        acceptance = inside(root, args.acceptance, "acceptance")
        receipt = inside(root, args.receipt, "receipt")
        harness, case_run_ids, declared_artifacts = load_plan(root, acceptance)
        harness_path = inside(root, harness.get("path"), "harness")
        harness_hash = str(harness.get("sha256", ""))
        harness_argv = harness.get("argv")
        if harness_path.suffix != ".py":
            raise ValueError("harness must be a tracked Python file")
        if not harness_path.is_file() or not tracked(root, harness_path):
            raise ValueError("harness is missing or not Git-tracked")
        if sha256(harness_path) != harness_hash:
            raise ValueError("harness hash does not match")
        if not isinstance(harness_argv, list) or not all(
                isinstance(item, str) for item in harness_argv):
            raise ValueError("harness.argv must be a string array")
        if receipt.exists() and not args.replace:
            raise ValueError("receipt already exists; use --replace for a new run")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BEHAVIOR_EXECUTION_BLOCKED: {exc}", file=sys.stderr)
        return 2

    safe_env = {
        key: value for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "PYTHONIOENCODING", "TMPDIR"}
    }
    started = utc_now()
    try:
        result = subprocess.run(
            [sys.executable, str(harness_path), *harness_argv],
            cwd=root, env=safe_env, capture_output=True, text=True,
            timeout=args.timeout_seconds)
        exit_code = result.returncode
        stdout = result.stdout[-OUTPUT_LIMIT:]
        stderr = result.stderr[-OUTPUT_LIMIT:]
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = (exc.stdout or "")[-OUTPUT_LIMIT:]
        stderr = ((exc.stderr or "") + "\nTIMEOUT")[-OUTPUT_LIMIT:]
    finished = utc_now()

    actual_artifacts: dict[str, str] = {}
    artifact_error = None
    for relative, declared_hash in declared_artifacts.items():
        path = root / relative
        if not path.is_file():
            artifact_error = f"artifact missing after run: {relative}"
            exit_code = exit_code or 3
            continue
        actual = sha256(path)
        actual_artifacts[relative] = actual
        if declared_hash != actual:
            artifact_error = f"artifact hash differs after run: {relative}"
            exit_code = exit_code or 3

    record = {
        "schema": 1,
        "protocol": PROTOCOL,
        "runner_version": RUNNER_VERSION,
        "runner_sha256": sha256(Path(__file__)),
        "started_at": started,
        "finished_at": finished,
        "exit_code": exit_code,
        "harness": {
            "path": harness_path.relative_to(root).as_posix(),
            "sha256": harness_hash,
            "argv": harness_argv,
        },
        "case_run_ids": case_run_ids,
        "artifacts": actual_artifacts,
        "stdout_tail": stdout,
        "stderr_tail": stderr,
    }
    if artifact_error:
        record["artifact_error"] = artifact_error
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=receipt.parent, delete=False) as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(receipt)
    print(f"BEHAVIOR_EXECUTION_RECORDED: {receipt.relative_to(root)} exit={exit_code}")
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
