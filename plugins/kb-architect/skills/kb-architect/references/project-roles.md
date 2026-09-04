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
Лимит — стоимость сценария, не число selector-ов.

Цикл: реальные задачи → опись → минимальный candidate → tests → quality review →
version/commit → fresh-context acceptance. Community-метод принимают, адаптируют или
смешивают с provenance/licence; внешний обзор — `done`, `deferred` или
`not-applicable`, а не обязательный повтор на каждую правку.

`quality_owner` отвечает за метод; `kb-architect` — gate/receipt/rollback; владелец —
за acceptance/authority. `packaging-only` review не получает профессиональный `PASS`.

## Проверяемая готовность без отдельной бюрократии

`kb_skills.py <root> --prepare-candidate` read-only: legacy/Git-tracked skills,
`UNRESOLVED` scaffold и `mechanical_preflight`; профессия/selector/posture не
назначаются. Принятый: `action: none`. Version — только явный token, иначе `UNKNOWN`.

Новый candidate хранит compact `kb-role-acceptance/v3` в `PROJECT_ROLES.json`.
Отдельный receipt tree и mutation-suite не нужны; accepted schema 2–5, compact v1/v2
и runner v1 остаются legacy-readable без patch-миграции.

Перед `accepted` достаточно четырёх наблюдаемых результатов:

1. `kb_skills.py` видит один Git-канон роли, knowledge routes и бюджет;
2. один узкий project validator проходит;
3. один fresh-context вопрос без имени роли доказывает selection, indexed
   recall и хотя бы один реальный stop/conflict;
4. владелец видит результат и принимает его, сохраняя честные `OPEN`.

Candidate передаёт `PENDING`; один `--execute-project-check` сам пишет `PASS/FAIL` и
связывает command, project-local tracked validator, skill trees и wiring. Validator file
должен быть назван в command; скрытый global code невоспроизводим. После его исправления
верни `PENDING` и сделай один новый run. Owner/live не протухляют binding. Fresh-context
observation ссылается на native task/turn либо tracked evidence.

Compact acceptance отдельно связывает SHA-256 `SKILL.md`; Git commit — остальные bytes
и rollback. Поля runner вручную не заполняют.

Хотя бы один агент получает `TESTED`. Другой — `INHERITED` при тех же bytes/wiring и
доказанной способности runtime либо честный `UNKNOWN`. Новый model-turn нужен при
изменении видимого входа или расхождении, а не в каждом проекте.

`kb_behavior.py`, mutation controls и повтор по runtimes — только risk-driven audit.
Core suite выполняется при выпуске `kb-architect`, не в проекте.

Одноимённая active copy с другими bytes блокирует приёмку; retired copy вне active
roots — нет.

## Стоимость

- `accepted_end_to_end_bytes` — один бюджет полного обычного маршрута: role entry,
  прямо связанные supporting-файлы, knowledge routes и control plane;
- actual receipt — input/cached-input/output/orchestration tokens либо `UNKNOWN`.

Обязателен `all_roles_scenario`; 8 КиБ — review threshold, единый end-to-end budget
получает headroom. Рост даёт `OPTIMIZATION_REQUIRED`; экономия с потерей recall/stop
отклоняется. Детальная разбивка печатается диагностически, но проект не переписывает
четыре числа после каждой нормальной правки.

Вынос знания из толстой роли атомарен: создать knowledge canon → добавить
route/aliases → связать роль → доказать fresh-context recall → удалить копию.
Для каждой роли компактный `quality` в manifest называет владельца метода, состояние
профессионального review, `knowledge_boundary` и причину. `deferred` требует условие
возврата. Отдельный quality-файл нужен только если предметной команде действительно
нужен подробный документ, а не для удовлетворения ядра.

Шаблоны лежат в `assets/templates/`; канонические проверки — `kb_index.py` и
`kb_skills.py`.

## Миграция и редкое заимствование

До приёмки legacy authoritative; candidate проверяют через `--registry`; source commit даёт rollback.
После переключения `.kb-skills.json` становится navigation tombstone.

Заимствование редкое: owner выпускает version, потребитель фиксирует repository + exact
pin + recovery, а изменения возвращает owner; knowledge routes остаются локальными.

Проекты мигрируют по одному: source commit → candidate → один project check через
явный execution flag + один
живой вопрос → решение владельца → marker последним. Применение patch-сборки выше
уже принятого минимального уровня не является новой миграцией. Короткая запись описана в
`references/migration.md`.
Индекс и recovery pointers должны быть tracked.

Успех измеряется не красотой схемы: агент быстрее выбирает роль, без подсказки находит
существующее знание, меньше грузит лишнего, останавливается на недоказанном и
восстанавливается в новом runtime. Local defects идут в private inbox, внешние beta —
обезличенным GitHub issue.
