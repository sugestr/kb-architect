#!/usr/bin/env bash
# Собирает kb-architect.skill — для тех, кто ставит скилл файлом, а не плагином.
set -euo pipefail

cd "$(dirname "$0")"

SRC="plugins/kb-architect/skills"
VERSION=$(grep -m1 '^  version:' "$SRC/kb-architect/SKILL.md" | sed 's/.*"\(.*\)".*/\1/')
OUT="kb-architect.skill"

rm -f "$OUT"
(cd "$SRC" && zip -r -q "../../../$OUT" kb-architect -x '*.DS_Store' '*__pycache__*' '*.pyc')

echo "собрано: $OUT  версия $VERSION  $(du -h "$OUT" | cut -f1)"
echo
echo "проверь, что номер версии отличается от предыдущей сборки —"
echo "иначе установленный скилл не отличить от нового (README, «Правило версий»)"
