---
name: kb-architect
description: "Build and improve durable project knowledge bases: diverse knowledge, professional roles, nested projects, reliable intake and retrieval, low-cost maintenance. Создать, проверить, обновить или перестроить базу знаний."
license: MIT
metadata:
  version: "7.0.3"
  minimum_project_version: "7.0.0"
  author: "sugestr"
---

# kb-architect

Инфраструктура знаний: сохранить, найти и применить с нужной ролью, видимыми
ограничениями и соразмерной ценой. Предметную структуру и методы выбирает проект.

## Выбери маршрут

Не читай весь пакет. Обычная работа в принятом проекте использует его boot/current
и нужную роль; общий контракт заново не загружается.

| Задача | Что прочитать или запустить |
|---|---|
| Объяснить возможности, найти команду | этот файл |
| Обычная работа в принятом проекте | правила проекта + current |
| Новый локальный запуск | этот файл + current; updater после первого безопасного результата |
| Создать базу | `references/contract.md` + `references/start-new.md` |
| Присоединить/перестроить существующую | `references/contract.md` + `references/adopt-existing.md` |
| Перенести checkout для Claude/Codex | `references/move-project.md` |
| Обновить установленный скилл | `references/service-layer.md` |
| Применить release delta к проекту | `references/migration.md` + `scripts/kb_apply.py` |
| Несколько агентов или handoff | `references/collaboration.md` + `assets/templates/agent-message.md` |
| Создать, проверить, разделить или подключить проектную роль | `references/project-roles.md` + `scripts/kb_skills.py` |
| Связать области, SQL, вложенный проект или сводную | `references/knowledge-routing.md` + `scripts/kb_index.py` |
| Проверить cloud/MCP/почту по средам | `references/modules.md` → `runtime_capabilities` |
| Пароли, карты, Remote или покупка | `references/modules.md` → `agent_vault_and_external_actions` |
| Разобрать приложенный локальный файл («пришло») | `references/incoming.md` |
| Сверить реальность, найти факт или gap | `references/retrieval.md`; внешняя сверка — `references/operations.md` |
| Сделать существенный вывод из KB | current + matching role + `references/retrieval.md` → `evidence_contract` |
| Проверить целостность или просрочку | `scripts/kb_check.py`, `scripts/kb_due.py` |
| Отделить факт, интерпретацию и решение | `references/knowledge-roles.md` |
| Собрать мусор | `references/garbage-collection.md` |
| Понять authority и границы публикации | `references/authority.md` |
| Измерить пользу/стоимость слоёв | `references/measurement.md` + `scripts/kb_cost.py --check` |
| Разобрать дефект или сопровождать скилл | `references/measurement.md` + `references/maintainer.md` |
| Собрать или доставить баг-репорт | `assets/templates/defect-report.md` + `scripts/kb_report.py --help` |

## Общие границы

- Один owner/source текущего знания. Файл, раздел, SQL и вложенная область —
  допустимые формы; индекс хранит адреса, роль — метод, hub — координацию.
- `PROJECT_ROLES.json` задаёт triggers; непокрытая существенная работа = stop.
  Matching required-роли загружаются все, предки/общие методы — один раз.
  Предметные источники и stops не заменяются памятью модели.
- Существенный project-derived вывод требует evidence по `retrieval.md`.
  Принятый query/ledger заменяет дублирующий lexical receipt; прямые поля источника
  его не требуют. Пустой поиск и механический PASS не доказывают полноту/истину.
- Внешнее/необратимое/высокорисковое требует project source + owner gate.
  Report/read-only сбрасывает старую write-authority. Git не переносит secrets/MCP.
- Consumer project: дефект общего скилла → только bug-report. Maintenance требует
  `kb_owner_gate.py` = `PASS`; иначе `BLOCKED_WRONG_EXECUTOR`, без записи в owner.
  Параллельным писателям — отдельные worktree/ветки и exact paths.
- Новый минимальный уровень проекта принимается один раз по `migration.md`;
  совместимый patch не повторяет миграцию. Установка не повышает marker и не
  перечитывает инструкции активной сессии. Stable update — `service-layer.md`.

## Рабочий цикл

Current → нужная роль/адрес → полезный проверенный результат → долговременная дельта.
Новый turn — не новый вход; неизменное прочитанное переиспользуется.

Локальный источник обрабатывай сразу, принятые обязательные проверки — параллельно.
Открывай только относящийся reference. Для ответа без новой
`SOURCE / FACT / INTERPRETATION / DECISION / OPEN` служебный tail не нужен.
Изменение сохраняй в каноне и зависимых представлениях; один пакет относящихся
проверок и точечная фиксация блока при имеющихся полномочиях. Незавершённое —
`DURABLE_TAIL=PENDING` с адресом продолжения. Сохрани весь объявленный вход;
обработанная часть не объявляется целой партией.

Ошибку/противоречие и неполноту показывай в границах затронутого вывода. Повтор
дефекта или лишней работы — сигнал к улучшению. Бюджеты проверяет `kb_cost.py`;
стоимость, полезность и реальные ошибки оцениваются вместе.
