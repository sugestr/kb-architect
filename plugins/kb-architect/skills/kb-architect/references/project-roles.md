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

## Проверяемая готовность без отдельной бюрократии

Новый project candidate хранит короткую приёмку прямо в `PROJECT_ROLES.json` по
протоколу `kb-role-acceptance/v3`. Отдельные `ROLE_ACCEPTANCE.json`, пять behavior-case,
mutation-suite и россыпь input/expected/observed receipts не требуются. Старые schema
2–5 и accepted compact v1/v2 остаются читаемыми: patch их не переписывает.

Перед `accepted` достаточно четырёх наблюдаемых результатов:

1. `kb_skills.py` видит один Git-канон роли, knowledge routes и бюджет;
2. один узкий project validator проходит;
3. один fresh-context вопрос без имени роли доказывает selection, indexed
   recall и хотя бы один реальный stop/conflict;
4. владелец видит результат и принимает его, сохраняя честные `OPEN`.

Staged candidate держит check в `PENDING`. Один `kb_skills.py --execute-project-check`
запускает command и сам пишет `PASS/FAIL`, run id и wiring hash; эти поля вручную не
заполняют, после записи registry снова индексируют. Owner/live не входят в binding и не
повторяют command. Fresh-context observation ссылается на native task/turn либо tracked
evidence: checker проверяет связь, но не изображает model runner.

Приёмка связывает только SHA-256 текущих `SKILL.md`. Owner status живёт в manifest и
не входит в эти hashes, поэтому переход `candidate → accepted` не протухляет
собственный тест. Git commit уже связывает остальные bytes и даёт rollback.

Хотя бы один агент получает `TESTED`. Другой агент может получить `INHERITED`, если
его discovery ведёт к тем же canonical bytes, wiring/config не менялись, а способность
этого runtime уже доказана; либо честный `UNKNOWN` с причиной. Новый model-turn нужен
при изменении wiring, конфигурации, видимого контента или при реальном расхождении, а
не в каждом проекте.

Полный `kb_behavior.py`, mutation controls, per-case attribution и повтор по всем
runtimes — maintainer/deep-audit инструменты. Проект включает их только по найденному
риску, а не ради финализации. Core test suite выполняется при выпуске `kb-architect`;
проект не повторяет его.

`kb_skills.py` по-прежнему проверяет active roots и останавливается при одноимённой
активной копии с другими bytes. Retired copy вне active roots не считается активной.

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
живой вопрос → решение владельца → marker последним. Применение patch-сборки внутри
той же contract line не является новой миграцией. Короткая запись описана в
`references/migration.md`.
Индекс и recovery pointers должны быть tracked.

Успех измеряется не красотой схемы: агент быстрее выбирает роль, без подсказки находит
существующее знание, меньше грузит лишнего, останавливается на недоказанном и
восстанавливается в новом runtime. Local defects идут в private inbox, внешние beta —
обезличенным GitHub issue.
