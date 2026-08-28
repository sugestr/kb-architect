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

Это один Git-канон для локальных и облачных Claude/Codex и их runtime на AWS, а не
копии под платформы. Доступность Git, connector и secret принимается по средам.
В boot canon достаточно адресов двух manifest и правила `load every matching required
role`.

`PROJECT_ROLES.json` единолично владеет project-specific `load_when`; `SKILL.md`
владеет методом. Агент не угадывает matching глобально. Непокрытая или двусмысленная
существенная работа останавливается; все совпавшие required-роли загружаются, конфликт
не усредняется.

## Содержание и разделение

В `SKILL.md` оставляй только решения, меняющие поведение: назначение и границу; метод
и обязательные проверки; source ladder и разрешение конфликтов; evidence threshold;
stop/escalation и запреты; нужные классы знания без локальных адресов; критерии
приёмки. Факты дела, полный закон, состояние, контакты, portal recipes и переписка
остаются в KB.

Разделяй роли, если различаются trigger, полномочия, source ladder, stops либо обычная
задача требует только одной части. Число ролей не ограничивается само по себе.

## Рост, приёмка и стоимость

Обычный цикл знания применим без изменений: реальные задачи → read-only опись → при
необходимости provenance/licence community-роли → минимальный candidate → примеры →
приёмка → version и commit. Community-роль можно принять, адаптировать или смешать,
но она не становится authority без проверки. Факт одного дела не меняет роль.

Regression обязан покрыть `role-selection`, `knowledge-recall`, `authority-stop`,
`source-conflict`, `context-cost`. Декларации недостаточно: Git-tracked
`ROLE_ACCEPTANCE.json` связывает прямую приёмку владельца с hashes manifest, knowledge
index, всего tracked-дерева роли, этими cases и cost baselines. Изменение метода,
trigger, wiring или baseline протухляет квитанцию; `candidate` не получает готовность.

`kb_skills.py` считает комбинации ролей. Помимо обычных task-сценариев обязателен
`all_roles_scenario` — верхний предел загрузки всех ролей, а не команда всегда их
грузить. Непринятый рост даёт `OPTIMIZATION_REQUIRED`. 8 КиБ — review threshold, не
универсальный максимум; превышение требует причины и квитанции. Оптимизация
отменяется, если после неё потерян recall знания или stop.

Вынос знания из толстой роли атомарен: создать канон → добавить route/aliases →
связать роль → доказать fresh-context recall → удалить копию из роли.

Шаблоны: `assets/templates/project-roles.json`, `knowledge-index.json`,
`role-acceptance.json`. Проверки:

```bash
python3 <kb-architect>/scripts/kb_index.py <project>
python3 <kb-architect>/scripts/kb_skills.py <project>
```

## Старый адрес и заимствование

До приёмки shadow-кандидата legacy-реестр остаётся authoritative; candidate проверяют
явным `--registry <project>/PROJECT_ROLES.json`. После приёмки `.kb-skills.json`
заменяют `legacy-role-registry.json`: новый checker следует к `PROJECT_ROLES.json`, а
человек, открывший старый адрес, видит сообщение «файл устарел». Pre-6.0 checker
остановится на неизвестной схеме и должен обновиться на безопасной границе. Это
navigation tombstone, не второй канон и не совместимость нового schema с v5.

По умолчанию роль принадлежит одному проекту. При редком заимствовании owner выпускает
версию, потребитель фиксирует repository + exact pin + recovery и отдельно принимает
snapshot. Загружаемый checkout обязан стоять на pin без локальной дельты. Изменения
возвращаются owner; project knowledge routes остаются локальными. Центральный
репозиторий оправдан только повторяющимся совместным владением.

## Миграция и критерий успеха

Проекты идут по одному от простых к смешанным. Сначала read-only отчёт: реальные
roles/triggers, знания и tools внутри ролей, пробелы индекса, вопросы владельцу, цена
маршрутов и пять regression cases. После ответов — shadow; после сравнения и прямой
приёмки — receipt, version, commit и tombstone.

Сам индекс и каждый его путь должны быть Git-tracked. Для внешнего или большого
источника индексируй tracked pointer с provenance/recovery, а не локальный кэш.

Успех: агент быстрее выбирает роль, находит существующее знание без подсказки, меньше
грузит лишнего, честно останавливается и одинаково восстанавливается. Дефекты идут
штатно: локальные — в private inbox, внешние beta — обезличенным GitHub issue.
