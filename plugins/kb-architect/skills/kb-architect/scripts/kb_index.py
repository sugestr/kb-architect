#!/usr/bin/env python3
"""Validate and resolve a project's visible knowledge-route index."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


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
            headings = [line.lstrip("#").strip() for line in candidate.read_text(encoding="utf-8").splitlines()
                        if line.startswith("#")]
            if headings.count(section) != 1:
                errors.append(f"section must resolve uniquely: {relative} -> {section}")
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--require", action="append", default=[])
    parser.add_argument("--current", action="store_true", help="resolve the declared current route")
    parser.add_argument("--require-now", action="store_true",
                        help="check physical root NOW.md, one current route and no aliases; implies --current")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    path = args.index.resolve() if args.index else root / DEFAULT_INDEX
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
