---
name: kb-architect
description: "Knowledge-base contract and tools for durable AI projects. Start, audit, update, restructure or move a KB; coordinate Claude/Codex; audit domain skills, runtime and credential access. Use for KBs, project skills, cloud/MCP/Keychain, пароль/карточка, agent purchases, cleanup, two-agent work and 'перенеси себя в общее поле'."
license: MIT
metadata:
  version: "5.15"
  author: "sugestr"
---

# kb-architect — лёгкий вход

Скилл сохраняет один канон при смене чатов и агентов, отделяет факт от
интерпретации и передаёт работу между Claude и Codex. Он не заменяет предметную
роль, первичные источники или разрешение владельца на внешнее действие.

## Сначала выбери маршрут

Не читай весь пакет. Открой только строки, нужные текущей задаче.

| Задача | Что прочитать или запустить |
|---|---|
| Объяснить возможности, найти команду | этот файл; больше ничего |
| Обычная работа в уже принятом проекте | канонические правила проекта + его текущее состояние; общий контракт повторно не читать |
| Создать базу | `references/contract.md` + `references/start-new.md` |
| Присоединить, диагностировать или перестроить существующую | `references/contract.md` + нужная часть `references/adopt-existing.md` |
| Перенести один checkout в общий проект Claude/Codex | `references/contract.md` + `references/move-project.md`; после собственных приёмок UI-проекты обеих систем получают `* `, путь — нет |
| Обновить стабильный скилл и применить выпуск | `references/service-layer.md`; для быстрой проверки `scripts/kb_update.py --public --fast --сделать` |
| Работать нескольким агентам, принять или передать сообщение | `references/collaboration.md` + `assets/templates/agent-message.md` |
| Проверить внутренний профессиональный skill | `references/modules.md` → `capability_skills` + `scripts/kb_skills.py` |
| Подготовить облачную работу или проверить MCP/почту в разных средах | `references/modules.md` → `runtime_capabilities` + `scripts/kb_environments.py` |
| Пароли, карты, Remote или покупка | `references/modules.md` → `agent_vault_and_external_actions` |
| Разобрать входящее, сверить реальность, найти факт | `references/operations.md` + `scripts/kb_lookup.py` |
| Сделать существенный вывод из KB | current state + project domain skill + `scripts/kb_lookup.py --help` |
| Проверить целостность или просрочку | `scripts/kb_check.py` и/или `scripts/kb_due.py` |
| Отделить факт, интерпретацию и решение | `references/knowledge-roles.md` |
| Собрать мусор | `references/garbage-collection.md` |
| Понять authority и границы публикации | `references/authority.md` |
| Измерить пользу/стоимость слоёв или разобрать дефект | `references/measurement.md` + `scripts/kb_cost.py --check`; maintainer также читает `references/maintainer.md` |

Если маршрут неочевиден, прочитай только диагностику в `references/00-kak-chitat.md`.
`references/releases.md` целиком не открывай: историю между версиями извлекает
`scripts/kb_apply.py`.

## Инварианты исполнения

- Контракт заморожен в `references/contract.md`; справочник не добавляет проекту
  обязательств молча.
- В зрелом проекте локальные правила и domain skill имеют приоритет для роли,
  authority, source ladder, stop/escalation и запрещённых действий.
- Git не переносит local MCP, Keychain и ignored-файлы. Принимай внешнюю
  возможность по runtime, account, scope и safe probe.
- Высокорисковое, внешнее или необратимое действие требует проектных источников и
  владельческого гейта независимо от того, насколько простой вопрос его вызвал.
- Последовательно используй один checkout; параллельным писателям — отдельные
  worktree/ветки и exact-path commits.
- В режиме отчёта или read-only старое разрешение на запись не переносится:
  текущая задача должна явно назвать разрешённые изменения до первой записи.
- Существенный project-derived вывод проходит `kb_lookup.py --claim`; без receipt
  `supported|qualified` это draft/`UNKNOWN`. Domain skill задаёт темы, core — гейт.
- Не перечитывай неизменный reference в одной логической задаче. Новый выпуск,
  authority-контекст или изменившийся файл сбрасывает эту квитанцию.

## Дешёвый рабочий цикл

Новый пользовательский turn — не новый вход. Переиспользуй boot receipt, пока root,
current pointer, редакция и authority-context прежние; файл создаёт только evidence gate.

До вызова инструментов выбери критический путь:

- **только ответ:** current state → точечный KB lookup → ответ; updater, полный
  audit, inbox, Git, defect report и memory не входят в этот путь сами по себе;
- **ответ + долговременное изменение:** ранний проверенный результат → durable tail;
- **опасное/внешнее действие:** сначала относящийся к нему authority/source gate.

1. Прочитать короткий проектный вход и текущее состояние.
2. Запустить только принятые проектом локальные проверки. Их PASS относится лишь
   к перечисленному охвату; ошибка или непройденный запуск — `UNKNOWN`, не PASS.
3. Открыть один routed reference или project skill только при соответствующем
   триггере.
4. Если запрос одновременно требует полезный текст сейчас и долговременный intake,
   показать помеченный черновик сразу после достаточной сверки; durable tail не
   ставить перед первым полезным результатом.
5. Записать результат в канон, corrections или исход сообщения; не создавать
   вторую копию текущего состояния.
