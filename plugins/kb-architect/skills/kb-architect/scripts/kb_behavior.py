#!/usr/bin/env python3
"""Record one explicit synthetic role-behavior harness execution.

The ordinary role checker never executes project code.  This command is the
separate, explicit execution boundary: it runs one tracked Python harness
without a shell, with a reduced environment, and writes a receipt binding the
harness and every input/expected/observed artifact declared by schema 3/4/5. Schema 4
adds mutations; schema 5 also attributes failure to the declared semantic case.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


PROTOCOL = "kb-behavior-run/v3"
RUNNER_VERSION = "3"
RESULT_PROTOCOL = "kb-behavior-result/v1"
OUTPUT_LIMIT = 32_768
NEGATIVE_CONTROL_EXIT = 10


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def reported_results(stdout: str, cases: set[str]) -> dict[str, str] | None:
    """Read the final structured case report without trusting free-form text."""
    prefix = "KB_BEHAVIOR_RESULT "
    lines = [line[len(prefix):] for line in stdout.splitlines()
             if line.startswith(prefix)]
    if len(lines) != 1:
        return None
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError:
        return None
    results = value.get("results") if isinstance(value, dict) \
        and value.get("protocol") == RESULT_PROTOCOL else None
    if not isinstance(results, dict) or set(results) != cases \
            or any(result not in {"PASS", "FAIL"} for result in results.values()):
        return None
    return results


def host_absolute_arg(value: str) -> bool:
    """Reject POSIX, home, Windows drive/UNC and file-URI host locators."""
    return value.startswith(("/", "~", "\\")) \
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None \
        or re.search(r"(^|=)(?:[/\\]|file:/)", value, re.IGNORECASE) is not None


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


def mutation_spec(case: str, label: str, value: object) -> dict:
    if not isinstance(value, dict) or value.get("kind") != "replace-text":
        raise ValueError(f"{case}: {label}.kind must be replace-text")
    find = value.get("find")
    replace = value.get("replace")
    count = value.get("count")
    if not isinstance(find, str) or not find or not isinstance(replace, str) \
            or find == replace or count != 1:
        raise ValueError(
            f"{case}: {label} requires distinct find/replace and count=1")
    return value


def control_spec(root: Path, case: str, control: object) -> tuple[Path, dict, dict]:
    if not isinstance(control, dict):
        raise ValueError(f"{case}: negative_control is required by schema 4/5")
    control_id = control.get("id")
    if not isinstance(control_id, str) or not control_id.strip():
        raise ValueError(f"{case}: negative_control.id is required")
    target = control.get("target")
    if not isinstance(target, dict):
        raise ValueError(f"{case}: negative_control.target evidence is required")
    target_path = inside(root, target.get("path"), f"{case}.negative_control.target")
    if not target_path.is_file() or target_path.is_symlink() or not tracked(root, target_path):
        raise ValueError(f"{case}: negative-control target must be a tracked regular file")
    target_hash = target.get("sha256")
    if target_hash != sha256(target_path):
        raise ValueError(f"{case}: negative-control target hash does not match")
    mutation = mutation_spec(case, "mutation", control.get("mutation"))
    neutral = mutation_spec(case, "neutral_mutation", control.get("neutral_mutation"))
    if mutation == neutral:
        raise ValueError(f"{case}: harmful and neutral mutations must differ")
    try:
        text = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{case}: mutation target must be UTF-8 text") from exc
    for label, item in (("mutation", mutation), ("neutral_mutation", neutral)):
        if text.count(item["find"]) != 1:
            raise ValueError(f"{case}: {label} find text must occur exactly once")
    if control.get("expected_exit") != NEGATIVE_CONTROL_EXIT:
        raise ValueError(
            f"{case}: negative_control.expected_exit must be {NEGATIVE_CONTROL_EXIT}")
    return target_path, mutation, neutral


def copy_tracked_tree(root: Path, destination: Path) -> None:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
    for raw in listed.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", errors="surrogateescape"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("tracked path leaves project root")
        source = root / relative
        target = destination / relative
        if source.is_symlink():
            link = os.readlink(source)
            if os.path.isabs(link):
                raise ValueError(f"tracked symlink is absolute: {relative}")
            resolved = (source.parent / link).resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"tracked symlink leaves project root: {relative}") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    subprocess.run(["git", "-C", str(destination), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(destination), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(destination), "-c", "user.name=kb-behavior-runner",
         "-c", "user.email=runner@example.invalid", "commit", "-qm", "fixture"],
        check=True)


def apply_control(root: Path, case: str, control: dict, *, neutral: bool = False) -> dict:
    target_path, harmful, harmless = control_spec(root, case, control)
    mutation = harmless if neutral else harmful
    text = target_path.read_text(encoding="utf-8")
    mutated = text.replace(mutation["find"], mutation["replace"], 1)
    target_path.write_text(mutated, encoding="utf-8")
    return {
        "id": control["id"] + (":neutral" if neutral else ""),
        "target_path": target_path.relative_to(root).as_posix(),
        "target_sha256": control["target"]["sha256"],
        "mutation": mutation,
        "mutated_sha256": sha256(target_path),
        "expected_exit": 0 if neutral else control["expected_exit"],
    }


def load_plan(root: Path, acceptance_path: Path
              ) -> tuple[int, dict, dict[str, str], dict[str, str], dict[str, dict]]:
    data = json.loads(acceptance_path.read_text(encoding="utf-8"))
    behavior = data.get("outcomes", {}).get("BEHAVIOR_PASS", {})
    cases = behavior.get("cases", {}) if isinstance(behavior, dict) else {}
    schema = data.get("schema")
    if schema not in {3, 4, 5} or not isinstance(cases, dict) or not cases:
        raise ValueError("schema-3/4/5 BEHAVIOR_PASS.cases are required")

    harnesses: list[dict] = []
    case_run_ids: dict[str, str] = {}
    artifacts: dict[str, str] = {}
    controls: dict[str, dict] = {}
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
        if schema in {4, 5}:
            control = run.get("negative_control")
            control_spec(root, str(case), control)
            controls[str(case)] = control

    harness = harnesses[0]
    if any(item != harness for item in harnesses[1:]):
        raise ValueError("all shared behavior cases must bind one identical harness")
    if schema in {4, 5}:
        ids = [control["id"] for control in controls.values()]
        mutations = [json.dumps(
            {"target": control["target"], "mutation": control["mutation"]},
            sort_keys=True) for control in controls.values()]
        if len(ids) != len(set(ids)) or len(mutations) != len(set(mutations)):
            raise ValueError(
                "schema-4/5 negative controls require unique ids and target/mutation per case")
        harness_path = inside(root, harness.get("path"), "harness")
        for case, control in controls.items():
            target_path, _harmful, _harmless = control_spec(root, case, control)
            if target_path == harness_path:
                raise ValueError(f"{case}: negative-control target cannot be the harness")
    return schema, harness, case_run_ids, artifacts, controls


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
        schema, harness, case_run_ids, declared_artifacts, controls = load_plan(
            root, acceptance)
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
        if schema == 5 and any(host_absolute_arg(item) for item in harness_argv):
            raise ValueError("schema-5 harness.argv cannot contain host-absolute paths")
        if receipt.exists() and not args.replace:
            raise ValueError("receipt already exists; use --replace for a new run")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BEHAVIOR_EXECUTION_BLOCKED: {exc}", file=sys.stderr)
        return 2

    safe_env = {
        key: value for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "PYTHONIOENCODING", "TMPDIR"}
    }
    safe_env["KB_ARCHITECT_SCRIPTS"] = str(Path(__file__).resolve().parent)
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
    normal_report = reported_results(stdout, set(case_run_ids)) if schema == 5 else None
    if schema == 5 and (exit_code != 0 or normal_report != {
            case: "PASS" for case in case_run_ids}):
        exit_code = exit_code or 5
        stderr = (stderr + "\nCASE_ATTRIBUTION_INVALID: normal run must report all PASS")[
            -OUTPUT_LIMIT:]
    negative_results: dict[str, dict] = {}
    neutral_results: dict[str, dict] = {}
    if exit_code == 0 and schema in {4, 5}:
        for case, control in controls.items():
            control_record: dict = {}
            try:
                with tempfile.TemporaryDirectory(prefix="kb-behavior-negative-") as folder:
                    negative_root = Path(folder).resolve()
                    copy_tracked_tree(root, negative_root)
                    control_record = apply_control(negative_root, case, control)
                    negative_harness = negative_root / harness_path.relative_to(root)
                    negative = subprocess.run(
                        [sys.executable, str(negative_harness), *harness_argv],
                        cwd=negative_root, env=safe_env, capture_output=True, text=True,
                        timeout=args.timeout_seconds)
                    actual_exit = negative.returncode
                    negative_stdout = negative.stdout[-OUTPUT_LIMIT:]
                    negative_stderr = negative.stderr[-OUTPUT_LIMIT:]
                    negative_report = reported_results(
                        negative.stdout, set(case_run_ids)) if schema == 5 else None
            except subprocess.TimeoutExpired as exc:
                actual_exit = 124
                negative_stdout = (exc.stdout or "")[-OUTPUT_LIMIT:]
                negative_stderr = ((exc.stderr or "") + "\nTIMEOUT")[-OUTPUT_LIMIT:]
                negative_report = None
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                actual_exit = 125
                negative_stdout = ""
                negative_stderr = f"NEGATIVE_CONTROL_SETUP_FAILED: {exc}"
                negative_report = None
            expected_exit = control["expected_exit"]
            negative_results[case] = {
                **control_record,
                "actual_exit": actual_exit,
                "stdout_tail": negative_stdout,
                "stderr_tail": negative_stderr,
                "reported_results": negative_report,
            }
            attributed = negative_report == {
                name: ("FAIL" if name == case else "PASS")
                for name in case_run_ids} if schema == 5 else True
            if actual_exit != expected_exit or not attributed:
                exit_code = exit_code or 4
            neutral_record: dict = {}
            try:
                with tempfile.TemporaryDirectory(prefix="kb-behavior-neutral-") as folder:
                    neutral_root = Path(folder).resolve()
                    copy_tracked_tree(root, neutral_root)
                    neutral_record = apply_control(
                        neutral_root, case, control, neutral=True)
                    neutral_harness = neutral_root / harness_path.relative_to(root)
                    neutral_run = subprocess.run(
                        [sys.executable, str(neutral_harness), *harness_argv],
                        cwd=neutral_root, env=safe_env, capture_output=True, text=True,
                        timeout=args.timeout_seconds)
                    neutral_exit = neutral_run.returncode
                    neutral_stdout = neutral_run.stdout[-OUTPUT_LIMIT:]
                    neutral_stderr = neutral_run.stderr[-OUTPUT_LIMIT:]
                    neutral_report = reported_results(
                        neutral_run.stdout, set(case_run_ids)) if schema == 5 else None
            except subprocess.TimeoutExpired as exc:
                neutral_exit = 124
                neutral_stdout = (exc.stdout or "")[-OUTPUT_LIMIT:]
                neutral_stderr = ((exc.stderr or "") + "\nTIMEOUT")[-OUTPUT_LIMIT:]
                neutral_report = None
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                neutral_exit = 125
                neutral_stdout = ""
                neutral_stderr = f"NEUTRAL_CONTROL_SETUP_FAILED: {exc}"
                neutral_report = None
            neutral_results[case] = {
                **neutral_record,
                "actual_exit": neutral_exit,
                "stdout_tail": neutral_stdout,
                "stderr_tail": neutral_stderr,
                "reported_results": neutral_report,
            }
            neutral_attributed = neutral_report == {
                name: "PASS" for name in case_run_ids} if schema == 5 else True
            if neutral_exit != 0 or not neutral_attributed:
                exit_code = exit_code or 4
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
        "reported_results": normal_report,
        "negative_controls": negative_results,
        "neutral_controls": neutral_results,
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
