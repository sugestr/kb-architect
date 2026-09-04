# Обновление проекта до 6.4.0

Этот reference читают только когда `kb_apply.py` вернул `NEEDS_APPLICATION` или
`APPLICATION_UNPROVEN`. Доставка текущего build и обновление старого проекта — разные результаты.

## Одна текущая версия

- `metadata.version: 6.4.0` — единственная текущая версия скилла;
- `metadata.minimum_project_version: 6.4.0` означает только: проект ниже `6.4.0`
  ещё не принял эту архитектурную дельту;
- `kb_standard_version: 6.4.0` ставится последним, после проверки и решения владельца.

Исторические `contract_line` и промежуточные build-номера не являются параллельными
версиями. Совместимый будущий patch может ставиться везде без повторной миграции;
`kb_apply.py` применяет только текущий минимальный уровень.

## Дельта 6.4.0

1. Определи topology: `focused`, `portfolio` или `hybrid`. Это описание для выбора
   маршрутов, не обязательная метка. Не дроби подробный специализированный проект и
   не удерживай широкий portfolio только по числу байт/ролей; смотри на расхождения
   authority/current/sensitivity/lifecycle/runtime/recovery.
2. У проекта один физический boot/current owner. Current допустим разделом в
   `CLAUDE.md`/`AGENTS.md`, отдельным файлом либо воспроизводимым запросом. Не создавай
   `NOW.md` и не сливай его с правилами только ради стандарта.
3. Удали из действующих project rules утверждение, что `CLAUDE.md` и `NOW.md` обязаны
   быть не больше 8 КиБ каждый. Checker измеряет их и дедуплицированный bootstrap, но
   без явно принятого `project_boot_budget_bytes` размер информационный.
4. Не сокращай уникальные правила по размеру. Реорганизация — только по явной задаче
   владельца или наблюдаемой поломке: чистое дерево и rollback, карта каждого блока и
   нового адреса/trigger, затем fresh-context recall/authority/stop test.
5. Если структура уже работает, миграция может ограничиться исправлением неверной
   нормы и декларацией одного current owner. Никакого обязательного перемещения файлов.

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
2. Применить только дельту 6.4.0 выше. Не переделывать то, что уже удовлетворяет
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
5. После post-results acceptance записать одну короткую schema-3 квитанцию, поставить
   marker минимального уровня, сделать точечный commit и — только при отдельной authority — push.

## Короткая квитанция

`KB_RELEASE_APPLICATION.json` schema 3 хранит один текущий переход и называет обе
стороны обычными версиями проекта. Принятые schema 2 с историческими полями
`from_line`/`to_line` остаются читаемыми и не требуют косметической миграции:

```json
{
  "schema": 3,
  "application": {
    "from_version": "6.3.0",
    "to_version": "6.4.0",
    "status": "finalized",
    "source": {"commit": "exact-pre-change-commit", "version_source": "CLAUDE.md"},
    "owner": {"accepted_by": "owner", "accepted_at": "ISO-8601"},
    "finalized_at": "ISO-8601",
    "open": []
  }
}
```

Git commit является source и историей старых receipts. Поэтому schema 3 не дублирует
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
