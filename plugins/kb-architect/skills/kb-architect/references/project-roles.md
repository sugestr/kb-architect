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

`quality_owner` отвечает за профессиональный метод и domain regressions;
`kb-architect` — за gate/receipt/rollback; владелец проекта — за acceptance и внешнюю
authority. `ROLE_QUALITY_REVIEW.json` не хранит факты и не доказывает предметную
правильность сам по себе.

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

Codex local/cloud/AWS используют одну Codex discovery-точку роли. Checkout, provider,
identity, scope и capabilities проверяет существующий runtime registry.

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

Фактические tokens не являются статическим hard limit. Обязателен
`all_roles_scenario`; 8 КиБ — review threshold, не максимум. `accepted_*_bytes` —
обоснованные потолки с headroom, а не exact snapshots. Append-only знание не должно
краснеть после каждой строки; его либо покрывает budget, либо оно не входит в обычный
autoload route. Рост сверх бюджета даёт `OPTIMIZATION_REQUIRED`; экономия с потерей
recall/stop отклоняется.

Checker считает inline/reference Markdown-ссылки из `SKILL.md`, включая
`<path with spaces>`; inline-code игнорируется. В принятой schema 2 linked bytes —
migration delta; budget включается после schema 3. Tree hash
проверяет integrity, но не означает автозагрузку тестов/evidence.

Вынос знания из толстой роли атомарен: создать knowledge canon → добавить
route/aliases → связать роль → доказать fresh-context recall → удалить копию.

Шаблоны лежат в `assets/templates/`. Канонические проверки:

```bash
python3 <kb-architect>/scripts/kb_index.py <project>
python3 <kb-architect>/scripts/kb_skills.py <project>
```

## Миграция и редкое заимствование

До приёмки shadow legacy остаётся authoritative; candidate проверяют через
`--registry <project>/PROJECT_ROLES.json`. После переключения `.kb-skills.json`
становится navigation tombstone к новому канону.

По умолчанию роль локальна. Для редкого заимствования owner выпускает version, а
потребитель фиксирует repository + exact pin + recovery и принимает snapshot.
Изменения возвращаются owner; knowledge routes остаются локальными. Центральный
репозиторий ролей не нужен без повторяемого спроса.

Проекты мигрируют по одному: source snapshot → shadow → четыре исхода → post-results
решение владельца → marker последним. Полный ledger описан в `references/migration.md`.
Индекс и его recovery pointers должны быть Git-tracked.

Успех измеряется не красотой схемы: агент быстрее выбирает роль, без подсказки находит
существующее знание, меньше грузит лишнего, останавливается на недоказанном и
восстанавливается в новом runtime. Local defects идут в private inbox, внешние beta —
обезличенным GitHub issue.
