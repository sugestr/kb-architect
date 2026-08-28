# Проектные роли — только специальная дельта

Роль — элемент знания проекта и наследует обычные правила `kb-architect`: один
канон, provenance, version, проверяемое изменение, стоимость, recovery, конфликт,
commit и fresh-context приёмку. Отдельная система управления ролями не создаётся.

## Граница

Роль — локальный Agent Skill о том, **как агент обращается со знаниями**: назначение,
профессиональный метод, source ladder, evidence threshold, stop/escalation и запреты.
Это не персонаж и не заявление о реальной лицензии модели.

| Слой | Пример | Канон |
|---|---|---|
| роль | как юрист проверяет применимость нормы, практику и доказательства | `skills/<role>/SKILL.md` |
| знание | закон, диагноз, анализ, факт, гипотеза, план, рецепт портала | KB проекта |
| tool | воспроизводимое извлечение, сверка, отправка | script/MCP/connector |

Типы знания проект выбирает сам; универсальная онтология не вводится. Адреса и
triggers живут в `KNOWLEDGE_INDEX.json`. Если справочник положили в роль, потому что
иначе агент его не находит, сначала чинят индекс и recall-test.

## Один канон и выбор роли

```text
PROJECT_ROLES.json                 # posture, project triggers, wiring
KNOWLEDGE_INDEX.json               # project-specific knowledge addresses
skills/<name>/SKILL.md             # method
.agents/skills/<name> -> ../../skills/<name>
.claude/skills/<name> -> ../../skills/<name>
```

Это один Git-канон для локальных/облачных Claude, Codex и AWS, не копии по платформам.
Git, connectors и secrets принимаются по средам; boot хранит адреса manifest и `load
every matching required role`.

`PROJECT_ROLES.json` единолично владеет project-specific `load_when`; `SKILL.md`
владеет методом. Агент не угадывает matching глобально. Непокрытая или двусмысленная
существенная работа останавливается; все совпавшие required-роли загружаются, конфликт
не усредняется.

## Содержание и разделение

В `SKILL.md` оставляй назначение/границу, метод, source ladder, evidence threshold,
stop/escalation, запреты и критерии приёмки. Факты дела, закон, состояние, контакты,
portal recipes и переписка остаются в KB.

Разделяй роли, если различаются trigger, полномочия, source ladder, stops либо обычная
задача требует только одной части. Число ролей не ограничивается само по себе.

## Рост, приёмка и стоимость

Цикл общий: реальные задачи → read-only опись → минимальный candidate → tests → review
→ version/commit. Community-роль принимают/адаптируют/смешивают с provenance/licence;
quality review помечает пропорциональный внешний обзор как выполненный, отложенный или
неприменимый. Полный мировой поиск не запускается на каждую правку.

У каждой роли есть `quality_owner`: предметный исполнитель отвечает за профессиональный
метод и domain regressions; `kb-architect` — за gate, receipt и rollback; владелец — за
приёмку результата и внешнюю authority. Эти полномочия не подменяют друг друга.
`ROLE_QUALITY_REVIEW` проверяет метод, source ladder и regressions, но не хранит факты.

Готовность состоит из четырёх независимых исходов в schema-2
`ROLE_ACCEPTANCE.json`:

1. `STRUCTURAL_PASS` — один tracked canon, portable frontmatter, оба validator,
   knowledge wiring, hashes и static costs;
2. `DISCOVERY_PASS` — для каждого заявленного агента inventory и выбранные
   `id/path/hash/version`, unforced fresh-context test и граница `new-session`;
3. `BEHAVIOR_PASS` — synthetic-first cases `role-selection`, `knowledge-recall`,
   `authority-stop`, `source-conflict`, `context-cost`; без разрешения на private
   real-data destination этот дополнительный proof честно `UNKNOWN`;
4. `OWNER_ACCEPTED` — отдельная post-results приёмка владельца.

Ссылка, symlink или список test names дают только structural evidence. Изменение метода,
trigger, wiring, quality review, дерева роли или baseline протухляет квитанцию.
Каждая роль проходит общий portable Agent Skills validator **и** project validator;
зелёный project test не разрешает неподдерживаемое поле вроде top-level `version`.

`kb_skills.py` проверяет одноимённые копии в перечисленных active roots
`~/.codex/skills`, `~/.claude/skills`, `~/.agents/skills`; дополнительные runtime roots
задаются `--runtime-root`. Отчёт называет проверенный охват. Совпавшие name при разных
hash — stop; выведенная из active roots копия не считается просмотренной.

Стоимость не смешивается: `accepted_role_entry_bytes` — обязательный вход роли;
`accepted_static_route_bytes` — entry плюс реально перечисленные `route_files`;
actual receipt отдельно хранит input/cached-input/output/orchestration tokens либо
`UNKNOWN`. Фактические tokens не становятся статическим hard limit. Помимо обычных
сценариев обязателен `all_roles_scenario`; 8 КиБ — review threshold, не максимум.
Рост без новой baseline даёт `OPTIMIZATION_REQUIRED`; экономия, потерявшая recall или
stop, отвергается.

Вынос знания из толстой роли атомарен: создать канон → добавить route/aliases →
связать роль → доказать fresh-context recall → удалить копию из роли.

Шаблоны: `project-roles.json`, `knowledge-index.json`, `role-quality-review.json`,
`role-acceptance.json` в `assets/templates/`. Проверки:

```bash
python3 <kb-architect>/scripts/kb_index.py <project>
python3 <kb-architect>/scripts/kb_skills.py <project>
```

## Старый адрес и заимствование

До приёмки shadow legacy остаётся authoritative; candidate проверяют явным
`--registry <project>/PROJECT_ROLES.json`. Затем `.kb-skills.json` заменяют
`legacy-role-registry.json`: это navigation tombstone к новому канону. Pre-6.0 checker
должен обновиться на безопасной границе.

По умолчанию роль project-local. При заимствовании owner выпускает version; потребитель
фиксирует repository + exact pin + recovery и принимает snapshot. Checkout стоит на
pin без delta; изменения возвращаются owner, knowledge routes остаются локальными.

## Миграция и критерий успеха

Проекты идут по одному от простых к смешанным. Сначала read-only отчёт: реальные
roles/triggers, знания и tools внутри ролей, пробелы индекса, вопросы владельцу, цена
маршрутов и пять regression cases. Затем shadow и четыре отдельных результата выше;
marker меняется только после прямой post-results приёмки. Release-wide source snapshot,
ledger и порядок finalize описаны один раз в `references/migration.md`.

Сам индекс и каждый его путь должны быть Git-tracked. Для внешнего или большого
источника индексируй tracked pointer с provenance/recovery, а не локальный кэш.

Успех: агент быстрее выбирает роль, находит существующее знание без подсказки, меньше
грузит лишнего, честно останавливается и одинаково восстанавливается. Дефекты идут
штатно: локальные — в private inbox, внешние beta — обезличенным GitHub issue.
