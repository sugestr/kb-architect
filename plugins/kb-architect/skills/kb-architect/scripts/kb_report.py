#!/usr/bin/env python3
"""Route one kb-architect defect/optimization report to its real recipient.

Local owner projects deliver to the declared/private laboratory inbox.  A local
address remains local even when the current runtime cannot write it: that is
``BLOCKED_LOCAL``, never permission to disclose the report on GitHub. Projects
whose declared route is GitHub may publish an anonymised issue. Preview is the
default; --do performs delivery and never calls a prepared report delivered.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
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
REPORT_INDEX = "REPORT_INDEX.json"


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
    # Recipient and current write authority are different facts.  Preserve an
    # explicitly declared local address even when this sandbox cannot write it;
    # the caller must receive BLOCKED_LOCAL, never a silent public fallback.
    return target


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


def report_id(report: Path) -> str:
    return "sha256:" + hashlib.sha256(report.read_bytes()).hexdigest()


def _load_index(inbox: Path) -> dict:
    path = inbox / REPORT_INDEX
    if not path.exists():
        return {"schema": 1, "reports": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("reports"), dict):
        raise ValueError(f"unsupported {REPORT_INDEX}")
    return data


def _inside(folder: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _parent_entry(inbox: Path, index: dict, reference: str) -> tuple[str, dict]:
    reports = index["reports"]
    if reference in reports:
        return reference, reports[reference]
    candidate = Path(os.path.expanduser(reference))
    if not candidate.is_absolute():
        candidate = inbox / candidate
    candidate = candidate.resolve()
    if not _inside(inbox, candidate) or not candidate.is_file():
        raise ValueError(f"linked report not found in local inbox: {reference}")
    identifier = report_id(candidate)
    entry = reports.setdefault(identifier, {
        "id": identifier,
        "filename": candidate.relative_to(inbox.resolve()).as_posix(),
        "sha256": identifier.removeprefix("sha256:"),
        "delivered_at": datetime.fromtimestamp(
            candidate.stat().st_mtime, timezone.utc).isoformat(),
        "relations": {},
    })
    return identifier, entry


def _write_index(inbox: Path, data: dict) -> None:
    fd, staged_name = tempfile.mkstemp(prefix=".kb-report-index-", dir=str(inbox))
    os.close(fd)
    staged = Path(staged_name)
    try:
        staged.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        os.replace(staged, inbox / REPORT_INDEX)
    finally:
        try:
            staged.unlink()
        except OSError:
            pass


def copy_local(report: Path, inbox: Path, relation: tuple[str, str] | None
               ) -> tuple[int, str]:
    destination = inbox / report.name
    identifier = report_id(report)
    try:
        index = _load_index(inbox)
        reports = index["reports"]
        entry = reports.get(identifier) or {
            "id": identifier,
            "filename": report.name,
            "sha256": identifier.removeprefix("sha256:"),
            "delivered_at": datetime.now(timezone.utc).isoformat(),
            "relations": {},
        }
        entry["filename"] = report.name
        entry["sha256"] = identifier.removeprefix("sha256:")
        entry.setdefault("relations", {})
        relation_note = ""
        if relation:
            kind, reference = relation
            parent_id, parent = _parent_entry(inbox, index, reference)
            if parent_id == identifier:
                return 2, "BLOCKED_LOCAL: report cannot amend or supersede itself"
            if kind == "amends":
                entry["relations"]["amends"] = parent_id
                links = parent.setdefault("relations", {}).setdefault("amended_by", [])
                if identifier not in links:
                    links.append(identifier)
            else:
                entry["relations"]["supersedes"] = parent_id
                previous = parent.setdefault("relations", {}).get("superseded_by")
                if previous not in (None, identifier):
                    return 2, ("BLOCKED_LOCAL: linked report is already superseded by "
                               f"{previous}")
                parent["relations"]["superseded_by"] = identifier
            relation_note = f"; {kind}={parent_id}"
        reports[identifier] = entry
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 2, f"BLOCKED_LOCAL: cannot prepare {REPORT_INDEX}: {exc}"

    if destination.exists():
        if destination.read_bytes() == report.read_bytes():
            already = True
        else:
            return 2, f"BLOCKED_LOCAL: target exists with different content: {destination}"
    else:
        already = False
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

    try:
        _write_index(inbox, index)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 2, (f"DELIVERED local but INDEX_BLOCKED: {destination}; "
                   f"{REPORT_INDEX}: {exc}")

    state = "already present" if already else "new"
    return 0, (f"DELIVERED local ({state}): {destination}; "
               f"report_id={identifier}{relation_note}")


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
    relation = parser.add_mutually_exclusive_group()
    relation.add_argument("--amends",
                          help="local report id or inbox filename amended by this report")
    relation.add_argument("--supersedes",
                          help="local report id or inbox filename replaced by this report")
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
        print("BLOCKED_LOCAL: no declared/private laboratory report inbox")
        return 2
    if route == "local" and (not inbox.is_dir() or not os.access(inbox, os.W_OK)):
        print(f"BLOCKED_LOCAL: declared/private report inbox unavailable: {inbox}")
        return 2
    relation_value = (("amends", args.amends) if args.amends else
                      (("supersedes", args.supersedes) if args.supersedes else None))
    if route == "github" and relation_value:
        print("BLOCKED: addendum/supersedes linkage is local-only; do not infer a public target")
        return 2

    if not args.do_send:
        if route == "local":
            relation_note = (f"; {relation_value[0]}={relation_value[1]}"
                             if relation_value else "")
            print(f"PREPARED local: {inbox / report.name}; "
                  f"report_id={report_id(report)}{relation_note}")
        else:
            print(f"PREPARED github: {GITHUB_ISSUES}/new")
            print("Public delivery requires an anonymised report, --public-safe and --do")
        return 1

    if route == "local":
        code, message = copy_local(report, inbox, relation_value)
    else:
        if not args.public_safe:
            print("BLOCKED: --public-safe is required before public GitHub delivery")
            return 2
        code, message = publish_github(report, text)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
