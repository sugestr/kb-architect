#!/usr/bin/env python3
"""Measure context cost for the entry and routed Markdown layers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
ENTRY_LIMIT = 8192
MODULE_LIMIT = 10
ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
MARKDOWN_PATH = re.compile(r"`((?:references|assets)/[^`]+\.md)`")


def routes(text: str) -> list[dict]:
    result = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| Задача |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            break
        match = ROW.match(line)
        if not match or set(match.group(1).strip()) == {"-"}:
            continue
        task, instruction = match.groups()
        listed = MARKDOWN_PATH.findall(instruction)
        resources = list(dict.fromkeys(listed))
        duplicates = sorted({item for item in listed if listed.count(item) > 1})
        result.append({"task": task.strip(), "resources": resources,
                       "_duplicate_resources": duplicates})
    return result


def measure() -> dict:
    entry = SKILL.read_bytes()
    text = entry.decode("utf-8")
    errors = []
    measured = []
    for route in routes(text):
        duplicates = route.pop("_duplicate_resources")
        if duplicates:
            errors.append(
                f"route repeats resource ({route['task']}): {', '.join(duplicates)}")
        extra = 0
        for relative in route["resources"]:
            path = ROOT / relative
            if not path.is_file():
                errors.append(f"route resource missing: {relative}")
                continue
            extra += len(path.read_bytes())
        total = len(entry) + extra
        measured.append({
            **route,
            "entry_bytes": len(entry),
            "extra_bytes": extra,
            "total_bytes": total,
            "estimated_tokens": round(total / 3.3),
        })
    modules = len(re.findall(
        r"^## `[^`]+`",
        (ROOT / "references/modules.md").read_text(encoding="utf-8"),
        re.MULTILINE,
    ))
    if len(entry) > ENTRY_LIMIT:
        errors.append(f"entry budget exceeded: {len(entry)} > {ENTRY_LIMIT} bytes")
    if modules > MODULE_LIMIT:
        errors.append(f"module budget exceeded: {modules} > {MODULE_LIMIT}")
    if not measured:
        errors.append("route table not found")
    return {
        "entry_bytes": len(entry),
        "entry_limit_bytes": ENTRY_LIMIT,
        "modules": modules,
        "module_limit": MODULE_LIMIT,
        "routes": measured,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = measure()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"entry: {result['entry_bytes']} / {result['entry_limit_bytes']} bytes")
        print(f"modules: {result['modules']} / {result['module_limit']}")
        for route in result["routes"]:
            print(
                f"route: {route['total_bytes']:6d} bytes  "
                f"~{route['estimated_tokens']:5d} tokens  {route['task']}"
            )
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
    return 2 if args.check and result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
