#!/usr/bin/env python3
"""Route one kb-architect defect/optimization report to its real recipient.

Local owner projects deliver to the declared/private laboratory inbox. Projects
without that writable route publish an anonymised GitHub issue. Preview is the
default; --do performs the delivery and never calls a prepared report delivered.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

import kb_paths


GITHUB_REPOSITORY = "sugestr/kb-architect"
GITHUB_ISSUES = f"https://github.com/{GITHUB_REPOSITORY}/issues"
REPORT_KEYS = ("инбокс отчётов", "report inbox", "defect report inbox")
ROUTE_KEYS = ("маршрут отчётов", "report route", "defect report route")


def git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            timeout=30)
    except Exception:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def declared_inbox(root: Path) -> Path | None:
    raw, _source = kb_paths.declared_value(str(root), REPORT_KEYS)
    if not raw:
        return None
    value = os.path.expanduser(raw.strip().strip("`*_\"' "))
    path = Path(value) if os.path.isabs(value) else root / value
    return path.resolve()


def private_lab_inbox(root: Path) -> Path | None:
    override = os.environ.get("KB_ARCHITECT_REPORT_INBOX")
    if override:
        return Path(os.path.expanduser(override)).resolve()
    top_raw = git(root, "rev-parse", "--show-toplevel")
    top = Path(top_raw) if top_raw else root
    candidate = top.parent / "kb-architect"
    remote = git(candidate, "remote", "get-url", "origin")
    inbox = candidate / "inbox"
    if (remote and remote.rstrip("/").removesuffix(".git").endswith(
            "sugestr/kb-architect-lab") and inbox.is_dir()):
        return inbox.resolve()
    return None


def local_target(root: Path) -> Path | None:
    target = declared_inbox(root) or private_lab_inbox(root)
    return target if target and target.is_dir() and os.access(target, os.W_OK) else None


def declared_route(root: Path) -> str | None:
    raw, _source = kb_paths.declared_value(str(root), ROUTE_KEYS)
    if not raw:
        return None
    value = raw.strip().lower()
    if value in {"local", "local-inbox", "локальный", "локальный инбокс"}:
        return "local"
    if value in {"github", "github-issue", "remote", "удалённый", "удаленный"}:
        return "github"
    return None


def anonymised(text: str) -> bool:
    match = re.search(
        r"^(?:режим подробности|detail mode):\s*(.+)$", text,
        re.IGNORECASE | re.MULTILINE)
    return bool(match and re.search(r"обезлич|anonym", match.group(1), re.I))


def title(text: str, report: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            value = line[2:].strip()
            if value:
                return "[kb-architect] " + value[:180]
    return "[kb-architect] " + report.stem[:180]


def copy_local(report: Path, inbox: Path) -> tuple[int, str]:
    destination = inbox / report.name
    if destination.exists():
        if destination.read_bytes() == report.read_bytes():
            return 0, f"DELIVERED local (already present): {destination}"
        return 2, f"BLOCKED: target exists with different content: {destination}"
    fd, staged_name = tempfile.mkstemp(prefix=".kb-report-", dir=str(inbox))
    os.close(fd)
    staged = Path(staged_name)
    try:
        shutil.copyfile(report, staged)
        os.replace(staged, destination)
    finally:
        try:
            staged.unlink()
        except OSError:
            pass
    return 0, f"DELIVERED local: {destination}"


def publish_github(report: Path, text: str) -> tuple[int, str]:
    if not anonymised(text):
        return 2, ("BLOCKED: GitHub accepts only an anonymised report; set "
                   "`режим подробности: обезличенный` and remove private data")
    command = ["gh", "issue", "create", "--repo", GITHUB_REPOSITORY,
               "--title", title(text, report), "--body-file", str(report)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return 1, f"PREPARED: gh is unavailable; open {GITHUB_ISSUES}/new"
    except Exception as exc:
        return 1, f"PREPARED: GitHub delivery not confirmed: {exc}"
    if result.returncode != 0:
        why = (result.stderr.strip().splitlines() or
               [f"exit {result.returncode}"])[0]
        return 1, f"PREPARED: GitHub delivery not confirmed: {why}"
    url = (result.stdout.strip().splitlines() or [GITHUB_ISSUES])[0]
    return 0, f"DELIVERED github: {url}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--target", choices=("auto", "local", "github"),
                        default="auto")
    parser.add_argument("--do", "--сделать", action="store_true", dest="do_send")
    parser.add_argument("--public-safe", action="store_true",
                        help="confirm the report was reviewed for public GitHub")
    args = parser.parse_args()

    root = Path(os.path.expanduser(args.project)).resolve()
    report = Path(os.path.expanduser(args.report)).resolve()
    if not root.is_dir():
        print(f"BLOCKED: project root not found: {root}")
        return 2
    if not report.is_file():
        print(f"BLOCKED: report not found: {report}")
        return 2
    text = report.read_text(encoding="utf-8", errors="replace")
    inbox = local_target(root)
    route = args.target
    if route == "auto":
        route = declared_route(root) or ("local" if inbox else "github")
    if route == "local" and not inbox:
        print("BLOCKED: no writable declared/private laboratory report inbox")
        return 2

    if not args.do_send:
        if route == "local":
            print(f"PREPARED local: {inbox / report.name}")
        else:
            print(f"PREPARED github: {GITHUB_ISSUES}/new")
            print("Public delivery requires an anonymised report, --public-safe and --do")
        return 1

    if route == "local":
        code, message = copy_local(report, inbox)
    else:
        if not args.public_safe:
            print("BLOCKED: --public-safe is required before public GitHub delivery")
            return 2
        code, message = publish_github(report, text)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
