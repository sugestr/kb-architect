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

Report routing is deterministic: an owner-local project keeps its declared private
inbox even when the current runtime cannot write there (`BLOCKED_LOCAL`, never a
public fallback); an external/remote beta project submits an anonymised GitHub issue.
`scripts/kb_report.py` previews and executes that route.

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
| Project knowledge base | Any project-specific knowledge: facts, evidence, law, diagnoses, events, hypotheses, plans, current state and external-system instructions. The project chooses its own structure. |
| Project roles | Local Agent Skills that define how an agent uses knowledge: professional method, source hierarchy, evidence threshold, stop conditions and prohibited actions. |
| Deterministic tools | Repeatable transformations and mechanical validation. |

The default durable-project composition is `kb-architect` as knowledge and
communication infrastructure plus one or more project-owned professional roles.
A project that makes material domain judgements must declare role coverage; work
without a matching required role stops. A pure storage/transport project may instead
declare `not-applicable` with a reason, and a restructuring project may declare
`transitioning` with covered work and open gaps.

Roles are knowledge artifacts and use the same canon, version, cost, change and
recovery rules as the rest of the project; there is no second role-management
framework. `kb-architect` adds only a visible role manifest and knowledge-route
index, verifies that Claude and Codex discover the same Git-tracked source, and tests
recovery and authority boundaries. It
does **not** decide which professions your project needs, invent professional
expertise, or replace primary sources and qualified review. Multiple matching roles
load together; their conflict is preserved and escalated. One skill may implement
several named roles only when they genuinely share triggers, source hierarchy,
evidence threshold and stop conditions. Portal recipes, laws and project facts stay
in the indexed knowledge base, not in the role.

Role readiness has four separate receipts: structural validity, unforced fresh-session
runtime discovery, synthetic-first behavioural cases, and post-results owner
acceptance. It is also bound to a named quality review, exact role tree, manifest,
knowledge-index hashes and split static cost baselines. A shadow candidate does not
replace the old role early. Same-name active runtime copies are inventoried; shared
roles run from an exact pin; an all-roles scenario keeps combined cost visible.

The concise [project-role guide](plugins/kb-architect/skills/kb-architect/references/project-roles.md)
covers creation, growth, splitting, cost checks, migration and rare pinned reuse.

For a material conclusion derived from project knowledge, the core now provides a
two-phase evidence gate. It records support and challenge searches, stays red until
every candidate is reviewed, and permits only `supported`, `qualified` or `unknown`.
The matching project role still decides which topics and evidence criteria matter.

### First beta run

1. Install the stable release for the platform you will test.
2. Start a fresh chat and say: `Explain what kb-architect would change in this project and what it would leave untouched.`
3. In an existing repository, say: `Adopt this knowledge base. Inspect first and show the proposed canon, conflicts and migration plan before changing files.`
4. If the project makes professional judgements, ask: `Inventory the project roles, separate role behaviour from knowledge and tools, and check recovery for Claude and Codex. Do not migrate until I approve the report.`
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
- `KNOWLEDGE_INDEX.json` improves discovery but does not impose a universal knowledge taxonomy or become a second fact canon.
- An evidence receipt proves that the declared searches and candidate review ran; it does not make lexical matching a professional judgement.
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

When automatic updates are accepted, a fresh task runs this fast check before
project-derived work. A fresh 24-hour receipt avoids the network. After
`INSTALLED`, it reads the installed entry and current route. A long task updates
only at a safe boundary and does not pretend old prompt instructions disappeared.
Installing files does not raise a project's marker. For v6+, migration is complete
only when `KB_RELEASE_APPLICATION.json` preserves the pre-change source snapshot,
every release outcome and post-results owner acceptance.

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
- исполняемый evidence-gate для существенных выводов: подтверждения, ограничения и честный `UNKNOWN`;
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

Куда отправлять отчёт, запоминать не нужно: локальный проект сохраняет объявленный
private inbox даже при отсутствии текущего права записи (`BLOCKED_LOCAL`, не public
fallback); чужой/удалённый бета-проект отправляет обезличенный GitHub issue. Маршрут
показывает и выполняет `scripts/kb_report.py`.

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
| KB проекта | Любые знания проекта: факты, доказательства, законы, диагнозы, события, гипотезы, планы, текущее состояние и инструкции внешних систем. Структуру выбирает сам проект. |
| Проектные роли | Локальные Agent Skills о том, как агент использует знания: метод, иерархия источников, порог доказательности, остановки и запреты. |
| Скрипты и tools | Воспроизводимые преобразования и механические проверки. |

Типовая композиция длительного проекта: `kb-architect` как инфраструктура знания и
коммуникации плюс одна или несколько project-owned профессиональных ролей. Если
проект делает существенные предметные выводы, покрытие ролями обязательно; вывод без
совпавшей required-роли блокируется. Чистое хранилище/транспорт может явно объявить
`not-applicable` с причиной, перестраиваемый проект — `transitioning` с покрытой
работой и открытыми пробелами.

Это не персонажи в промпте. Роль — принадлежащий проекту и проверяемый локальный skill
о поведении агента. Она сама является элементом знания проекта и обслуживается теми
же правилами канона, version, стоимости, изменения и recovery; отдельная система
управления ролями не создаётся. Специальная дельта — видимый `PROJECT_ROLES.json`,
project-specific `KNOWLEDGE_INDEX.json`, один Git-канон и discovery для Claude/Codex.

Но он **не выбирает профессии за владельца, не сочиняет экспертизу и не заменяет
первичные источники или квалифицированную проверку**. Законы, факты дела, диагнозы и
рецепты госпорталов остаются индексируемым знанием, а не текстом роли. Все совпавшие роли загружаются
вместе; конфликт сохраняется и эскалируется. Один skill может реализовать несколько
именованных ролей только при общей иерархии источников, evidence threshold и
stop-gates; иначе роли разделяются.

Готовность роли разделяет structural validity, unforced fresh-session discovery,
synthetic-first behavior и post-results owner acceptance. Квитанция связана с named
quality review, hashes дерева/manifest/index и раздельными static cost baselines.
Shadow не становится каноном раньше времени; одноимённые active runtime copies видны;
заимствованная роль грузится из exact pin, а all-roles scenario показывает общую цену.

Короткое руководство [«Проектные роли»](plugins/kb-architect/skills/kb-architect/references/project-roles.md)
объясняет создание, рост, разделение, стоимость, миграцию и редкое pinned-заимствование.

Для существенного вывода из KB ядро даёт двухфазный evidence-gate: оно записывает
поиск подтверждений и возражений, остаётся красным до разбора каждого кандидата и
закрывается только как `supported`, `qualified` или `unknown`. Какие темы искать и
какой порог доказательности достаточен, по-прежнему определяет project role.

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
Проведи read-only опись ролей проекта. Отдели правила поведения роли от знаний и
tools, покажи knowledge routes, стоимость типовых загрузок и вопросы ко мне. Ничего
не мигрируй до моего ответа.
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
5. Нашёл ли агент существующее знание через индекс без подсказки владельца?
6. Назвала ли проверка точный охват или выдала широкое «чисто» после неполного запуска?
7. Стала ли работа заметно дороже без измеримой пользы?

Если что-то сломалось, заполни
[beta-отчёт](https://github.com/sugestr/kb-architect/issues/new?template=beta-report.md) и приложи версию, обезличенный
контекст, точный запрос, ожидаемое и фактическое поведение. Наблюдение ценнее готового
предложения по исправлению: стандарту сейчас нужны не новые идеи, а воспроизводимые
факты эксплуатации.

## Честные ограничения

- Это исследовательский прототип с приёмочным контуром, а не объявленный универсальный стандарт.
- Встроенный `kb_lookup.py` — лексический поиск. Пустая выдача **не доказывает**, что знания нет.
- `KNOWLEDGE_INDEX.json` улучшает обнаружение, но не навязывает проектам единую классификацию и не становится вторым каноном фактов.
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

Если принято автоматическое обновление, новая задача выполняет быстрый check до
project-derived работы. Свежая 24-часовая квитанция не обращается к сети. После
`INSTALLED` агент читает новый entry и нужный маршрут. Длинная сессия обновляется
только на безопасной границе и не выдаёт старый prompt за забытый.
Установка файлов не повышает marker проекта. Для v6+ миграцию закрывает только
`KB_RELEASE_APPLICATION.json`: source snapshot до записи, исход каждой редакции и
post-results приёмка владельца.

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
  scripts/kb_lookup.py   найти известное и закрыть evidence-gate до вывода
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
