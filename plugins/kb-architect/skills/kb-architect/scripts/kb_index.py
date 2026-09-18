#!/usr/bin/env python3
"""Validate and resolve a project's visible knowledge-route index."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_paths  # noqa: E402


DEFAULT_INDEX = "KNOWLEDGE_INDEX.json"


def current_alias_errors(root: Path) -> list[str]:
    """Check visible project paths only at the explicit NOW migration gate."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True, text=True)
    if listed.returncode:
        return ["cannot inspect current aliases: Git-visible paths unavailable"]
    errors = []
    for relative in sorted(set(listed.stdout.split("\0")) - {"", "NOW.md"}):
        candidate = root / relative
        if candidate.is_symlink():
            try:
                if candidate.resolve(strict=True) == root / "NOW.md":
                    errors.append(f"legacy current alias remains: {relative}; migrate consumers and remove it")
            except (OSError, RuntimeError):
                pass  # Unrelated broken links do not establish a current alias.
    return errors


def targets(route: dict) -> list[dict]:
    """Legacy file addresses and typed targets share one interface."""
    paths = route.get("paths", [])
    typed = route.get("targets", [])
    return ([{"kind": "file", "path": value} for value in paths]
            if isinstance(paths, list) else []) + (typed if isinstance(typed, list) else [])


def local_paths(route: dict) -> list[str]:
    """Static local delivery cost: recipes count; database contents do not."""
    return list(dict.fromkeys(item["path"] for item in targets(route)
                             if isinstance(item, dict) and item.get("kind") != "project"
                             and isinstance(item.get("path"), str)))


def section_span(path: Path, heading: str) -> tuple[int, int]:
    """UTF-8 byte interval: heading plus descendants until a peer/ancestor.

    Ignore fenced code headings, retain exact bytes and reject ambiguity.
    """
    import re
    raw = path.read_bytes()
    offset, headings, fence = 0, [], None
    for line in raw.splitlines(keepends=True):
        text = line.decode("utf-8").strip("\r\n")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", text)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif (token[0] == fence[0] and len(token) >= len(fence)
                  and not text[marker.end():].strip()):
                fence = None
        elif fence is None:
            match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", text)
            if match:
                title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
                headings.append((offset, len(match.group(1)), title))
        offset += len(line)
    matches = [i for i, value in enumerate(headings) if value[2] == heading]
    if len(matches) != 1:
        raise ValueError(f"section must resolve uniquely: {path.name} -> {heading}")
    i = matches[0]
    start, level, _ = headings[i]
    end = next((pos for pos, depth, _ in headings[i + 1:] if depth <= level), len(raw))
    return start, end


def read_set_bytes(units: list[tuple[Path, int, int]]) -> int:
    """Union byte intervals by resolved physical path, across all categories."""
    grouped = {}
    for path, start, end in units:
        grouped.setdefault(path.resolve(), []).append((start, end))
    total = 0
    for spans in grouped.values():
        stop = 0
        for start, end in sorted(spans):
            total += max(0, end - max(start, stop))
            stop = max(stop, end)
    return total


def local_read_set(root: Path, routes: list[dict], paths: list[Path],
                   extra_paths: tuple[Path, ...] = ()) -> list[tuple[Path, int, int]]:
    """Indexed sections retain their address; extra route_files mean whole files."""
    selected = {}
    for route in routes:
        for item in targets(route):
            if not isinstance(item, dict) or item.get("kind") == "project":
                continue
            path = (root / item["path"]).resolve()
            span = section_span(path, item["section"]) if item.get("kind") == "section" \
                else (0, path.stat().st_size)
            selected.setdefault(path, []).append(span)
    return ([(path, start, end) for path in paths
             for start, end in selected.get(path, [(0, path.stat().st_size)])]
            + [(path, 0, path.stat().st_size) for path in extra_paths])


def target_errors(root: Path, item: object) -> list[str]:
    if not isinstance(item, dict):
        return ["target must be an object"]
    kind, relative = item.get("kind"), item.get("path")
    if kind not in ("file", "section", "query", "project"):
        return ["target kind must be file, section, query or project"]
    if not isinstance(relative, str) or not relative.strip():
        return ["target path must be a non-empty string"]
    declared = root / relative
    candidate = declared.resolve(strict=False)
    inside = candidate.is_relative_to(root)
    errors = []
    if kind == "project":
        if item.get("relation") not in ("contains", "references", "depends-on"):
            errors.append("project target requires relation contains/references/depends-on")
        if item.get("access") != "read-only" or not item.get("scope"):
            errors.append("project target requires explicit read-only access and scope")
        if not isinstance(item.get("route"), str) or not item["route"]:
            errors.append("project target requires a destination route id")
        # Reachability is checked when this route is resolved. A missing unrelated
        # project must not block local work or be silently treated as empty.
        return errors
    if not inside:
        return [f"path leaves project root: {relative}; use an explicit project target"]
    if not candidate.exists():
        return [f"path is missing: {relative}"]
    if not candidate.is_file():
        return [f"path must resolve to a file: {relative}"]
    if not tracked_file(root, declared):
        errors.append(f"path is not Git-tracked and recoverable: {relative}")
    elif declared.is_symlink() and not tracked_file(root, candidate):
        errors.append(f"symlink target is not Git-tracked and recoverable: {relative}")
    if kind == "section":
        section = item.get("section")
        if not isinstance(section, str) or not section:
            errors.append("section target requires its exact heading")
        else:
            try:
                section_span(candidate, section)
            except (ValueError, UnicodeError) as exc:
                errors.append(str(exc))
    if kind == "query":
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            errors.append("query requires command as a non-empty argv array")
        if item.get("read_only") is not True:
            errors.append("query must declare read_only=true; resolver never executes it")
        for key in ("coverage", "provenance"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append(f"query requires {key}")
    return errors


def tracked_file(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", relative],
        capture_output=True, text=True)
    return result.returncode == 0


def load_index(path: Path) -> tuple[dict | None, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"knowledge index unreadable: {exc}"]
    if not isinstance(data, dict) or data.get("schema") != 1:
        return None, ["knowledge index requires schema 1"]
    if not isinstance(data.get("routes"), list):
        return None, ["knowledge index requires a routes array"]
    return data, []


def validate(root: Path, path: Path, only=None) -> tuple[dict[str, dict], list[str], list[str]]:
    root = root.resolve()
    data, errors = load_index(path)
    notes: list[str] = []
    routes: dict[str, dict] = {}
    if data is None:
        return routes, errors, notes
    if not tracked_file(root, path):
        errors.append("knowledge index is not Git-tracked and recoverable")
    for raw in data["routes"]:
        if not isinstance(raw, dict):
            errors.append("knowledge route is not an object")
            continue
        route_id = raw.get("id")
        if not isinstance(route_id, str) or not route_id:
            errors.append("knowledge route has no id")
            continue
        if route_id in routes:
            errors.append(f"duplicate knowledge route: {route_id}")
            continue
        if only is not None and route_id not in only:
            continue
        missing = [key for key in ("description", "load_when", "aliases")
                   if not raw.get(key)]
        if missing:
            errors.append(f"{route_id}: missing {', '.join(missing)}")
            continue
        if not isinstance(raw["load_when"], list) or not all(
                isinstance(item, str) and item for item in raw["load_when"]):
            errors.append(f"{route_id}: load_when must be a non-empty string array")
        if not isinstance(raw["aliases"], list) or not all(
                isinstance(item, str) and item for item in raw["aliases"]):
            errors.append(f"{route_id}: aliases must be a non-empty string array")
        if "paths" in raw and (not isinstance(raw["paths"], list) or not all(
                isinstance(item, str) and item for item in raw["paths"])):
            errors.append(f"{route_id}: paths must be a string array")
        if "targets" in raw and not isinstance(raw["targets"], list):
            errors.append(f"{route_id}: targets must be an array")
        if not targets(raw):
            errors.append(f"{route_id}: requires paths or targets")
        for item in targets(raw):
            try:
                errors.extend(f"{route_id}: {error}" for error in target_errors(root, item))
            except (OSError, UnicodeError) as exc:
                errors.append(f"{route_id}: unreadable target: {exc}")
        routes[route_id] = raw
        notes.append(f"{route_id}: {len(targets(raw))} target(s); {raw['description']}")
    if only is None and "current" in data and (not isinstance(data["current"], str) or data["current"] not in routes):
        errors.append("current must name an existing route")
    return routes, errors, notes


def resolve(root: Path, path: Path, route_id: str, chain=()) -> tuple[list[dict], list[str]]:
    """Resolve only requested addresses. No command, scan, or write authority."""
    key = (str(path.resolve()), route_id)
    if key in chain:
        return [], [f"route cycle: {path} -> {route_id}"]
    if len(chain) >= 32:
        return [], ["route depth exceeds 32; coverage UNKNOWN"]
    root = root.resolve()
    routes, errors, _ = validate(root, path, only={route_id})
    if errors:
        return [], errors
    route = routes.get(route_id)
    if route is None:
        return [], [f"required knowledge route is unavailable: {route_id}"]
    endpoints = []
    for item in targets(route):
        destination = (root / item["path"]).resolve()
        if item["kind"] == "project":
            nested, failed = resolve(destination.parent, destination, item["route"], chain + (key,))
            for target in nested:
                target.setdefault("via", []).insert(0, {
                    "index": str(path), "route": route_id,
                    "relation": item["relation"], "access": item["access"], "scope": item["scope"],
                })
            endpoints.extend(nested)
            errors.extend(f"{route_id}: {failure}" for failure in failed)
        else:
            endpoints.append({**item, "path": str(destination), "index": str(path),
                              "route": route_id, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                              "execution": "NOT_RUN" if item["kind"] == "query" else "NOT_READ"})
    return endpoints, errors



# Knowledge without a road from the index.
#
# UAD report of 14.09.2026: 112 of 165 knowledge files had no route, so agents that
# navigate by the index answered "will verify the source" while the fact sat in the
# canon for four days. Route→target validation above cannot see this: it walks from
# routes to files, never from files back to routes. The finding is reachability, not
# membership in `paths`: the contract lets knowledge be discoverable through a table
# of contents, so a file linked from a routed entry file is reachable.
KNOWLEDGE_ROOT_KEYS = ("корень знания", "knowledge root", "knowledge_root")
UNREACHABLE_ALLOWED_KEYS = ("допустимо без дороги", "unreachable allowed",
                            "knowledge_unreachable_allowed")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s#]+?\.md)(?:#[^)]*)?\)|`([^`\s]+?\.md)`")
FENCED = re.compile(r"```.*?```", re.DOTALL)


def knowledge_roots(root: Path) -> tuple[list[str], str]:
    """Declared knowledge directories, or `knowledge/` by default; none → not checked."""
    raw, _ = kb_paths.declared_value(str(root), KNOWLEDGE_ROOT_KEYS)
    if raw:
        parts = [p.strip().strip("`\"'«»").strip("/") for p in re.split(r"[,;]", raw)]
        roots = [p for p in parts if p and not p.startswith("<")]
        if roots:
            return roots, "declared"
    if (root / "knowledge").is_dir():
        return ["knowledge"], "default"
    return [], "not-declared"


def tracked_markdown(root: Path, roots: list[str]) -> list[str] | None:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", *roots],
                            capture_output=True)
    if result.returncode != 0:
        return None
    return sorted(p for p in result.stdout.decode("utf-8", "replace").split("\0")
                  if p.endswith(".md"))


def local_links(root: Path, rel: str) -> list[str]:
    """Markdown links and backticked .md paths that resolve to a file inside root."""
    try:
        text = FENCED.sub("", (root / rel).read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return []
    found = []
    for a, b in MD_LINK.findall(text):
        target = (a or b).split("?")[0]
        for candidate in ((root / rel).parent / target, root / target.lstrip("/")):
            try:
                resolved = candidate.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if (root / resolved).is_file():
                found.append(resolved)
                break
    return found


def coverage(root: Path, index_path: Path) -> dict:
    """Which tracked knowledge files no route or link chain from boot/index reaches."""
    root = root.resolve()
    data, errors = load_index(index_path)
    if data is None:
        return {"status": "NOT_CHECKED", "reason": errors[0]}
    roots, source = knowledge_roots(root)
    if not roots:
        return {"status": "NOT_CHECKED", "roots": [], "source": source,
                "reason": "knowledge root not declared and knowledge/ is absent",
                "how": "declare «корень знания: <dir>[, <dir>]» in the project rules"}
    files = tracked_markdown(root, roots)
    if files is None:
        return {"status": "NOT_CHECKED", "roots": roots, "source": source,
                "reason": "git ls-files failed; only Git-tracked knowledge is measured"}
    routed = set()
    for route in data["routes"]:
        if isinstance(route, dict):
            routed.update(local_paths(route))
    seeds = set(routed)
    seeds.update(os.path.relpath(p, root) for p in kb_paths.rules_files(str(root)))
    entry = kb_paths.locate(str(root), "entry")
    if entry.path:
        seeds.add(os.path.relpath(entry.path, root))
    registry = root / "PROJECT_ROLES.json"
    if registry.is_file():
        try:
            for skill in json.loads(registry.read_text(encoding="utf-8")).get("skills", []):
                canonical = skill.get("canonical") if isinstance(skill, dict) else None
                if isinstance(canonical, str) and (root / canonical / "SKILL.md").is_file():
                    seeds.add(f"{canonical.strip('/')}/SKILL.md")
        except (OSError, ValueError):
            pass
    seen, stack = set(), sorted(seeds)
    while stack:
        rel = stack.pop()
        if rel in seen:
            continue
        seen.add(rel)
        stack.extend(local_links(root, rel))
    unreachable = [f for f in files if f not in seen]
    raw_allowed, _ = kb_paths.declared_value(str(root), UNREACHABLE_ALLOWED_KEYS)
    allowed = int(raw_allowed) if raw_allowed and re.fullmatch(r"[0-9]+", raw_allowed) else 0
    by_area = Counter("/".join(f.split("/")[:2]) if f.count("/") > 1 else f.split("/")[0]
                      for f in unreachable)
    return {
        "status": "FINDING" if len(unreachable) > allowed else "PASS",
        "roots": roots, "source": source, "files": len(files),
        "routed": sum(1 for f in files if f in routed),
        "reachable": len(files) - len(unreachable),
        "unreachable": unreachable, "allowed": allowed,
        "by_area": dict(by_area.most_common()),
        "note": "reachable = route paths/targets, boot files and role SKILL.md plus local "
                "Markdown links from them; reachability is not proof that the file is read",
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--require", action="append", default=[])
    parser.add_argument("--current", action="store_true", help="resolve the declared current route")
    parser.add_argument("--require-now", action="store_true",
                        help="check physical root NOW.md, one current route and no aliases; implies --current")
    parser.add_argument("--coverage", action="store_true",
                        help="knowledge files that no route or link chain from boot/index reaches")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    path = args.index.resolve() if args.index else root / DEFAULT_INDEX
    if args.coverage:
        report = coverage(root, path)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif report["status"] == "NOT_CHECKED":
            print(f"coverage: NOT_CHECKED — {report['reason']}")
            if report.get("how"):
                print(f"  {report['how']}")
        else:
            print(f"coverage: {report['status']} — roots={','.join(report['roots'])} "
                  f"({report['source']}) files={report['files']} routed={report['routed']} "
                  f"reachable={report['reachable']} unreachable={len(report['unreachable'])} "
                  f"allowed={report['allowed']}")
            for area, count in report["by_area"].items():
                print(f"  {area}: {count}")
            for rel in report["unreachable"][:40]:
                print(f"  - {rel}")
            if len(report["unreachable"]) > 40:
                print(f"  … and {len(report['unreachable']) - 40} more")
        return 1 if report["status"] == "FINDING" else 0
    current_errors = []
    args.current = args.current or args.require_now
    current = None
    if args.current:
        data, _ = load_index(path)
        current = data.get("current") if data else None
        if isinstance(current, str) and current:
            args.require.append(current)
        else:
            current_errors.append("current route is not declared; coverage UNKNOWN (do not guess NOW.md)")
    routes, errors, notes = validate(root, path, only=set(args.require) if args.require else None)
    errors.extend(current_errors)
    if args.require_now:
        route = routes.get(current, {})
        if targets(route) != [{"kind": "file", "path": "NOW.md"}]:
            errors.append("current route must address only root NOW.md; migrate the existing current owner")
        if (root / "NOW.md").is_symlink():
            errors.append("root NOW.md must be the regular current file, not a symlink")
        errors.extend(current_alias_errors(root))
    resolved = []
    for route_id in args.require:
        if route_id not in routes:
            errors.append(f"required knowledge route is unavailable: {route_id}")
        else:
            found, failures = resolve(root, path, route_id)
            resolved.extend(found)
            errors.extend(failures)
    if args.json:
        print(json.dumps({
            "index": str(path),
            "routes": routes,
            "required": args.require,
            "resolved": resolved,
            "validation_scope": args.require or "all local declarations; external targets not opened",
            "errors": errors,
        }, ensure_ascii=False, indent=2))
    else:
        for note in notes:
            print("OK:", note)
        for route_id in args.require:
            route = routes.get(route_id)
            if route:
                print(f"ROUTE {route_id}: " + ", ".join(str(item.get("path", "UNKNOWN"))
                      for item in targets(route) if isinstance(item, dict)))
        for item in resolved:
            print(f"TARGET {item['kind']}: {item['path']} {item.get('section', '')} ({item['execution']})")
        print(f"coverage: index={path} routes={len(routes)} errors={len(errors)}")
        for error in errors:
            print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
