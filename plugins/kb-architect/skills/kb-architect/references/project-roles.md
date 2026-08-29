# Проектные роли — специальная дельта

Роль — project-owned Agent Skill о том, **как агент обращается со знаниями**. Для неё
действует общий KB-контракт; второй системы управления нет.

## Граница

| Слой | Содержимое | Канон |
|---|---|---|
| роль | назначение, профессиональный метод, source ladder, evidence threshold, stops и запреты | `skills/<role>/SKILL.md` |
| знание | факты, законы, диагнозы, события, гипотезы, планы, portal recipes | KB проекта |
| tool | воспроизводимое извлечение, сверка или отправка | script/MCP/connector |

Типы знания выбирает проект. Справочник, попавший в роль из-за плохого поиска, выносят
только после починки `KNOWLEDGE_INDEX.json` и recall-test. Роль не подтверждает лицензию.

## Один канон и выбор

```text
PROJECT_ROLES.json                 # posture, triggers, wiring, validators, budgets
KNOWLEDGE_INDEX.json               # project-specific knowledge addresses
skills/<name>/SKILL.md             # professional method
.agents/skills/<name> -> ../../skills/<name>
.claude/skills/<name> -> ../../skills/<name>
```

Claude, Codex, cloud и AWS обнаруживают один Git-канон. Connectors и secrets
принимаются отдельно по средам.

`PROJECT_ROLES.json` владеет project-specific `load_when`; `SKILL.md` — методом.
Проект явно объявляет posture: `required`, `transitioning` или `not-applicable` с
причиной. Непокрытый существенный вывод — stop. Все совпавшие required-роли
загружаются; конфликт сохраняется и эскалируется.

## Как растить и разделять

В роли оставляй только метод. Факты дела, нормативные тексты, контакты, состояние,
переписку и инструментальные инструкции держи в индексированной KB.

Разделяй skill, если различаются triggers, полномочия, source ladder или stops, либо
обычная задача использует лишь одну его часть. Число ролей само по себе не лимит;
лимитируется стоимость реально загружаемого сценария.

Цикл изменения: реальные задачи → read-only опись → минимальный candidate → tests →
quality review → version/exact-path commit → fresh-context acceptance. Готовую
community-роль можно принять, адаптировать или смешать с provenance/licence.
Пропорциональный внешний обзор получает `done`, `deferred` или `not-applicable` с
причиной; полный мировой поиск не обязателен на каждую правку.

`quality_owner` отвечает за метод; `kb-architect` — за gate/receipt/rollback;
владелец — за acceptance и внешнюю authority. `ROLE_QUALITY_REVIEW.json` сам не
доказывает предметную правильность. `review_scope`: `packaging-only`,
`internal-method`, `external-benchmark` или `licensed-review`; перекладка не получает
профессиональный `PASS`.

## Проверяемая готовность

Schema 3 `ROLE_ACCEPTANCE.json` разделяет четыре исхода:

1. `STRUCTURAL_PASS` — tracked canon, portable frontmatter, общий Agent Skills и
   project validators, knowledge wiring, hashes и static costs;
2. `DISCOVERY_PASS` — для Claude и Codex inventory и выбранные `id/path/hash/version`,
   unforced fresh context и `new-session` boundary;
3. `BEHAVIOR_PASS` — synthetic-first `role-selection`, `knowledge-recall`,
   `authority-stop`, `source-conflict`, `context-cost`; private real-data proof без
   authority остаётся `UNKNOWN`;
4. `OWNER_ACCEPTED` — отдельная post-results приёмка владельца.

`DISCOVERY_PASS` обязателен каждому заявленному агенту. Manifest
`acceptance.behavior_scope: shared` и receipt
`BEHAVIOR_PASS.runtime_scope: shared` означают один общий behavior suite. Свободный
`validation.*.scope` не усиливает машинный gate. Наблюдаемое расхождение конкретной
среды переоткрывает acceptance как defect/`UNKNOWN`, а не заводит второй постоянный
набор правил. Schema 2 читается как legacy до project migration.

Schema-3 behavior case получает PASS только с разными tracked+hashed
input/expected/observed и одним structured tracked harness. Явный
`kb_behavior.py <root> --execute` записывает exit/time/case ids/hashes;
`kb_skills.py` project code не запускает, а сверяет receipt. Ручной JSON или
несуществующий harness дают `BEHAVIOR_EVIDENCE_UNEXECUTED`. Это защита от случайного
самоудостоверения, не криптографическая аттестация; discovery/owner gates отдельны.

Ссылка, symlink или список test names доказывают только structure. Метод, trigger,
wiring, quality review, дерево роли или budget change протухляют acceptance. Команды
validator имеют один канон в `PROJECT_ROLES.json`; boot указывает туда и не повторяет
список.

`kb_skills.py` проверяет active roots `~/.codex/skills`, `~/.claude/skills`,
`~/.agents/skills` и дополнительные `--runtime-root`. Одинаковое имя при разных hash
— stop. Retired copy вне active roots не считается проверенной.

## Стоимость

- `accepted_role_entry_bytes` — обязательный вход роли;
- `accepted_static_route_bytes` — entry, существующие supporting-файлы, на которые
  прямо ссылается `SKILL.md`, и объявленные knowledge `route_files`;
- actual receipt — input/cached-input/output/orchestration tokens либо `UNKNOWN`.

Обязателен `all_roles_scenario`; 8 КиБ — review threshold, не максимум, а
`accepted_*` — budget с headroom. Рост даёт `OPTIMIZATION_REQUIRED`; экономия с
потерей recall/stop отклоняется. Checker включает routed files и Markdown-ссылки роли;
schema-2 linked bytes остаются migration delta. Tree hash доказывает integrity, не
автозагрузку tests/evidence.

Вынос знания из толстой роли атомарен: создать knowledge canon → добавить
route/aliases → связать роль → доказать fresh-context recall → удалить копию.
При legacy-миграции для каждой роли запиши один честный исход boundary review:
`method-only`, extraction применён, `deferred` с условием возврата или `declined`.
Поле — `ROLE_QUALITY_REVIEW.role_knowledge_boundary`; `deferred` требует
`return_condition` и safe mode. Semantic classifier это решение не заменяет.

Шаблоны лежат в `assets/templates/`; канонические проверки — `kb_index.py` и
`kb_skills.py`.

## Миграция и редкое заимствование

До приёмки legacy остаётся authoritative; candidate проверяют через
`--registry <project>/PROJECT_ROLES.json`. Это разделение старого канона и candidate,
не дубль checkout: source commit даёт rollback, worktree нужен лишь параллельному writer.
После переключения `.kb-skills.json`
становится navigation tombstone к новому канону.

По умолчанию роль локальна. Для редкого заимствования owner выпускает version, а
потребитель фиксирует repository + exact pin + recovery и принимает snapshot.
Изменения возвращаются owner; knowledge routes остаются локальными. Центральный
репозиторий ролей не нужен без повторяемого спроса.

Проекты мигрируют по одному: source snapshot → candidate → четыре исхода → post-results
решение владельца → marker последним. Полный ledger описан в `references/migration.md`.
Индекс и его recovery pointers должны быть Git-tracked.

Успех измеряется не красотой схемы: агент быстрее выбирает роль, без подсказки находит
существующее знание, меньше грузит лишнего, останавливается на недоказанном и
восстанавливается в новом runtime. Local defects идут в private inbox, внешние beta —
обезличенным GitHub issue.
