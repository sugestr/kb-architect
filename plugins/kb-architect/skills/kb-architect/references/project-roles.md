# Проектные роли — специальная дельта

Роль — project-specific selector метода и маршрутов знаний. Сам метод — project-owned
Agent Skill о том, **как агент обращается со знаниями**. Selector-ы могут делить skill;
всеми управляет общий KB-контракт.

## Граница

| Слой | Содержимое | Канон |
|---|---|---|
| role selector | назначение, trigger и маршруты знаний | `PROJECT_ROLES.json` |
| method skill | общий профессиональный метод, source ladder, evidence threshold, stops и запреты | `skills/<role>/SKILL.md` |
| знание | факты, законы, диагнозы, события, гипотезы, планы, portal recipes | KB проекта |
| tool | воспроизводимое извлечение, сверка или отправка | script/MCP/connector |

Типы знания выбирает проект. Справочник, попавший в роль из-за плохого поиска, выносят
только после починки `KNOWLEDGE_INDEX.json` и recall-test. Роль не подтверждает лицензию.

## Один канон и выбор

`PROJECT_ROLES.json` хранит posture, selector-ы и budgets; `KNOWLEDGE_INDEX.json` —
адреса знаний; `skills/<name>/SKILL.md` — метод. Discovery обоих агентов ведёт к
одному Git-канону; connectors/secrets принимаются отдельно. Posture: `required`,
`transitioning` или `not-applicable` с причиной. Непокрытый существенный вывод —
stop; совпавшие required-selector-ы загружаются все, конфликт сохраняется.

## Как растить и разделять

В роли оставляй только метод. Факты дела, нормативные тексты, контакты, состояние,
переписку и инструментальные инструкции держи в индексированной KB.

Разные triggers требуют разных selector-ов, но не обязательно разных skills.
Разделяй method skill, если расходятся полномочия, source ladder, stops, quality owner
или общий entry заставляет обычную узкую задачу постоянно грузить ненужный метод.
Один skill допустим для selector-ов с общими инвариантами и подтверждённым route-cost.
Лимитируется стоимость сценария, а не число selector-ов.

Цикл: реальные задачи → опись → минимальный candidate → tests → quality review →
version/commit → fresh-context acceptance. Community-метод принимают, адаптируют или
смешивают с provenance/licence; внешний обзор — `done`, `deferred` или
`not-applicable`, а не обязательный повтор на каждую правку.

`quality_owner` отвечает за метод; `kb-architect` — gate/receipt/rollback; владелец —
за acceptance/authority. `packaging-only` review не получает профессиональный `PASS`.

## Проверяемая готовность

Schema 5 `ROLE_ACCEPTANCE.json` разделяет четыре исхода; schema 2/3/4 читаются как
legacy до следующей project migration:

1. `STRUCTURAL_PASS` — tracked canon, portable frontmatter, общий Agent Skills и
   project validators, knowledge wiring, hashes и static costs;
2. `DISCOVERY_PASS` — для Claude и Codex inventory и выбранные `id/path/hash/version`,
   unforced fresh context и `new-session` boundary;
3. `BEHAVIOR_PASS` — synthetic-first `role-selection`, `knowledge-recall`,
   `authority-stop`, `source-conflict`, `context-cost`; private real-data proof без
   authority остаётся `UNKNOWN`;
4. `OWNER_ACCEPTED` — отдельная post-results приёмка владельца.

`DISCOVERY_PASS` обязателен каждому агенту. `behavior_scope: shared` означает один
suite; расхождение среды переоткрывает acceptance как `UNKNOWN`, а не создаёт второй
набор правил.

Schema-5 case получает PASS только с разными tracked+hashed input/expected/observed и
одним tracked harness. `kb_behavior.py <root> --execute` записывает
exit/time/case ids/hashes; `kb_skills.py` код проекта не запускает, а сверяет receipt.
Ручной JSON или отсутствующий harness дают `BEHAVIOR_EVIDENCE_UNEXECUTED`.

Каждый case объявляет harmful и neutral `replace-text` одной hash-bound цели. Runner
проверяет их во временной копии тем же harness/argv. Harmful обязан дать exit `10` и
structured results, где красный только этот case; neutral — exit `0` и все зелёные.
Parser error, timeout, self-mutation, общий red и детектор любого изменения не
подходят: `BEHAVIOR_EVIDENCE_INADEQUATE`. Inspection и остальные gates отдельны.

Schema 5 запрещает host-absolute `harness.argv`: project paths относительны, locator
установленного ядра runner передаёт как `KB_ARCHITECT_SCRIPTS`.

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
- `accepted_control_plane_bytes` — `PROJECT_ROLES.json` и `KNOWLEDGE_INDEX.json`;
- `accepted_end_to_end_bytes` — сумма static route и control plane;
- actual receipt — input/cached-input/output/orchestration tokens либо `UNKNOWN`.

Обязателен `all_roles_scenario`; 8 КиБ — review threshold, `accepted_*` — budget с
headroom. Рост даёт `OPTIMIZATION_REQUIRED`; экономия с потерей recall/stop отклоняется.
Tree hash доказывает integrity, не автозагрузку tests/evidence.

Вынос знания из толстой роли атомарен: создать knowledge canon → добавить
route/aliases → связать роль → доказать fresh-context recall → удалить копию.
При legacy-миграции для каждой роли запиши один честный исход boundary review:
`method-only`, extraction применён, `deferred` с условием возврата или `declined`.
Поле — `ROLE_QUALITY_REVIEW.role_knowledge_boundary`; `deferred` требует
`return_condition` и safe mode. Semantic classifier это решение не заменяет.

Шаблоны лежат в `assets/templates/`; канонические проверки — `kb_index.py` и
`kb_skills.py`.

## Миграция и редкое заимствование

До приёмки legacy authoritative; candidate проверяют через `--registry`; source commit даёт rollback.
После переключения `.kb-skills.json` становится navigation tombstone.

Заимствование редкое: owner выпускает version, потребитель фиксирует repository + exact
pin + recovery, а изменения возвращает owner; knowledge routes остаются локальными.

Проекты мигрируют по одному: source snapshot → candidate → четыре исхода → post-results
решение владельца → marker последним. Полный ledger описан в `references/migration.md`.
Индекс и его recovery pointers должны быть Git-tracked.

Успех измеряется не красотой схемы: агент быстрее выбирает роль, без подсказки находит
существующее знание, меньше грузит лишнего, останавливается на недоказанном и
восстанавливается в новом runtime. Local defects идут в private inbox, внешние beta —
обезличенным GitHub issue.
