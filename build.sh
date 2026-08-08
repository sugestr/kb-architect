#!/usr/bin/env bash
# Собирает kb-architect.skill — для тех, кто ставит скилл файлом, а не плагином.
set -euo pipefail

cd "$(dirname "$0")"

SRC="plugins/kb-architect/skills"
VERSION=$(grep -m1 '^  version:' "$SRC/kb-architect/SKILL.md" | sed 's/.*"\(.*\)".*/\1/')
OUT="kb-architect.skill"

# Потолок обязательной страницы. Стандарт требует потолок входа от чужих баз
# и до 4.10 не имел его у себя: SKILL.md рос монотонно, потому что добавить
# всегда легче, чем вычесть. Он грузится в каждую сессию, где скилл сработал,
# поэтому его размер — прямой налог на все проекты сразу.
LIMIT=${SKILL_LIMIT:-40960}
SIZE=$(wc -c < "$SRC/kb-architect/SKILL.md")
if [ "$SIZE" -gt "$LIMIT" ]; then
  echo "ПОТОЛОК ПРЕВЫШЕН: SKILL.md $SIZE байт при пределе $LIMIT."
  echo "Не сокращай смысл — выноси в справочник: страница платится каждой сессией."
  exit 1
fi

rm -f "$OUT"
(cd "$SRC" && zip -r -q "../../../$OUT" kb-architect -x '*.DS_Store' '*__pycache__*' '*.pyc')

echo "собрано: $OUT  версия $VERSION  $(du -h "$OUT" | cut -f1)"
echo
echo "проверь, что номер версии отличается от предыдущей сборки —"
echo "иначе установленный скилл не отличить от нового (README, «Правило версий»)"
