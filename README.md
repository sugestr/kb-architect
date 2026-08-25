# kb-architect

[Русский](#русский) · [English](#english)

**Beta toolkit for durable Claude and Codex projects: one knowledge canon,
recoverable professional roles, and checks that make confident contradictions
visible.**

**Бета-инструментарий для долгих проектов Claude и Codex: один канон знаний,
восстанавливаемые профессиональные роли и проверки, которые делают уверенные
противоречия видимыми.**

> Agent Skill · one-page frozen core · optional reference library · tested
> maintenance tools · Russian contract and references · bilingual overview · MIT

---

## English

`kb-architect` is a lightweight operating contract for AI-assisted projects that
must survive new chats, new agents and changing facts. It does not add another
memory database. It tells the project which files are authoritative, how current
claims expire, how contradictions are handled, and what a fresh session must verify
before it confidently acts on old knowledge.

Try it when a project already has useful files but repeatedly loses context, keeps
two versions of “what is current”, or moves work between Claude and Codex. A tiny
one-off project probably does not need it.

### Send this to a beta tester

Give them the [latest release](https://github.com/sugestr/kb-architect/releases/latest)
and this five-step route:

1. Install the skill and open a real, ongoing project with its existing files.
2. Paste the starter prompt below. The first pass is explanation and inspection, not a blind rewrite.
3. Continue two or three normal project tasks in separate chats.
4. Run the fresh-chat check below.
5. Submit one [beta report](https://github.com/sugestr/kb-architect/issues/new?template=beta-report.md), including “no useful difference” if that is what happened.

Starter prompt:

```text
I am beta-testing kb-architect on this project. Explain in plain language why it may
help here, what it will change, and what it will leave untouched. Then inspect the
project read-only and show me its competing sources of current state, stale claims,
and a minimal adoption plan. Do not change files until I approve the plan. If this
project makes professional judgements, do not invent expertise: tell me which
project-owned professional roles I have provided and which decisions remain outside
their authority.
```

Fresh-chat check:

```text
Without a recap from me, use the project canon to state what is current, what is
uncertain, what is stale, and what requires a professional role. Name the exact
sources you relied on and stop on contradictions.
```

### What it owns — and what it does not

| Layer | Responsibility |
|---|---|
| `kb-architect` | Knowledge lifecycle: one canon per class of state, freshness, provenance, contradictions, handoffs and maintenance checks. |
| Project knowledge base | Facts, evidence, current state, decisions and open questions for this specific project. |
| Professional/domain skills | The method for doing tax, legal, medical, financial, engineering or other domain work: role, source hierarchy, evidence threshold, stop conditions and prohibited actions. |
| Deterministic tools | Repeatable transformations and mechanical validation. |

Professional roles are **strongly recommended for any project that makes material
domain judgements**. One project may need one role or several narrowly scoped roles.
They are not decorative personas: each role is a project-owned, reviewable method.

`kb-architect` can register those skills, verify that Claude and Codex can discover
the same Git-tracked source, and test their recovery and authority boundaries. It
does **not** decide which professions your project needs, invent professional
expertise, or replace primary sources and qualified review. Without a domain skill,
the knowledge base can remain coherent while the professional quality of its
conclusions remains undefined. That is acceptable for a simple non-domain project;
it is usually a weak setup for serious subject-matter work.

### First beta run

1. Install the stable release for the platform you will test.
2. Start a fresh chat and say: `Explain what kb-architect would change in this project and what it would leave untouched.`
3. In an existing repository, say: `Adopt this knowledge base. Inspect first and show the proposed canon, conflicts and migration plan before changing files.`
4. If the project makes professional judgements, provide its project-owned domain skill or skills and ask: `Check that these professional roles are recoverable and available to both Claude and Codex.`
5. Use the project across several real sessions, then ask a fresh session to check for stale state and contradictions.

The useful beta result is not “installation succeeded”. It is an observed behaviour:
the agent found the right canon, stopped on a contradiction, missed a known fact,
invented authority, or could not recover a role in a fresh clone. Please report the
exact prompt, version, expected behaviour and observed behaviour in a
[GitHub issue](https://github.com/sugestr/kb-architect/issues). Remove secrets and
personal data first.

### Honest limits

- This is a research prototype with an acceptance suite, not a claim of universal maturity.
- The built-in lookup is lexical. An empty result is **not** proof that knowledge is absent.
- Measured retrieval misses can justify a semantic/vector index as a derived search layer; it finds candidates, but source files remain the canon.
- It does not supply professional advice, credentials, runtime access or permission for external actions.
- Cloud-ready project files do not prove that a local MCP, account or secret exists in a cloud runtime.
- The mandatory core is one frozen page; optional modules are adopted only for a demonstrated project need.

### Installation

**Claude Code plugin marketplace**

```text
/plugin marketplace add sugestr/kb-architect
/plugin install kb-architect@sugestr
```

Update later with `/plugin marketplace update sugestr`.

**Codex**

Download a stable public release and copy
`plugins/kb-architect/skills/kb-architect` as a managed directory to
`~/.codex/skills/kb-architect`. Do not symlink a working installation to a
development checkout. Future updates are handled by:

```bash
python3 ~/.codex/skills/kb-architect/scripts/kb_update.py --public --fast --do
```

Restart with a fresh task after an update; a running session does not hot-reload
skill instructions.

**Cowork or a regular chat**

Download `kb-architect.skill` from the
[latest release](https://github.com/sugestr/kb-architect/releases/latest), attach it
to the chat and install it from the file card.

---

## Русский

## Для чего это

Понедельник: ты объясняешь новому чату, что за проект, что уже решено и чего ждём.
К вечеру агент разобрался. Во вторник открывается новый чат — и всё начинается
сначала.

Через месяц появляется папка с заметками. В двух файлах уже разные сроки, два списка
«что дальше» живут независимо, а самый свежий по дате файл пересказывает состояние
чужой системы трёхмесячной давности. Агент открывает один из вариантов и уверенно
отвечает. Проблема уже не в нехватке памяти: **база выглядит надёжной и врёт**.

`kb-architect` добавляет проекту лёгкий эксплуатационный контракт:

- один канонический источник для каждого класса текущего состояния;
- срок годности утверждения отдельно от даты правки файла;
- различение источника, наблюдения, факта, интерпретации и решения;
- явную реакцию на противоречие вместо случайного выбора одной версии;
- контрольные вопросы, проверку просрочки и проверку целостности;
- передачу работы между сессиями, Claude и Codex без двух копий проекта;
- проверяемое восстановление project-owned профессиональных skills и внешних runtime-возможностей.

## Что переслать другу-тестеру

Дай ему ссылку на [последний выпуск](https://github.com/sugestr/kb-architect/releases/latest)
и короткий маршрут:

1. Установить skill и открыть не пустой пример, а свой живой проект с уже существующими файлами.
2. Вставить стартовый запрос ниже. Первый проход только объясняет и осматривает — ничего не перестраивает вслепую.
3. Выполнить две-три обычные задачи проекта в разных чатах.
4. Открыть ещё один свежий чат и выполнить контрольный запрос.
5. Заполнить один [beta-отчёт](https://github.com/sugestr/kb-architect/issues/new?template=beta-report.md), даже если результат — «заметной пользы нет».

Стартовый запрос:

```text
Я тестирую kb-architect на этом проекте. Объясни простыми словами, зачем он может
быть здесь полезен, что изменит и что оставит как есть. Затем проведи read-only
осмотр: покажи конкурирующие источники текущего состояния, протухшие утверждения
и минимальный план подключения. Не меняй файлы, пока я не одобрю план. Если проект
делает профессиональные выводы, не выдумывай экспертизу: назови уже предоставленные
project-owned профессиональные роли и решения, которые остаются вне их полномочий.
```

Контрольный запрос в свежем чате:

```text
Без пересказа с моей стороны используй канон проекта и скажи: что сейчас является
фактом, что не доказано, что протухло и где нужна профессиональная роль. Назови
точные источники и остановись, если они противоречат друг другу.
```

Минимум — одна замороженная страница `references/contract.md`. Справочник и
инструменты подключаются только тогда, когда проект встретил соответствующую
проблему. Векторная база, отдельный сервер и proprietary memory service не нужны.

## Важная граница: база знаний — не профессия

Для практического проекта полезно разделить четыре слоя:

| Слой | За что отвечает |
|---|---|
| `kb-architect` | Как знания хранятся, стареют, проверяются, конфликтуют и передаются. |
| KB проекта | Факты, доказательства, текущее состояние, решения и открытые вопросы конкретного дела. |
| Профессиональные/domain skills | Как профессионально работать в предметной области: роль, метод, иерархия источников, порог доказательности, условия остановки и запреты. |
| Скрипты и tools | Воспроизводимые преобразования и механические проверки. |

Если проект делает существенные налоговые, юридические, медицинские, финансовые,
инженерные или иные предметные выводы, **заранее подключить одну или несколько
профессиональных ролей настоятельно рекомендуется**. Несколько ролей нужны там, где
решение пересекает несколько областей; их scope и право на вывод должны быть
разделены явно.

Это не персонажи в промпте. Профессиональная роль — принадлежащий проекту и
проверяемый skill с методом, авторитетными источниками, порогом доказательности и
условиями, при которых агент обязан остановиться. `kb-architect` умеет вести реестр
таких skills, проверять один Git-канон, discovery для Claude и Codex, validation и
fresh-clone recovery.

Но он **не выбирает профессии за владельца, не сочиняет экспертизу и не заменяет
первичные источники или квалифицированную проверку**. Это намеренная граница. Без
domain skill база всё ещё может хорошо помнить факты и историю, но стандарт
профессионального вывода остаётся неопределённым. Для простого непредметного проекта
это нормально; для серьёзной предметной работы такая конфигурация обычно малоэффективна.

## Как попробовать на реальном проекте

После установки открой свежий чат и сначала попроси:

```text
Объясни, что kb-architect изменит в этом проекте, а что оставит как есть.
```

Если файлы уже существуют:

```text
Присоедини kb-architect к этому проекту. Сначала проведи read-only осмотр и покажи:
текущий канон, конкурирующие источники, риски и план. Ничего не переноси без согласования.
```

Для нового проекта:

```text
Заведи базу знаний этого проекта. Сначала уточни читателей, крупные части проекта
и владельцев записи; структуру предложи под ответы, а не по универсальному шаблону.
```

Если у проекта есть одна или несколько профессиональных ролей:

```text
Проверь, что эти project-owned professional skills имеют один Git-канон,
понятные полномочия и восстанавливаются для Claude и Codex в fresh clone.
```

Потом работай как обычно. Команды запоминать не нужно: короткий `SKILL.md`
маршрутизирует агента только к нужной процедуре. Полезные контрольные запросы:

| Сказать | Что должно произойти |
|---|---|
| «что просрочено» | агент назовёт только найденные просрочки и точный охват проверки; |
| «цела ли база» | проверит ссылки, сроки, незаполненные доказательства и объём входа; |
| «проверь, не врёт ли база» | прогонит реальные контрольные вопросы в чистом контексте; |
| «перестрой базу» | сначала покажет обратимый план с Git-бэкапом; |
| «подключи Codex к проекту» | создаст один канон правил и отдельные точки входа, а не копию базы; |
| «сделай хендовер» | передаст наблюдение на проверку, а не объявит его автоматически принятым фактом. |

## Что именно тестировать в бете

Не ограничивайся зелёной установкой. Она доказывает только доставку файлов.
Хороший бета-тест даёт наблюдение из реальной работы:

1. Нашёл ли новый чат правильный канон без пересказа всей истории?
2. Заметил ли он заранее подготовленное противоречие или уверенно выбрал удобный файл?
3. Отличил ли «отправлено» от «принято», «счёт создан» от «оплачено», а дату правки от свежести знания?
4. Сохранил ли профессиональную роль, её source ladder и stop conditions в fresh clone и на обеих платформах?
5. Назвала ли проверка точный охват или выдала широкое «чисто» после неполного запуска?
6. Стала ли работа заметно дороже без измеримой пользы?

Если что-то сломалось, заполни
[beta-отчёт](https://github.com/sugestr/kb-architect/issues/new?template=beta-report.md) и приложи версию, обезличенный
контекст, точный запрос, ожидаемое и фактическое поведение. Наблюдение ценнее готового
предложения по исправлению: стандарту сейчас нужны не новые идеи, а воспроизводимые
факты эксплуатации.

## Честные ограничения

- Это исследовательский прототип с приёмочным контуром, а не объявленный универсальный стандарт.
- Встроенный `kb_lookup.py` — лексический поиск. Пустая выдача **не доказывает**, что знания нет.
- Semantic/vector retrieval можно добавить как производный индекс после измеренных промахов; ответ всё равно проверяется в исходном файле, а индекс не становится вторым каноном.
- Skill не даёт профессиональный совет, credential, доступ к аккаунту или разрешение на внешнее действие.
- Git не переносит local MCP, Keychain и ignored-секреты в облако. Каждая runtime-возможность принимается отдельно по аккаунту, scope и безопасной пробе.
- На маленькой одноразовой папке накладные расходы будут выше пользы.

## Установка

**Claude Code — через marketplace плагина:**

```text
/plugin marketplace add sugestr/kb-architect
/plugin install kb-architect@sugestr
```

Обновление: `/plugin marketplace update sugestr`.

**Codex:** скачай стабильный публичный выпуск и скопируй каталог
`plugins/kb-architect/skills/kb-architect` как управляемую копию в
`~/.codex/skills/kb-architect`. Не связывай рабочую установку симлинком с
development-checkout. Следующие обновления выполняет одна команда:

```bash
python3 ~/.codex/skills/kb-architect/scripts/kb_update.py --public --fast --do
```

После обновления начни новую задачу: уже идущая сессия не перечитывает инструкции
skill на лету.

**Cowork или обычный чат:** скачай `kb-architect.skill` из
[последнего выпуска](https://github.com/sugestr/kb-architect/releases/latest), приложи
в чат и установи с карточки файла.

Проверка установки: скажи в новом чате «объясни, что это за skill».

## Что внутри

```text
plugins/kb-architect/skills/kb-architect/
  SKILL.md               лёгкий маршрутизатор к одной нужной процедуре
  references/contract.md замороженный обязательный контракт на одной странице
  references/            опциональный справочник
  assets/templates/      вход, текущее состояние, журнал, вопросы и хендовер
  agents/openai.yaml     интерфейс skill в Codex
  scripts/kb_init.py     развернуть минимальную базу
  scripts/kb_due.py      найти просроченное
  scripts/kb_check.py    проверить целостность
  scripts/kb_lookup.py   найти известное до вывода «этого нет»
  scripts/kb_skills.py   проверить project-owned профессиональные skills
  scripts/kb_apply.py    разобрать изменения между редакциями
  scripts/kb_update.py   безопасно обновить файловые установки
```

Справочник читает агент, а не человек. Человеку достаточно этого README, короткого
`SKILL.md` и собственного решения о том, какие профессиональные роли нужны проекту.

## Версии и лицензия

Номер в `metadata.version` файла `SKILL.md` меняется при любой правке содержимого
пакета. Первая цифра меняется при изменении контракта или архитектуры обязательной
загрузки/доставки; совместимая документация и инструменты поднимают вторую. История
лежит в `references/releases.md`.

MIT. Бери, адаптируй и проверяй на своей работе. Если сломалось — расскажи как.

<!-- В plugin.json намеренно нет второго поля version. Канон версии —
     metadata.version в SKILL.md; две независимо обновляемые версии неизбежно
     разошлись бы. -->
