# Правила и текущее состояние проекта <ИМЯ>

<Одна-две фразы: назначение проекта и кто его пользователь.>
project root: . (repo root; локальный абсолютный путь не является инструкцией проекта)
project topology: <focused | portfolio | hybrid; диагностическая модель, не gate>
текущее состояние: раздел «Сейчас» в этом файле
подробные правила: <PROJECT_GUIDE.md или «нет»>

Это один физический boot/current canon. `CLAUDE.md` и `AGENTS.md` лучше связать
symlink на одни байты. Отдельный `NOW.md` нужен только если проект сознательно
разделяет часто меняющееся состояние и стабильные правила.

## Сейчас

Обновлено: YYYY-MM-DD

- Где мы: <только настоящее>.
- Что дальше: <следующий шаг>.
- Чего ждём: <от кого, с какого числа, что делать при тишине>.
- Что запрещено без владельца: <stop-condition>.
- Что не знаем: <UNKNOWN/OPEN>.

## Вход в сессию

Этот цикл выполняется один раз на новую task/session, не на каждое сообщение.
Неизменные root, current, версия и authority-context повторно не загружай.

«Обнови скилл базы знаний» — action-first до owner gate, не ещё один отчёт.
Acceptance, secrets/private runtime и push требуют отдельной authority.

1. Прочитай current; локальный приложенный источник — в том же первом пакете.
2. Если update не отключён, запусти `kb_update.py --public --fast --сделать
   --project <корень-проекта>` после первого безопасного результата. До durable/external шага
   после `INSTALLED` перечитай entry/route. Явный project pre-work gate имеет приоритет.
3. Если в «Соответствии» **явно принята диагностика** при входе, запусти один
   объявленный readiness command/manifest. Не дублируй здесь его внутренний список.
   Ошибка запуска или ненайденный scope — `UNKNOWN`, не PASS.
4. Required role прочитай до интерпретации/совета. Точные поля источника — `SOURCE`.
   Отсутствие required skill — stop-condition.

## Authority и stop-gates

- Не утверждать поведение внешней системы из памяти; сверить или назвать `TBD`.
- Внешние и необратимые действия: <что требует отдельного одобрения владельца>.
- Источник полномочий по предметным выводам: <project role / source ladder>.
- Запрещено: <действия, которые агент не выполняет>.
- Доступы: хранить место секрета, не значение.

Этот блок остаётся в коротком входе: его нельзя прятать в подробностях, потому что
даже простой вопрос может привести к опасному действию.

## Соответствие kb-architect

kb_standard_version: <минимальная совместимая версия проекта, сейчас 7.0.0>
release application: `KB_RELEASE_APPLICATION.json`
сервисный контур kb-architect: <принят | не принят>
обновление скилла: <по сигналу | автоматически>
канал обновления скилла: GitHub public https://github.com/sugestr/kb-architect
маршрут отчётов: <local-inbox | github-issue>
инбокс отчётов: <для local-inbox — прямой путь>

Принято:
- <например: readiness: один script/manifest, который сам владеет составом проверок>
- <например: service-layer fast update>

Отклонено или отложено:
- <возможность> — <исход и причина/условие возврата>

<Если сервисный контур принят, new task до project-derived работы выполняет delivery
+ `kb_apply.py`. `NEEDS_APPLICATION`/`APPLICATION_UNPROVEN` остаётся до короткой
post-results приёмки; marker меняется последним. Patch build его не переоткрывает.
Новая возможность получает
явный исход. Никаких симлинков рабочего проекта на private development checkout.>

## Профессиональные роли

roles: `PROJECT_ROLES.json`
knowledge routes: `KNOWLEDGE_INDEX.json`
role selection: project-declared; load every matching required role
role readiness: `PROJECT_ROLES.json` → `skills[].validation` + `acceptance`

## Среды и внешние возможности

cloud policy: <allowed | pending | prohibited>
runtime capabilities: <нет | реестр .kb-environments.json>

<Локальный MCP, Keychain и папка вне Git не появляются в облаке автоматически.
Required external capability получает provider, identity, scope, authority и acceptance
для каждой среды. Недоступность — точный BLOCKED. Проверяй при setup/adopt, не на
каждый обычный вопрос.>

## Граница записи и совместная работа

- Канон текущего состояния: <один путь/раздел/запрос>.
- Последовательно Claude и Codex работают в одном checkout.
- Параллельные писатели — отдельные worktree/ветки; коммит только exact paths.
- `read-only`, `только отчёт` или `диагностируй` в текущем запросе отменяет старую
  write-authority до явного списка targets.
- Реорганизация требует точного scope, rollback и task-authority; явная команда
  обновить/мигрировать разрешает обратимые изменения внутри названного проекта.
- Не сокращать по числу байт вслепую. Сначала карта блоков и адресов, затем проверка
  fresh-context recall/authority/stops. `project_boot_budget_bytes` — только явное
  решение проекта; без него размер измеряется информационно.

## Минимальная семантика знания

- Совершённое действие без достаточного `verify` — не факт.
- `valid_until` ставится только при предметно обоснованном сроке; неизвестная
  свежесть остаётся `UNKNOWN`, а не получает произвольную дату.
- Производный файл получает `generated_from` и правится в источнике.
- Ошибка сначала дописывается в `CORRECTIONS.md`; закрывается ссылкой на исправленный
  канон, а не одной записью о проблеме.

## Роуты подробностей

| Trigger | Читать |
|---|---|
| структура, владение, recovery | <PROJECT_GUIDE.md#...> |
| предметный вывод | <skills/<name>/SKILL.md> |
| обновление стандарта | `kb_apply.py` output + `references/service-layer.md`; при дельте `references/migration.md` |
| облачная работа или внешний connector | `.kb-environments.json` + `kb_environments.py` |
| перенос проекта | `references/move-project.md` |
| handoff/report | `references/collaboration.md` |

Не добавляй сюда длинную историю или справочник «на всякий случай». Но и не выноси
уникальное правило только ради размера: маршрут считается рабочим лишь после проверки,
что новая сессия находит его вовремя.
