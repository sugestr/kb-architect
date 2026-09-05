# Проектные роли

Роль определяет цель и метод применения знаний. Инфраструктура управляет
обнаружением, версиями и проверками; предметную корректность принимает quality owner.

| Слой | Что хранит | Канон |
|---|---|---|
| selector | purpose, load_when, skill, knowledge_routes, optional extends | PROJECT_ROLES.json |
| method | способ рассуждения, source ladder, evidence threshold, stops | skills/<name>/SKILL.md |
| knowledge | факты, нормы, диагнозы, события, переписка, справочники, portal recipes | индексированная KB |
| tool | извлечение, проверка, расчёт или действие | предметный script/connector |

Роль не подтверждает лицензию. Знания не прячут в method skill: сначала создают
адрес/aliases и проверяют recall, затем удаляют копию. Claude/Codex находят один
Git-канон метода; global-only копия не доказывает recovery. Runtime/secrets — отдельно.

## Выбор и иерархия

Posture: `required`, `transitioning` или `not-applicable` с причиной.
Непокрытый существенный вывод — stop; совпавшие required-selector-ы загружаются
все, конфликт сохраняется. Чтение прямых полей и независимая работа продолжаются.

`extends: parent-role-id` — необязательная специализация внутри проекта. Предок
передаёт общую цель, метод и stops; ребёнок добавляет предметные условия. Ослабление
stop меняет владеющий метод и требует приёмки, не молчаливого override.
`kb_skills.py <root> --select <id>` даёт план предки → выбранные роли, один раз
каждый метод/маршрут. Цикл и неизвестный родитель — ошибка. Соседние роли не следуют
из наследования. CLI разрешает выбранные ids, но не определяет их релевантность.

Координатор и специалист могут требоваться вместе. Управление областью не является
`extends` профессионального метода и не передаёт компетенцию. Разные люди/компании
могут использовать одну роль; scope объекта, периода и юрисдикции задают источники.

Purpose проверяется поведением: как цель изменила сравнение вариантов и результат;
какие источники дали основание; что осталось недоказанным. Например, управляющий
сравнивает прибыль и затраты, предметный советник применяет свою лестницу источников.
Память — указатель или гипотеза. Актуальное проверенное основание переиспользуют
в пределах применимости, без полного повторного исследования каждой мелочи.

## Когда предложить новую роль

Предлагай синтез, когда устойчивые задачи требуют особой цели, source ladder,
ответственности или качества, а существующий метод не покрывает их либо постоянно
обрастает исключениями. Один серьёзный профессиональный пробел достаточен:
опасную ошибку не требуется повторять. Назови реальные задачи, ожидаемое изменение
поведения, цену и владельца качества.

Сначала проверь, хватает ли существующей роли, уточнения trigger или специализации.
Разные triggers могут делить один skill при общих authority/source/stops/quality owner.
Разделяй методы при расхождении этих границ либо постоянной дорогой загрузке лишнего.
Новая папка, человек, объём или разовый вопрос сами по себе роли не требуют.
Слабый сигнал сохраняют с условием возврата в существующем журнале, без пустого
skill и вечной тревоги. Предложение не означает автоматической приёмки.

## Приёмка

`kb_skills.py <root> --prepare-candidate` — read-only prefill из legacy/tracked
skills: смысловые `UNRESOLVED` и bounded prompt. Он не назначает профессию.
Принятый проект получает `action: none`.

Новый candidate хранит `kb-role-acceptance/v3` в PROJECT_ROLES.json. Отдельный
receipt tree, ROLE_ACCEPTANCE.json и mutation suite не нужны. Accepted schema 2–5,
compact v1/v2 и runner v1 остаются legacy-readable без patch-миграции.

Нужны четыре разных результата:

1. Структура: один канон, discoverable routes, recovery и принятый бюджет.
2. Один узкий проектный validator.
3. Fresh-context вопрос без имени роли: selection, indexed recall и реальный stop/conflict.
4. Приёмка показанного результата с честными OPEN по полномочиям из migration.md.

Candidate ставит `PENDING`; `--execute-project-check` запускает объявленный
tracked project-local validator и сам записывает PASS/FAIL, связывая command,
validator bytes, skill trees и wiring. Validator должен быть назван в command;
скрытый global code невоспроизводим. После изменения входов верни PENDING и
выполни один новый run. Поля runner не заполняют успехом вручную.

Fresh-context observation ссылается на native task/turn или tracked evidence.
Один агент получает TESTED; другой — INHERITED при тех же bytes/wiring и доказанной
способности runtime либо UNKNOWN. Изменение входа/метода требует относящегося
теста; patch сам по себе не требует model-turn. Owner/live не протухляют binding.

Compact acceptance связывает SKILL.md SHA-256; Git хранит остальные bytes и rollback.
Одноимённая active copy с другими bytes блокирует приёмку; retired вне active roots —
нет. `kb_behavior.py`, mutation и повторы по runtime нужны только для найденного риска.
Core suite выполняют при выпуске скилла, не в каждом проекте.

## Качество и цена

В compact `quality` manifest записаны владелец метода, состояние профессионального
review, knowledge_boundary и причина. Deferred требует условия возврата.
Packaging-only review не является профессиональным PASS. Подробный quality-файл
нужен предметной команде по потребности, не для удовлетворения ядра. Community-метод
принимают/адаптируют с provenance/licence; внешний обзор не повторяют на каждую правку.

`accepted_end_to_end_bytes` — единый бюджет entry, supporting files, routed knowledge
и control plane с запасом. Обязателен all_roles_scenario; 8 КиБ — review threshold.
Методы предков считаются один раз. Query считает рецепт; результаты БД/внешние
project routes измеряются в сценарии отдельно. Рост выше бюджета даёт
OPTIMIZATION_REQUIRED; сокращение с потерей recall/stop отклоняется. Actual
input/cached-input/output/orchestration tokens — квитанция либо UNKNOWN.

## Применение и заимствование

До переключения legacy authoritative, candidate проверяют через `--registry`;
source commit даёт rollback. После переключения .kb-skills.json — navigation
tombstone. Заимствованный метод имеет owner repository, exact pin и recovery;
изменение возвращают владельцу, knowledge routes потребитель объявляет у себя.

Проекты принимают по одному по `migration.md`: источник → candidate → относящиеся
проверки → решение → marker последним. Индексы и recovery pointers tracked. Успех — полезный
ответ, обнаруженное знание, правильный stop и меньшая цена работы.
