---
name: kb-architect
description: "Knowledge-base contract and tools for durable AI projects. Start, audit, update, restructure or move a KB; coordinate Claude/Codex; audit domain skills, runtime and credential access. Use for KBs, project skills, cloud/MCP/Keychain, пароль/карточка, agent purchases, cleanup, two-agent work and 'перенеси себя в общее поле'."
license: MIT
metadata:
  version: "5.12"
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
| Разобрать входящее, сверить реальность, найти факт | `references/operations.md`; перед выводом об отсутствии — `scripts/kb_lookup.py` |
| Проверить целостность или просрочку | `scripts/kb_check.py` и/или `scripts/kb_due.py` |
| Отделить факт, интерпретацию и решение | `references/knowledge-roles.md` |
| Собрать мусор | `references/garbage-collection.md` |
| Понять authority и границы публикации | `references/authority.md` |
| Измерить пользу/стоимость слоёв или разобрать дефект | `references/measurement.md` + `scripts/kb_cost.py --check`; maintainer также читает `references/maintainer.md` |

Если маршрут неочевиден, прочитай только диагностику в `references/00-kak-chitat.md`.
`references/releases.md` целиком не открывай: историю между версиями извлекает
`scripts/kb_apply.py`.

## Инварианты исполнения

- Контракт заморожен. Его канон — `references/contract.md`; не пересказывай его
  как новые проектные правила и не добавляй обязательств из справочника молча.
- В зрелом проекте локальные правила и domain skill имеют приоритет для роли,
  authority, source ladder, stop/escalation и запрещённых действий.
- Git не переносит в облако local MCP, Keychain и ignored-файлы. Внешнюю
  возможность принимай для runtime, account, scope и safe probe.
- Высокорисковое, внешнее или необратимое действие требует проектных источников и
  владельческого гейта независимо от того, насколько простой вопрос его вызвал.
- В последовательной работе используется один checkout. Параллельные писатели
  работают в отдельных worktree/ветках и коммитят только точные пути.
- В режиме отчёта или read-only старое разрешение на запись не переносится:
  текущая задача должна явно назвать разрешённые изменения до первой записи.
- Не перечитывай в одной логической задаче тот же reference, если путь и содержимое
  не изменились. Новый выпуск, новый authority-контекст или изменившийся файл
  аннулируют это допущение.

## Дешёвый рабочий цикл

Новый пользовательский turn — не новый вход в проект. В одной живой задаче не
повторяй boot/service cycle, если root, current pointer, редакция скилла и
authority-context не изменились. Квитанция живёт в контексте задачи; отдельный файл
ради неё не нужен.

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
