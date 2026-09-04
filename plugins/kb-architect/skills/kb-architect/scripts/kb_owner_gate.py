#!/usr/bin/env python3
"""Fail closed when a consumer-project task tries to maintain kb-architect.

The active task root matters, not the directory passed to Git after the task
started.  Codex exposes a stable thread id; its local session metadata records
the root that the task was created with.  Claude project-root environment
variables are used when available.  With no runtime-bound root, irreversible
maintenance remains UNKNOWN rather than being inferred from ``cwd``.

This is a guard against ordinary orchestration mistakes, not a security
boundary against an actor that can alter hooks, environment and repository
files.  A consumer task is routed to an immutable defect report instead.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping


OWNER_REPOSITORY = "sugestr/kb-architect-lab"
CLAUDE_ROOT_KEYS = ("CLAUDE_PROJECT_DIR", "CLAUDE_WORKING_DIRECTORY")


def git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            timeout=20)
    except Exception:
        return None
    return result.stdout.rstrip("\r\n") if result.returncode == 0 else None


def repository_slug(root: Path) -> str | None:
    remote = git(root, "remote", "get-url", "origin")
    if not remote:
        return None
    value = remote.strip().replace("\\", "/").rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if ":" in value and "://" not in value:
        value = value.split(":", 1)[1]
    else:
        value = value.split("://", 1)[-1]
        parts = value.split("/", 1)
        value = parts[1] if len(parts) == 2 else parts[0]
    bits = [part for part in value.split("/") if part]
    return "/".join(bits[-2:]).lower() if len(bits) >= 2 else None


def is_owner_repository(root: Path) -> bool:
    return repository_slug(root) == OWNER_REPOSITORY.lower()


def codex_session_root(thread_id: str, sessions_root: Path) -> Path | None:
    if not thread_id or not sessions_root.is_dir():
        return None
    candidates = sorted(
        sessions_root.rglob(f"*{thread_id}.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            with path.open(encoding="utf-8") as stream:
                first = stream.readline()
            row = json.loads(first)
            payload = row.get("payload", {})
            if (row.get("type") == "session_meta"
                    and payload.get("id") == thread_id
                    and isinstance(payload.get("cwd"), str)):
                return Path(payload["cwd"]).expanduser().resolve()
        except (OSError, ValueError, TypeError):
            continue
    return None


def runtime_project_root(
        env: Mapping[str, str] | None = None,
        sessions_root: Path | None = None) -> tuple[Path | None, str | None]:
    values = os.environ if env is None else env
    thread_id = values.get("CODEX_THREAD_ID", "").strip()
    if thread_id:
        root = codex_session_root(
            thread_id,
            sessions_root or Path.home() / ".codex" / "sessions")
        if root:
            return root, f"codex-session:{thread_id}"
        return None, f"codex-session-metadata-missing:{thread_id}"
    for key in CLAUDE_ROOT_KEYS:
        raw = values.get(key, "").strip()
        if raw:
            return Path(raw).expanduser().resolve(), key.lower()
    return None, None


def evaluate(
        project: Path,
        require_runtime_owner: bool = False,
        env: Mapping[str, str] | None = None,
        sessions_root: Path | None = None) -> dict:
    target = project.expanduser().resolve()
    active, evidence = runtime_project_root(env=env, sessions_root=sessions_root)
    target_owner = is_owner_repository(target)
    if active is not None:
        active_owner = is_owner_repository(active)
        if target_owner and active_owner:
            return {
                "state": "PASS",
                "code": 0,
                "target": str(target),
                "active_project": str(active),
                "evidence": evidence,
            }
        return {
            "state": "BLOCKED_WRONG_EXECUTOR",
            "code": 3,
            "target": str(target),
            "active_project": str(active),
            "evidence": evidence,
        }
    if require_runtime_owner:
        return {
            "state": "OWNER_CONTEXT_UNKNOWN",
            "code": 2,
            "target": str(target),
            "active_project": None,
            "evidence": evidence or "runtime-project-root-unavailable",
        }
    if target_owner:
        return {
            "state": "PASS",
            "code": 0,
            "target": str(target),
            "active_project": str(target),
            "evidence": "explicit-project-root",
        }
    return {
        "state": "BLOCKED_WRONG_EXECUTOR",
        "code": 3,
        "target": str(target),
        "active_project": str(target),
        "evidence": "explicit-project-root",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True,
                        help="active project root (runtime-bound evidence wins over cwd)")
    parser.add_argument("--effect", choices=("edit", "commit", "push", "release", "runtime"),
                        default="edit")
    parser.add_argument("--require-runtime-owner", action="store_true",
                        help="reject cwd-only evidence; used by hooks and release tooling")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate(Path(args.project), args.require_runtime_owner)
    result["effect"] = args.effect
    result["owner_repository"] = OWNER_REPOSITORY
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return int(result["code"])

    print(result["state"])
    print(f"effect={args.effect}")
    print(f"owner_repository={OWNER_REPOSITORY}")
    print(f"target={result['target']}")
    print(f"active_project={result['active_project'] or 'UNKNOWN'}")
    print(f"evidence={result['evidence']}")
    if result["state"] != "PASS":
        active = result["active_project"] or "<active-project-root>"
        report = Path(__file__).with_name("kb_report.py")
        print("allowed_effect=prepare_defect_report")
        print(f"next=python3 {report} --project {active} --report <report.md>")
        print("Start or continue a task bound to the owner repository for maintenance.")
    return int(result["code"])


if __name__ == "__main__":
    sys.exit(main())
