---
name: kb-architect
description: "Durable AI knowledge-base router: start, audit, update or move a KB; coordinate agents, roles, runtimes, credentials and cloud/MCP; пароль, карточка, 'перенеси себя в общее поле'."
license: MIT
metadata:
  version: "6.3.3"
  minimum_project_version: "6.3.0"
  author: "sugestr"
---

# kb-architect — лёгкий вход

Сохраняет один канон между агентами. Проектные роли выбирает проект, не ядро.

## Сначала выбери маршрут

Не читай весь пакет. Открой только строки, нужные текущей задаче.

| Задача | Что прочитать или запустить |
|---|---|
| Объяснить возможности, найти команду | этот файл; больше ничего |
| Обычная работа в принятом проекте | правила проекта + current; общий контракт не перечитывать |
| Новый локальный запуск | этот файл + current; updater не ставить перед первым безопасным результатом без project pre-work gate |
| Создать базу | `references/contract.md` + `references/start-new.md` |
| Присоединить/перестроить существующую | `references/contract.md` + нужная часть `references/adopt-existing.md` |
| Перенести checkout для Claude/Codex | `references/contract.md` + `references/move-project.md`; UI-имена получают `* ` |
| Обновить установленный скилл | «Обнови скилл базы знаний»: action-first по `references/service-layer.md` |
| Применить release delta к проекту | `references/migration.md` + `scripts/kb_apply.py <root>` |
| Несколько агентов или handoff | `references/collaboration.md` + `assets/templates/agent-message.md` |
| Создать, проверить, разделить или подключить проектную роль | `references/project-roles.md` + `scripts/kb_skills.py` |
| Проверить cloud/MCP/почту по средам | `references/modules.md` → `runtime_capabilities` + `scripts/kb_environments.py` |
| Пароли, карты, Remote или покупка | `references/modules.md` → `agent_vault_and_external_actions` |
| Разобрать приложенный локальный файл («пришло») | `references/incoming.md` |
| Сверить реальность, найти факт или gap | `references/operations.md` + `scripts/kb_lookup.py` |
| Сделать существенный вывод из KB | current state + matching project role + `scripts/kb_lookup.py --help` |
| Проверить целостность или просрочку | `scripts/kb_check.py` и/или `scripts/kb_due.py` |
| Отделить факт, интерпретацию и решение | `references/knowledge-roles.md` |
| Собрать мусор | `references/garbage-collection.md` |
| Понять authority и границы публикации | `references/authority.md` |
| Измерить пользу/стоимость слоёв | `references/measurement.md` + `scripts/kb_cost.py --check` |
| Разобрать дефект или сопровождать скилл | `references/measurement.md` + `references/maintainer.md` |
| Собрать или доставить баг-репорт | из consumer project — только `assets/templates/defect-report.md` + `scripts/kb_report.py --help`; maintenance запрещён |

Неясный маршрут — `references/00-kak-chitat.md`; release-дельту извлекает
`scripts/kb_apply.py`, историю не перечитывай.

## Инварианты исполнения

- Контракт — `references/contract.md`; reference обязателен лишь после принятия.
- Project rules/role задают modality, authority, sources и stops.
- `PROJECT_ROLES.json` задаёт triggers, `KNOWLEDGE_INDEX.json` — адреса;
  непокрытая существенная работа = stop, matching required-роли загружаются все.
- Git не переносит MCP/Keychain/ignored state; runtime = account + scope + safe probe.
- Внешнее/необратимое/высокорисковое требует project source + owner gate.
- Consumer project: дефект общего скилла → только bug-report; package/project
  canon не править. Maintenance требует `kb_owner_gate.py` = `PASS`; иначе
  `BLOCKED_WRONG_EXECUTOR`, без owner-worktree/write/release/install.
- Последовательно — один checkout; параллельным писателям — worktree/ветка и exact paths.
- Report/read-only сбрасывает старую write-authority; targets нужны до записи.
- `kb_lookup.py --claim` нужен project-derived выводу, не прямым полям источника;
  domain skill задаёт темы, core — гейт.
- Update не report-only: installed entry ведёт local changes до owner gate; public — delivery.
- Текущая версия одна: `6.3.3`. `minimum_project_version: 6.3.0` — только
  порог проекта: ниже обновить один раз; patch миграцию не повторяет.
- Рост route блокирует `kb_cost.py --check` как `OPTIMIZATION_REQUIRED`.
- Не перечитывай reference без изменения; новая версия/file/authority сбрасывает receipt.

## Дешёвый рабочий цикл

Новый turn — не новый вход. Переиспользуй receipt при тех же root/current/version/authority;
изменившийся файл создаёт только свой evidence gate.

До вызова инструментов выбери критический путь:

- **только ответ:** current → lookup → ответ, если нет новой/изменённой
  `SOURCE / FACT / INTERPRETATION / DECISION / OPEN`; без audit/inbox/Git;
- **material delta:** ранний результат → durable tail; без write-authority —
  `DURABLE_TAIL=PENDING` + точные targets/bounded handoff;
- **опасное/внешнее действие:** сначала относящийся к нему authority/source gate.

1. Короткий project entry/current и обязательную диагностику читать параллельно
   с уже доступным источником; локальный файл не требует MCP-инвентаря.
2. Запустить только принятые проверки; PASS не шире их охвата, сбой — `UNKNOWN`.
3. Открыть один routed reference/project skill только по trigger.
4. Полезный проверенный черновик показать сразу; назвать этап понятным языком,
   durable tail не ставить перед ним.
5. Дельту закрыть каноном/corrections/исходом сообщения либо `PENDING`;
   навигация, цитата и brainstorm tail не создают.
