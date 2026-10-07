# kb-architect

[Русский](#русский) · [English](#english)

**Навык для Claude Code и Codex, который ведёт базу знаний проекта: новый чат продолжает
работу без пересказа, решения и факты не теряются, а база не обманывает уверенным тоном.**

**A skill for Claude Code and Codex that keeps a project's knowledge base: a new chat picks up
the work without a recap, decisions and facts are not lost, and the base does not mislead
with confident but stale answers.**

> Agent Skill · обычные файлы в Git, без сервера и базы данных · Claude Code и Codex ·
> бета, используется в живых проектах · MIT

---

## Русский

### Что это

`kb-architect` — набор правил и небольших скриптов, который превращает файлы вашего проекта
в базу знаний с понятным устройством: где лежит текущее состояние, где решения, где
источники, куда записывать новое и как проверять, что база не устарела.

Всё хранится в обычных файлах репозитория проекта. Отдельный сервер, векторная база или
платный сервис памяти не нужны. Правила одинаково работают для Claude Code и Codex, поэтому
оба агента ведут один проект, а не две его копии.

### Какие проблемы решает

| Проблема | Что делает kb-architect |
|---|---|
| Каждый новый чат приходится вводить в курс дела заново | В начале сессии среда сама собирает «вход»: правила проекта, текущее состояние и нужную роль. Пока агент его не прочитал, менять файлы он не может |
| Решения и находки остаются в чате, в рабочих заметках или в памяти агента | Правило «записывай в том же шаге» и команда **«закрой сессию»**: агент восстанавливает всю сессию по журналу и вносит пропущенное |
| База уверенно отвечает устаревшим: два «текущих» файла, прошедшие сроки, противоречия | Один источник текущего состояния, сроки годности у утверждений, проверка целостности; на противоречии агент останавливается, а не выбирает удобный файл |
| Агент работает «вообще», без профессионального метода | Роли проекта (юрист, бухгалтер, разработчик и другие) подключаются по задаче; скилл не выдумывает экспертизу, роли пишет и принимает владелец |
| Несколько сессий и агентов мешают друг другу | Один канон, правила передачи работы, сообщения между проектами с подтверждением доставки |
| База со временем зарастает | Сам подскажет «пора обслужить базу» и по команде **«обслужи базу»** разнесёт накопленное |

### Как начать

1. **Установите** скилл (см. [Установка](#установка)).
2. **Откройте свой живой проект** и скажите одно из двух:
   - если файлы уже есть — `Присоедини kb-architect к этому проекту. Сначала только осмотр и план, ничего не меняй без моего согласия.`
   - если проект новый — `Заведи базу знаний этого проекта.`

   Первый проход только осматривает и предлагает план. Файлы меняются после вашего «да», с
   резервной копией в Git.
3. **Дальше работайте как обычно.** Команды запоминать не нужно; несколько коротких фраз
   помогают в нужный момент:

| Сказать | Что произойдёт |
|---|---|
| «закрой сессию» | агент сверит всю сессию с базой, внесёт пропущенное, закоммитит и коротко отчитается |
| «обслужи базу» | разнесёт накопившиеся записи, обновит текущее состояние, проверит базу контрольными вопросами |
| «обновись» | подтянет проект до новой версии скилла |
| «что просрочено» | назовёт прошедшие сроки и устаревшие утверждения |
| «цела ли база» | проверит ссылки, сроки, незаполненные доказательства и объём входа |
| «перестрой базу» | сначала покажет обратимый план с резервной копией |
| «сделай хендовер» | подготовит передачу работы другой сессии или агенту |

### Установка

**Claude Code — через marketplace плагина:**

```text
/plugin marketplace add sugestr/kb-architect
/plugin install kb-architect@sugestr
```

Обновление: `/plugin marketplace update sugestr`.

**Codex:** скачайте [последний выпуск](https://github.com/sugestr/kb-architect/releases/latest)
и скопируйте папку `plugins/kb-architect/skills/kb-architect` в `~/.codex/skills/kb-architect`.

**Включите вход в проект — один раз на машину** (это и даёт «чат без пересказа»):

```bash
python3 <папка скилла>/scripts/kb_start.py install --agent claude
python3 <папка скилла>/scripts/kb_start.py install --agent codex
```

В Codex новый hook нужно один раз одобрить в настройках («Review hooks»). Файловая установка
после этого сама проверяет обновления в начале сессии.

**Обычный чат или Cowork:** скачайте `kb-architect.skill` из
[последнего выпуска](https://github.com/sugestr/kb-architect/releases/latest), приложите к
чату и установите с карточки файла.

Проверка: в новом чате скажите «объясни, что это за skill».

### Что внутри

```text
plugins/kb-architect/skills/kb-architect/
  SKILL.md            ядро: обязательные правила и маршрут к нужной процедуре
  references/         процедуры; агент читает только нужную под задачу
  assets/templates/   шаблоны для новой базы
  scripts/            проверки и служебные шаги:
    kb_start.py         вход в проект в начале сессии
    kb_session.py       «закрой сессию»: что сессия сделала и узнала
    kb_service.py       «обслужи базу» и экзамен базы
    kb_check.py         целостность: ссылки, сроки, доказательства
    kb_debts.py         работа, не дошедшая до базы
    kb_due.py           просроченное
    kb_update.py        безопасное обновление установки
```

Справочник читает агент. Человеку достаточно этого описания и решения, какие
профессиональные роли нужны проекту.

### Честные ограничения

- Скилл не даёт профессиональных советов, доступов и разрешений на внешние действия; роли и
  решения остаются за владельцем.
- Поиск по базе текстовый: пустой результат не доказывает, что знания нет.
- Для маленькой одноразовой папки накладные расходы больше пользы.
- Это бета: правила проверяются тестами и на живых проектах автора, но не объявлены стандартом.

### Обратная связь

Сломалось или пользы не видно — заполните
[отчёт](https://github.com/sugestr/kb-architect/issues/new?template=beta-report.md): версия,
точный запрос, что ожидали и что произошло. Уберите личные данные и пароли. История версий —
[`references/releases.md`](plugins/kb-architect/skills/kb-architect/references/releases.md).

---

## English

### What it is

`kb-architect` is a set of rules and small scripts that turns a project's files into a
knowledge base with a clear layout: where the current state lives, where decisions and
sources are, where new knowledge goes, and how to check that the base is not stale. It is
plain files in the project's Git repository — no server, no vector database. Claude Code and
Codex follow the same rules, so both work on one project instead of two copies. The rules and
references are written in Russian; the agent reads them, you do not have to.

### Problems it solves

- **Every new chat needs a recap.** At session start the environment assembles the entry —
  project rules, current state, the matching role — and blocks edits until the agent has read it.
- **Knowledge stays in chats, scratch notes or agent memory.** Record-as-you-go rules plus the
  command «закрой сессию» (close the session): the agent rebuilds the whole session from its
  journal and records what was missed.
- **The base answers confidently with stale facts.** One source for current state, expiry
  dates on claims, integrity checks, and a stop on contradictions.
- **The agent works without a professional method.** Project roles (lawyer, accountant,
  developer, …) load per task; the skill never invents expertise.
- **Several sessions and agents get in each other's way.** One canon, handoff rules, and
  cross-project messages with delivery receipts.
- **The base grows cluttered.** It says when maintenance is due and runs it on «обслужи базу».

### Getting started

1. Install (below).
2. In a real project say `Adopt kb-architect for this project. Inspect and propose a plan first;
   change nothing until I approve.` — or, for a new project, `Set up the knowledge base for this
   project.` The first pass is read-only; changes follow your approval with a Git backup.
3. Work as usual. Short commands: «закрой сессию» (close the session), «обслужи базу» (maintain
   the base), «обновись» (update the project to the new skill version), «что просрочено» (what
   is overdue), «цела ли база» (integrity check).

### Installation

Claude Code: `/plugin marketplace add sugestr/kb-architect`, then
`/plugin install kb-architect@sugestr`. Codex: copy `plugins/kb-architect/skills/kb-architect`
from the [latest release](https://github.com/sugestr/kb-architect/releases/latest) to
`~/.codex/skills/kb-architect`. Enable the session entry once per machine:
`python3 <skill folder>/scripts/kb_start.py install --agent claude` (and `--agent codex`, then
approve the hook in Codex). In a regular chat, attach `kb-architect.skill` from the latest release.

### Limits

No professional advice, credentials or permission for external actions; text search, so an
empty result does not prove absence; overkill for a tiny one-off folder; beta.

Feedback: [open a report](https://github.com/sugestr/kb-architect/issues/new?template=beta-report.md).
MIT.

<!-- plugin.json intentionally has no second version field. The version canon is
     metadata.version in SKILL.md; two independently updated versions would drift. -->
