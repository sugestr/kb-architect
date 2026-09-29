#!/usr/bin/env python3
"""Route one kb-architect defect/optimization report to its real recipient.

Local owner projects deliver to the declared/private laboratory inbox.  A local
address remains local even when the current runtime cannot write it: that is
``BLOCKED_LOCAL``, never permission to disclose the report on GitHub. Projects
whose declared route is GitHub may publish an anonymised issue. Preview is the
default; --do performs delivery and never calls a prepared report delivered.

The owner's laboratory runs on one machine while sessions also run on a server.
There a declared ``../kb-architect/inbox`` resolved to a plain folder with the
lab's name, the report was printed DELIVERED and nobody read it (five reports,
20-29.09.2026).  A path named ``kb-architect/inbox`` is therefore accepted only
when it is the lab checkout itself; otherwise the report goes to a private issue
of the lab repository (``lab-issue``), which the lab collects into its inbox.
The lab repository is private, so this is not public disclosure; without access
to it the report stays PREPARED/BLOCKED_LOCAL at the source.
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
LAB_REPOSITORY = "sugestr/kb-architect-lab"
LAB_LABEL = "kb-report"
LAB_TITLE = "[kb-report]"
ISSUE_BODY_LIMIT = 60_000
LAB_REMOTE = re.compile(r"[:/]sugestr/kb-architect-lab(?:\.git)?/?$")
# The report's own id is the last «· sha256:…» field, optionally followed by one
# link field; an id quoted in a link or in the heading is not the report's id.
OWN_ID = re.compile(r" · (sha256:[0-9a-f]{16})(?: · (?:amends|supersedes) sha256:[0-9a-f]{16})?$")
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
    return kb_paths.git_record(result.stdout) if result.returncode == 0 else None


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
    candidates = [top.parent / "kb-architect"]

    # A Codex worktree lives under its runtime directory, not beside the
    # owner's canonical projects.  Ask Git for the shared metadata directory
    # and recover the source checkout's sibling lab without scanning the disk.
    common_raw = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common_raw:
        common = Path(common_raw)
        if common.name == ".git":
            candidates.append(common.parent.parent / "kb-architect")

    # Bounded owner-machine convention.  External beta testers without the
    # private laboratory simply do not match its exact private remote.
    candidates.append(Path.home() / "Documents" / "Projects" / "kb-architect")

    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        remote = git(candidate, "remote", "get-url", "origin")
        inbox = candidate / "inbox"
        if remote and LAB_REMOTE.search(remote.strip()) and inbox.is_dir():
            return inbox.resolve()
    return None


def is_lab_checkout_inbox(path: Path) -> bool:
    """The inbox directory of a checkout whose origin is the private lab."""
    top = git(path, "rev-parse", "--show-toplevel") if path.is_dir() else None
    if not top or not (Path(top) / "inbox").is_dir():
        return False
    remote = git(Path(top), "remote", "get-url", "origin") or ""
    # samefile, not a string compare: macOS paths differ in letter case.
    return bool(LAB_REMOTE.search(remote.strip())) and os.path.samefile(path, Path(top) / "inbox")


def names_the_lab(path: Path) -> bool:
    return path.name == "inbox" and path.parent.name == "kb-architect"


def local_target(root: Path) -> Path | None:
    target = declared_inbox(root) or private_lab_inbox(root)
    # Recipient and current write authority are different facts.  Preserve an
    # explicitly declared local address even when this sandbox cannot write it;
    # the caller must receive BLOCKED_LOCAL, never a silent public fallback.
    return target


def lab_access() -> tuple[bool, str]:
    """Whether this actor can open the private lab repository through gh."""
    try:
        result = subprocess.run(
            ["gh", "repo", "view", LAB_REPOSITORY, "--json", "visibility",
             "-q", ".visibility"], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return False, "gh is unavailable"
    except Exception as exc:
        return False, f"gh did not answer: {exc}"
    if result.returncode != 0:
        why = (result.stderr.strip().splitlines() or [f"exit {result.returncode}"])[0]
        return False, why
    if result.stdout.strip().upper() != "PRIVATE":
        return False, f"{LAB_REPOSITORY} is not private: {result.stdout.strip()}"
    return True, "private lab repository reachable"


def lab_title(text: str, report: Path, root: Path, identifier: str,
              relation: tuple[str, str] | None) -> str:
    base = title(text, report).removeprefix("[kb-architect] ")
    tail = f" · {root.name} · {identifier[:23]}"
    if relation:
        tail += f" · {relation[0]} {relation[1][:23]}"
    return f"{LAB_TITLE} {base[:200 - len(tail) - len(LAB_TITLE)]}{tail}"


def publish_lab_issue(report: Path, text: str, root: Path,
                      relation: tuple[str, str] | None) -> tuple[int, str]:
    identifier = report_id(report)
    if len(text) > ISSUE_BODY_LIMIT:
        return 2, (f"BLOCKED_LOCAL: report is {len(text)} characters, above the issue "
                   f"limit {ISSUE_BODY_LIMIT}; split it or deliver from the lab machine")
    if relation and not relation[1].startswith("sha256:"):
        return 2, "BLOCKED_LOCAL: lab-issue linkage needs a report id (sha256:...), not a file name"
    try:
        found = subprocess.run(
            ["gh", "issue", "list", "--repo", LAB_REPOSITORY, "--state", "all",
             "--search", f"{identifier[:23]} in:title", "--json", "url,title"],
            capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return 1, f"PREPARED lab-issue: gh did not answer: {exc}"
    if found.returncode != 0:
        why = (found.stderr.strip().splitlines() or [f"exit {found.returncode}"])[0]
        return 1, f"PREPARED lab-issue: existing issues not checked: {why}"
    try:
        existing = json.loads((found.stdout or "").strip() or "[]")
    except ValueError:
        existing = None
    if not isinstance(existing, list):
        return 1, "PREPARED lab-issue: existing issues not checked: unexpected gh output"

    def own_id(item):
        m = OWN_ID.search(item.get("title", "")) if isinstance(item, dict) else None
        return m.group(1) if m else None
    same = [i for i in existing if own_id(i) == identifier[:23]]
    if same:
        return 0, f"DELIVERED lab-issue (already present): {same[0].get('url')}; report_id={identifier}"
    command = ["gh", "issue", "create", "--repo", LAB_REPOSITORY,
               "--title", lab_title(text, report, root, identifier, relation),
               "--body-file", str(report)]
    try:
        result = subprocess.run(command + ["--label", LAB_LABEL], capture_output=True,
                                text=True, timeout=60)
        if result.returncode != 0 and "label" in (result.stderr or "").lower():
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return 1, f"PREPARED lab-issue: delivery not confirmed: {exc}"
    if result.returncode != 0:
        why = (result.stderr.strip().splitlines() or [f"exit {result.returncode}"])[0]
        return 1, f"PREPARED lab-issue: delivery not confirmed: {why}"
    url = (result.stdout.strip().splitlines() or [""])[0]
    return 0, f"DELIVERED lab-issue: {url}; report_id={identifier}"


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
    parser.add_argument("--target", choices=("auto", "local", "lab-issue", "github"),
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
    lab_reason = None
    if route == "local" and (inbox is None or names_the_lab(inbox)) and not (
            inbox is not None and is_lab_checkout_inbox(inbox)):
        # The owner's lab is not on this machine (a server session, a folder that
        # only carries the lab's name): its private issue queue is the inbox.
        ok, why = lab_access()
        if ok:
            route = "lab-issue"
        else:
            lab_reason = why
    if route == "local" and not inbox:
        print("BLOCKED_LOCAL: no declared/private laboratory report inbox"
              + (f"; private lab issues unavailable: {lab_reason}" if lab_reason else ""))
        return 2
    if route == "local" and names_the_lab(inbox) and not is_lab_checkout_inbox(inbox):
        print(f"BLOCKED_LOCAL: {inbox} carries the lab's name but is not the lab checkout; "
              f"private lab issues unavailable: {lab_reason}")
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
        if route == "lab-issue":
            print(f"PREPARED lab-issue: private issue in {LAB_REPOSITORY}; "
                  f"report_id={report_id(report)}")
            return 1
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
    elif route == "lab-issue":
        ok, why = lab_access()
        if not ok:
            print(f"BLOCKED_LOCAL: private lab issues unavailable: {why}")
            return 2
        code, message = publish_lab_issue(report, text, root, relation_value)
    else:
        if not args.public_safe:
            print("BLOCKED: --public-safe is required before public GitHub delivery")
            return 2
        code, message = publish_github(report, text)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
