---
name: kb-architect
description: "Durable AI knowledge-base router: start, audit, update, restructure or move a KB; coordinate Claude/Codex; manage project roles, runtimes, credentials, cloud/MCP and multi-agent work; пароль, карточка, 'перенеси себя в общее поле'."
license: MIT
metadata:
  version: "6.2.5"
  author: "sugestr"
---

# kb-architect — лёгкий вход

Скилл сохраняет один канон между агентами. Проект добавляет свои роли; ядро их не выбирает.

## Сначала выбери маршрут

Не читай весь пакет. Открой только строки, нужные текущей задаче.

| Задача | Что прочитать или запустить |
|---|---|
| Объяснить возможности, найти команду | этот файл; больше ничего |
| Обычная работа в уже принятом проекте | канонические правила проекта + его текущее состояние; общий контракт повторно не читать |
| Новый локальный запуск | если update не отключён: до работы `scripts/kb_update.py --public --fast --сделать --project <root>`; затем новый entry/дельта |
| Создать базу | `references/contract.md` + `references/start-new.md` |
| Присоединить, диагностировать или перестроить существующую | `references/contract.md` + нужная часть `references/adopt-existing.md` |
| Перенести checkout для Claude/Codex | `references/contract.md` + `references/move-project.md`; UI-имена получают `* ` |
| Обновить установленный скилл | «Обнови скилл базы знаний»: action-first по `references/service-layer.md` |
| Применить release delta к проекту | `references/migration.md` + `scripts/kb_apply.py <root>` |
| Работать нескольким агентам, принять или передать сообщение | `references/collaboration.md` + `assets/templates/agent-message.md` |
| Создать, проверить, разделить или подключить проектную роль | `references/project-roles.md` + `scripts/kb_skills.py` |
| Проверить cloud/MCP/почту по средам | `references/modules.md` → `runtime_capabilities` + `scripts/kb_environments.py` |
| Пароли, карты, Remote или покупка | `references/modules.md` → `agent_vault_and_external_actions` |
| Разобрать входящее, сверить реальность, найти факт | `references/operations.md` + `scripts/kb_lookup.py` |
| Сделать существенный вывод из KB | current state + matching project role + `scripts/kb_lookup.py --help` |
| Проверить целостность или просрочку | `scripts/kb_check.py` и/или `scripts/kb_due.py` |
| Отделить факт, интерпретацию и решение | `references/knowledge-roles.md` |
| Собрать мусор | `references/garbage-collection.md` |
| Понять authority и границы публикации | `references/authority.md` |
| Измерить пользу/стоимость слоёв | `references/measurement.md` + `scripts/kb_cost.py --check` |
| Разобрать дефект или сопровождать скилл | `references/measurement.md` + `references/maintainer.md` |
| Собрать или доставить баг-репорт | `assets/templates/defect-report.md` + `scripts/kb_report.py --help` |

Неясный маршрут: диагностика в `references/00-kak-chitat.md`. Историю
`references/releases.md` целиком не читай — дельту извлекает `scripts/kb_apply.py`.

## Инварианты исполнения

- Контракт — `references/contract.md`; reference обязателен только после явного принятия.
- Локальные правила и project role задают модальность, authority, source ladder и stops.
- `PROJECT_ROLES.json` объявляет role posture и triggers, `KNOWLEDGE_INDEX.json` —
  project-specific адреса знаний; непокрытая существенная работа — stop,
  все совпавшие required-роли загружаются, их конфликт не усредняется.
- Git не переносит MCP, Keychain и ignored-файлы; runtime принимай по account,
  scope и safe probe.
- Внешнее, необратимое или высокорисковое действие требует project source и owner gate.
- Последовательно используй один checkout; параллельным писателям — отдельные
  worktree/ветки и exact-path commits.
- В report/read-only старое разрешение на запись не переносится: targets нужны до записи.
- Существенный project-derived вывод проходит `kb_lookup.py --claim`; без receipt
  `supported|qualified` это draft/`UNKNOWN`. Domain skill задаёт темы, core — гейт.
- Update — не report-only: installed entry ведёт обратимые local changes до owner gate;
  public — только freshness/delivery.
- Marker хранит contract line; compact receipt — source/owner. Patch build
  не переоткрывает migration.
- Рост released route блокирует `kb_cost.py --check` как `OPTIMIZATION_REQUIRED`;
  число модулей не заменяет бюджет реально загружаемого маршрута.
- Не перечитывай неизменный reference в одной логической задаче. Новый выпуск,
  authority-контекст или изменившийся файл сбрасывает эту квитанцию.

## Дешёвый рабочий цикл

Новый пользовательский turn — не новый вход. Переиспользуй receipt при тех же root, current,
версии и authority; файл создаёт только evidence gate.

До вызова инструментов выбери критический путь:

- **только ответ:** current → точечный lookup → ответ; полный audit/inbox/Git не добавлять;
- **ответ + долговременное изменение:** ранний проверенный результат → durable tail;
- **опасное/внешнее действие:** сначала относящийся к нему authority/source gate.

1. Прочитать короткий проектный вход и текущее состояние.
2. Запустить только принятые проверки; PASS не шире их охвата, сбой — `UNKNOWN`.
3. Открыть один routed reference/project skill только по trigger.
4. Полезный проверенный черновик показать сразу; durable tail не ставить перед ним.
5. Записать итог в канон/corrections/исход сообщения без второй копии current.
