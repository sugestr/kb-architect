# Обновление старого проекта без повторной миграции на каждый patch

Этот reference читают только когда `kb_apply.py` вернул `NEEDS_APPLICATION` или
`APPLICATION_UNPROVEN`. Доставка текущего build и обновление старого проекта — разные результаты.

## Один номер скилла и один порог совместимости

- `metadata.version: 6.3.3` — единственная текущая версия скилла;
- `metadata.minimum_project_version: 6.3.0` — нижняя граница совместимого проекта, а не вторая версия скилла;
- `kb_standard_version: 6.3.0` — проект уже прошёл обязательное обновление с более старого уровня;
- более поздний patch устанавливается как свежий скилл, но не заставляет проект повторять ту же миграцию.

Patch-выпуск может обновить tool/docs/поведение и не переоткрывать роли,
owner acceptance или миграцию. Для `6.3.3` обязательный порог проекта — `6.3.0`:
всё ниже обновляется, `6.3.0` и выше повторно не мигрирует.
`kb_apply.py` применяет текущий порог напрямую: проект не воспроизводит историю всех
patch-релизов и не ведёт строку ledger на каждый из них.

## Короткий цикл

1. Сначала выполнить read-only `kb_skills.py <root> --prepare-candidate`: он возвращает
   prefill из legacy/templates, список только смысловых `UNRESOLVED` и bounded
   fresh-context prompt. Уже принятый проект получает `action: none`, поэтому новый
   patch при том же минимальном уровне не открывает миграцию. До первой записи сохранить
   exact pre-change Git commit и файл, где прочитан marker.
   Для tracked-only проекта этот commit уже является rollback; второй checkout не нужен.
   Если ветка продвинулась до финализации, сначала проверить промежуточные commits и
   заменить source на фактический parent candidate: старый предок остаётся session
   snapshot, но уже не является безопасным rollback всей ветки.
2. Применить только дельту нового минимального уровня. Не переделывать то, что уже удовлетворяет
   текущему контракту, и не переснимать действующие доказательства без изменившегося
   смысла, wiring или bytes роли.
3. Запустить только project checks, способные изменить решение. Для роли обычно это
   один `kb_skills.py --execute-project-check`: candidate передаёт `PENDING`, а runner
   до выполнения связывает Git-tracked validator bytes, skill trees и wiring, а затем
   сам записывает наблюдённый `PASS/FAIL`. После исправления validator вернуть check в
   `PENDING` и выполнить ровно один новый запуск; прежний и новый input hashes должны
   различаться. Никогда не записывать успех или exit `0` заранее. Затем один обычный fresh-context вопрос без имени
   роли, который проверяет selection, indexed recall и один stop/conflict.
4. Показать владельцу содержательный diff, реальные `PASS/FAIL/UNKNOWN`, известные
   `OPEN` и rollback. Предметная корректность роли обсуждается столько, сколько нужно;
   служебная финализация не должна занимать основную работу.
5. После post-results acceptance записать одну короткую schema-2 квитанцию, поставить
   marker минимального уровня, сделать точечный commit и — только при отдельной authority — push.

## Короткая квитанция

`KB_RELEASE_APPLICATION.json` schema 2 хранит один текущий переход:

```json
{
  "schema": 2,
  "application": {
    "from_line": "6.1",
    "to_line": "6.3.0",
    "status": "finalized",
    "source": {"commit": "exact-pre-change-commit", "version_source": "CLAUDE.md"},
    "owner": {"accepted_by": "owner", "accepted_at": "ISO-8601"},
    "finalized_at": "ISO-8601",
    "open": []
  }
}
```

Git commit является source и историей старых receipts. Поэтому schema 2 не дублирует
ref + hash, release rows, evidence paths и один owner gate в нескольких файлах. `OPEN`
не блокирует структурную миграцию, если владелец принял безопасный текущий режим.

## Что не входит в обычную миграцию

- full core suite `kb-architect` — release gate самого скилла;
- повторный model-turn Claude/Codex при тех же canonical bytes и неизменном wiring;
- пять искусственных behavior-case, mutation suite и per-case hash receipts;
- предметное исследование, не нужное для изменения структуры;
- новый acceptance только потому, что изменился patch при том же минимальном уровне.

Эти проверки допустимы при найденном риске или специальном аудите. Их отсутствие не
называется доказательством того, чего проект не проверял.

## Authority

Project-local commit, private report delivery и external push/publication остаются
разными действиями. `BLOCKED_LOCAL` не разрешает public fallback.
