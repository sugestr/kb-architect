#!/usr/bin/env python3
"""Measure routed context and fail closed on an unaccepted cost increase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
BASELINE = ROOT / "assets" / "route-cost-baseline.json"
ENTRY_LIMIT = 8192
ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
MARKDOWN_PATH = re.compile(r"`((?:references|assets)/[^`]+\.md)`")
SECTION_HINT = re.compile(r"→\s*`([^`]+)`")
HELP_COMMAND = re.compile(r"`(scripts/[^`\s]+\.py) --help`")
MODULE_HEADING = re.compile(r"^## `([^`]+)`.*$", re.MULTILINE)


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
        section = SECTION_HINT.search(instruction)
        sections = ({resources[0]: section.group(1)}
                    if section and len(resources) == 1 else {})
        result.append({
            "task": task.strip(),
            "resources": resources,
            "sections": sections,
            "help_commands": HELP_COMMAND.findall(instruction),
            "_duplicate_resources": duplicates,
        })
    return result


def section_bytes(path: Path, name: str) -> int | None:
    text = path.read_text(encoding="utf-8")
    headings = list(MODULE_HEADING.finditer(text))
    for index, heading in enumerate(headings):
        if heading.group(1) != name:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        return len(text[heading.start():end].encode("utf-8"))
    return None


def help_bytes(relative: str) -> tuple[int | None, str | None]:
    path = ROOT / relative
    if not path.is_file():
        return None, f"route command missing: {relative} --help"
    try:
        result = subprocess.run(
            [sys.executable, str(path), "--help"], capture_output=True,
            timeout=30)
    except Exception as exc:
        return None, f"route command failed: {relative} --help: {exc}"
    if result.returncode != 0:
        return None, (f"route command failed: {relative} --help: "
                      f"exit {result.returncode}")
    return len(result.stdout + result.stderr), None


def load_baseline() -> tuple[dict | None, str | None]:
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"cost baseline unavailable: {exc}"
    if not isinstance(data, dict) or data.get("schema") != 1:
        return None, "cost baseline has unsupported schema"
    if not isinstance(data.get("routes"), dict):
        return None, "cost baseline has no routes object"
    return data, None


def compare_baseline(measured: list[dict], baseline: dict) -> list[str]:
    errors = []
    current = {route["task"]: route["total_bytes"] for route in measured}
    previous = baseline.get("routes", {})
    for task, total in current.items():
        accepted = previous.get(task)
        if not isinstance(accepted, int):
            errors.append(
                f"OPTIMIZATION_REQUIRED: new route has no accepted baseline: {task}")
        elif total > accepted:
            errors.append(
                f"OPTIMIZATION_REQUIRED: route grew by {total - accepted} bytes "
                f"({accepted} -> {total}): {task}")
    for task in sorted(set(previous) - set(current)):
        errors.append(f"cost baseline contains removed route: {task}")
    return errors


def measure(check_baseline: bool = True) -> dict:
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
        details = []
        for relative in route["resources"]:
            path = ROOT / relative
            if not path.is_file():
                errors.append(f"route resource missing: {relative}")
                continue
            section = route["sections"].get(relative)
            size = section_bytes(path, section) if section else len(path.read_bytes())
            if size is None:
                errors.append(f"route section missing: {relative} -> {section}")
                continue
            extra += size
            details.append({"path": relative, "section": section, "bytes": size})
        command_details = []
        for relative in route["help_commands"]:
            size, error = help_bytes(relative)
            if error:
                errors.append(error)
                continue
            extra += size or 0
            command_details.append({"command": f"{relative} --help", "bytes": size})
        total = len(entry) + extra
        measured.append({
            **route,
            "resource_details": details,
            "command_details": command_details,
            "entry_bytes": len(entry),
            "extra_bytes": extra,
            "total_bytes": total,
            "estimated_tokens": round(total / 3.3),
        })
    modules = len(MODULE_HEADING.findall(
        (ROOT / "references/modules.md").read_text(encoding="utf-8")))
    if len(entry) > ENTRY_LIMIT:
        errors.append(f"entry budget exceeded: {len(entry)} > {ENTRY_LIMIT} bytes")
    baseline_version = None
    if check_baseline:
        baseline, baseline_error = load_baseline()
        if baseline_error:
            errors.append(baseline_error)
        else:
            baseline_version = baseline.get("version")
            errors.extend(compare_baseline(measured, baseline))
    if not measured:
        errors.append("route table not found")
    return {
        "entry_bytes": len(entry),
        "entry_limit_bytes": ENTRY_LIMIT,
        "modules": modules,
        "module_limit": None,
        "baseline_version": baseline_version,
        "routes": measured,
        "errors": errors,
    }


def baseline_payload(result: dict, version: str) -> dict:
    return {
        "schema": 1,
        "version": version,
        "entry_limit_bytes": ENTRY_LIMIT,
        "routes": {route["task"]: route["total_bytes"]
                   for route in result["routes"]},
    }


def skill_version() -> str:
    match = re.search(r'^\s+version:\s*"([^"]+)"',
                      SKILL.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-baseline", action="store_true",
                        help="accept current route costs for this skill version")
    args = parser.parse_args()
    result = measure(check_baseline=not args.write_baseline)
    if args.write_baseline:
        BASELINE.write_text(
            json.dumps(baseline_payload(result, skill_version()),
                       ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"accepted route-cost baseline: {BASELINE}")
        return 0
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"entry: {result['entry_bytes']} / {result['entry_limit_bytes']} bytes")
        print(f"modules: {result['modules']} (count is a signal, not a token budget)")
        print(f"accepted baseline: {result['baseline_version'] or 'UNKNOWN'}")
        for route in result["routes"]:
            print(
                f"route: {route['total_bytes']:6d} bytes  "
                f"~{route['estimated_tokens']:5d} tokens  {route['task']}")
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        if any("OPTIMIZATION_REQUIRED" in error for error in result["errors"]):
            print("Запрос на оптимизацию: сократи/раздели маршрут либо явно прими "
                  "новую baseline вместе с release rationale.", file=sys.stderr)
    return 2 if args.check and result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
