#!/usr/bin/env python3
"""Audit project portability and environment-specific capabilities.

The optional registry is ``<project>/.kb-environments.json``.  It records logical
capabilities, not credentials.  The checker is deliberately offline and stdlib-only:
it validates declarations and Git portability, but never opens mail, starts an MCP,
or treats a provider name as acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


RUNTIMES = {"codex-local", "claude-local", "codex-cloud"}
STATUSES = {"accepted", "pending", "unavailable", "not-applicable"}
CLOUD_LOCAL_KINDS = {"local-mcp", "local-filesystem", "macos-keychain"}
# Split the macOS home prefix so the public leakage scanner does not mistake this
# generic detector for a copied personal path.
ABSOLUTE = re.compile(r"(?:/" + r"Users/|/home/|[A-Za-z]:\\\\|~/)")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def tracked(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return False
    return git(root, "ls-files", "--error-unmatch", rel).returncode == 0


def entry_portability(root: Path, runtimes: list[str], errors: list[str]) -> None:
    required = ["AGENTS.md"]
    if "claude-local" in runtimes:
        required.append("CLAUDE.md")
    seen: set[Path] = set()
    for name in required:
        path = root / name
        if not path.exists():
            errors.append(f"{name}: required project entry is missing")
            continue
        if not tracked(root, path):
            errors.append(f"{name}: project entry is not Git-tracked")
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"{name}: entry resolves outside the repository")
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{name}: entry is unreadable: {exc}")
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if ABSOLUTE.search(line) and not line.lstrip().startswith("# historical"):
                errors.append(
                    f"{name}:{lineno}: active instruction contains a host-specific path"
                )


def accepted_provider(entry: object, runtime: str, capability: str,
                      errors: list[str]) -> bool:
    if not isinstance(entry, dict):
        errors.append(f"{capability}: {runtime} provider is not an object")
        return False
    status = entry.get("status")
    if status not in STATUSES:
        errors.append(f"{capability}: {runtime} has invalid status {status!r}")
        return False
    if status != "accepted":
        return False
    required = ("kind", "provider", "identity", "scope", "authority",
                "validation", "accepted_at")
    missing = [field for field in required if not entry.get(field)]
    if missing:
        errors.append(
            f"{capability}: accepted {runtime} provider missing {', '.join(missing)}"
        )
        return False
    if runtime == "codex-cloud" and entry.get("kind") in CLOUD_LOCAL_KINDS:
        errors.append(
            f"{capability}: codex-cloud cannot accept host-only kind {entry.get('kind')}"
        )
        return False
    if entry.get("kind") == "local-mcp" and not entry.get("source"):
        errors.append(f"{capability}: accepted local MCP has no inventory source")
        return False
    return True


def validate(root: Path, registry: Path, runtime: str,
             requested: list[str]) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    notes: list[str] = []
    if git(root, "rev-parse", "--show-toplevel").returncode:
        return ["project is not a Git checkout"], notes, 0
    remote = git(root, "remote", "get-url", "origin")
    if remote.returncode or not remote.stdout.strip():
        errors.append("origin remote is missing")
    if not registry.exists():
        errors.append("cloud/runtime capability audit not declared: .kb-environments.json missing")
        return errors, notes, 0
    if not tracked(root, registry):
        errors.append(".kb-environments.json is not Git-tracked")
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"registry unreadable: {exc}"], notes, 0
    if data.get("schema") != 1 or not isinstance(data.get("capabilities"), list):
        return ["registry requires schema 1 and a capabilities array"], notes, 0
    runtimes = data.get("supported_runtimes")
    if not isinstance(runtimes, list) or not runtimes or any(r not in RUNTIMES for r in runtimes):
        errors.append("supported_runtimes contains an unknown or empty runtime")
        runtimes = []
    if runtime not in runtimes:
        errors.append(f"runtime {runtime} is not declared supported")
    policy = data.get("cloud_policy")
    if runtime == "codex-cloud" and policy != "allowed":
        errors.append(f"cloud_policy is {policy!r}, not 'allowed'")
    entry_portability(root, runtimes, errors)

    by_id: dict[str, dict] = {}
    for item in data["capabilities"]:
        if not isinstance(item, dict):
            errors.append("capability entry is not an object")
            continue
        capability = item.get("id")
        if not isinstance(capability, str) or not capability:
            errors.append("capability entry has no id")
            continue
        if capability in by_id:
            errors.append(f"{capability}: duplicate capability id")
            continue
        by_id[capability] = item
        required_fields = ("purpose", "required_when", "sensitivity",
                           "failure_policy", "prohibited_actions", "providers")
        missing = [field for field in required_fields if not item.get(field)]
        if missing:
            errors.append(f"{capability}: missing {', '.join(missing)}")
            continue
        if item.get("failure_policy") not in ("fail-closed", "fail-open"):
            errors.append(f"{capability}: invalid failure_policy")
        providers = item.get("providers")
        if not isinstance(providers, dict):
            errors.append(f"{capability}: providers is not an object")
            continue
        for declared_runtime, provider in providers.items():
            if declared_runtime not in RUNTIMES:
                errors.append(f"{capability}: unknown runtime {declared_runtime}")
                continue
            accepted_provider(provider, declared_runtime, capability, errors)

    required = set(requested)
    required.update(
        capability for capability, item in by_id.items()
        if item.get("required_by_default") is True
    )
    for capability in sorted(required):
        item = by_id.get(capability)
        if item is None:
            errors.append(f"required capability is undeclared: {capability}")
            continue
        provider = item.get("providers", {}).get(runtime)
        before = len(errors)
        ok = accepted_provider(provider, runtime, capability, errors)
        if not ok and len(errors) == before:
            status = provider.get("status") if isinstance(provider, dict) else "missing"
            errors.append(f"{capability}: {runtime} is required but status is {status}")
        if ok:
            notes.append(f"{capability}: accepted in {runtime}")
    optional_missing = []
    for capability, item in by_id.items():
        if capability in required:
            continue
        provider = item.get("providers", {}).get(runtime)
        if not isinstance(provider, dict) or provider.get("status") != "accepted":
            optional_missing.append(capability)
    if optional_missing:
        notes.append("optional capabilities unavailable here: " + ", ".join(sorted(optional_missing)))
    return errors, notes, len(by_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--runtime", choices=sorted(RUNTIMES), default="codex-cloud")
    parser.add_argument("--require", action="append", default=[], dest="requested")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    registry = args.registry.resolve() if args.registry else root / ".kb-environments.json"
    errors, notes, count = validate(root, registry, args.runtime, args.requested)
    for note in notes:
        print("OK:", note)
    print(f"coverage: runtime={args.runtime} declared={count} errors={len(errors)}")
    for error in errors:
        print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
