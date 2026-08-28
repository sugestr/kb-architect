#!/usr/bin/env python3
"""Validate and resolve a project's visible knowledge-route index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


DEFAULT_INDEX = "KNOWLEDGE_INDEX.json"


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


def validate(root: Path, path: Path) -> tuple[dict[str, dict], list[str], list[str]]:
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
        missing = [key for key in ("description", "load_when", "aliases", "paths")
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
        if not isinstance(raw["paths"], list) or not all(
                isinstance(item, str) and item for item in raw["paths"]):
            errors.append(f"{route_id}: paths must be a non-empty string array")
            continue
        for relative in raw["paths"]:
            declared = root / relative
            candidate = declared.resolve(strict=False)
            try:
                candidate.relative_to(root)
            except ValueError:
                errors.append(f"{route_id}: path leaves project root: {relative}")
                continue
            if not candidate.exists():
                errors.append(f"{route_id}: path is missing: {relative}")
            elif not candidate.is_file():
                errors.append(f"{route_id}: path must resolve to a file: {relative}")
            elif not tracked_file(root, declared):
                errors.append(f"{route_id}: path is not Git-tracked and recoverable: {relative}")
            elif declared.is_symlink() and not tracked_file(root, candidate):
                errors.append(f"{route_id}: symlink target is not Git-tracked and recoverable: {relative}")
        routes[route_id] = raw
        notes.append(f"{route_id}: {len(raw['paths'])} path(s); {raw['description']}")
    return routes, errors, notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--require", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    path = args.index.resolve() if args.index else root / DEFAULT_INDEX
    routes, errors, notes = validate(root, path)
    for route_id in args.require:
        if route_id not in routes:
            errors.append(f"required knowledge route is unavailable: {route_id}")
    if args.json:
        print(json.dumps({
            "index": str(path),
            "routes": routes,
            "required": args.require,
            "errors": errors,
        }, ensure_ascii=False, indent=2))
    else:
        for note in notes:
            print("OK:", note)
        for route_id in args.require:
            route = routes.get(route_id)
            if route:
                print(f"ROUTE {route_id}: " + ", ".join(route["paths"]))
        print(f"coverage: index={path} routes={len(routes)} errors={len(errors)}")
        for error in errors:
            print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
