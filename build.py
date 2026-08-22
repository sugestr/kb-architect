#!/usr/bin/env python3
"""Build a byte-reproducible kb-architect.skill archive."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
SKILL = ROOT / "plugins" / "kb-architect" / "skills" / "kb-architect"
OUT = ROOT / "kb-architect.skill"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
EXCLUDED = {".DS_Store"}


def files() -> list[Path]:
    return sorted(
        p for p in SKILL.rglob("*")
        if p.is_file()
        and p.name not in EXCLUDED
        and "__pycache__" not in p.parts
        and p.suffix != ".pyc"
    )


def main() -> int:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'^  version: "([^"]+)"$', text, re.MULTILINE)
    if not match:
        raise SystemExit("metadata.version not found")
    limit = int(os.environ.get("SKILL_LIMIT", "8192"))
    size = len(text.encode("utf-8"))
    if size > limit:
        raise SystemExit(f"ПОТОЛОК ПРЕВЫШЕН: SKILL.md {size} байт при пределе {limit}")

    tmp = OUT.with_suffix(".skill.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files():
            rel = Path("kb-architect") / path.relative_to(SKILL)
            info = zipfile.ZipInfo(rel.as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            info.create_system = 3
            archive.writestr(info, path.read_bytes())
    tmp.replace(OUT)
    print(f"собрано: {OUT.name}  версия {match.group(1)}  {OUT.stat().st_size} байт")
    return 0


if __name__ == "__main__":
    sys.exit(main())
