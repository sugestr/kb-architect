# Применение выпуска без самоудостоверяющего marker

Этот reference читают только когда `kb_apply.py` вернул `NEEDS_APPLICATION` или
`APPLICATION_UNPROVEN`. Доставка файлов скилла и миграция проекта — разные результаты.
`kb_standard_version` является финальным указателем, а не доказательством сделанной
работы.

## Режим задачи

- **«Обнови скилл базы знаний»** — action-first: после `kb_apply.py` выполняй
  обратимые локальные шаги и commits ниже до owner gate. `Проверь`/`аудит`/
  `read-only`/`только отчёт` — диагностика без записи.
- Переиспользуй валидные snapshot, ledger, candidate changes, tests и receipts: сверь
  commit/hash и продолжи с первого незакрытого шага без широкого повторного аудита.
- Явный `to_version` владельца/receipt ограничивает цикл: новая installed version
  его не расширяет. Проверяй цель через
  `kb_apply.py <root> --target-version <to_version>`; остальное — следующая дельта.

Предметный выбор, post-results acceptance, secrets/private runtime, внешнее действие
и push/publication сохраняют отдельную authority.

## 1. До первой записи

В чистом или честно описанном Git checkout зафиксируй:

- exact commit/ref до миграции;
- project-relative файл, где прочитан прежний marker, его SHA-256 и прежнюю версию;
- полный диапазон выпусков `(from_version, to_version]`, который показал `kb_apply.py`;
- текущие проверки, незакоммиченные изменения и authority задачи.

Создай незавершённый `KB_RELEASE_APPLICATION.json` из
`assets/templates/release-application.json`, но не ставь `finalized` и не повышай marker.
Source commit должен оставаться доступным предком итогового checkout. Если marker раньше
не было, сначала восстанови его по истории; не назначай прошлую версию на глаз.
Если locator — tracked относительный symlink вроде `AGENTS.md -> CLAUDE.md`, записывай
именно locator и hash прочитанных target bytes: checker безопасно разыменует его внутри
того же source commit и запретит absolute/escaping/looping target.

Tracked-only candidate живёт в текущем checkout: exact pre-change commit уже rollback,
поэтому второй каталог/ветка не нужны. Worktree нужен для реальной параллельной записи;
Keychain, MCP, AWS и другое состояние вне Git — для отдельного staged cutover.

Для нового проекта допустим первый элемент `kind: initial-adoption`,
`from_version: null`: source snapshot доказывает отсутствие marker, а ledger содержит
только принятую текущую редакцию. Это не заставляет новый проект разбирать всю историю.

## 2. Один ledger на весь диапазон

На каждую строку release history запиши ровно один исход:

- `applied` — изменение применено и названо evidence;
- `deferred` — сознательно отложено, записаны условие возврата и безопасный текущий режим;
- `declined` — владелец отказался, записаны причина и последствия;
- `not-applicable` — проверена неприменимость к этому проекту;
- `tool-inherited` — изменение относится только к установленному инструменту и
  подтверждено его тестом/версией.

Marker одной поздней версии не закрывает промежуточные строки. Evidence — адреса
проверяемых project receipts, diff или test output, а не фраза «сделано».

## 3. Candidate, результаты, владелец

Сначала внеси обратимый candidate и прогони применимые project tests. Покажи владельцу:

- exact diff и что осталось вне scope;
- отдельные `PASS`, `FAIL`, `UNKNOWN`, без превращения недоступного proof в PASS;
- стоимость до/после и rollback;
- для ролей — четыре независимых gate из `references/project-roles.md`.

Только после этого получи post-results acceptance. Разрешение начать миграцию не равно
приёмке её результата.

## 4. Finalize

В одном точечном project commit:

1. заверши ledger и owner evidence;
2. поставь `status: finalized` и `finalized_at`;
3. повысь `kb_standard_version` до `to_version`;
4. прогони `kb_apply.py <root> --target-version <to_version>`, `kb_check.py`,
   `kb_due.py` и project tests; более новая installed version в `kb_due.py` —
   следующая дельта, не провал этой приёмки.

Для v6+ `kb_apply.py` возвращает 0 только если tracked receipt восстанавливает source,
имеет непрерывную цепочку до marker и точный ledger всех выпусков. Неполная квитанция —
`APPLICATION_UNPROVEN`, даже если номер уже новый.

## 5. Три независимые authority

Project-local commit, доставка приватного отчёта его объявленному получателю и push/
publication во внешний remote — три разных действия. Разрешение на первое не переносится
на второе или третье. `BLOCKED_LOCAL` не разрешает GitHub fallback. Prepared, committed,
delivered, pushed и owner-accepted записываются разными исходами.
