#!/usr/bin/env python3
"""
kb_service.py — сервисный обход базы: когда пора и что делать.

    python3 kb_service.py due <корень>     # пора ли обслужить базу (это зовёт hook входа)
    python3 kb_service.py plan <корень>    # план обхода с цифрами проекта
    python3 kb_service.py exam <корень>    # экзамен: контрольные вопросы с чистого листа

Почему. Аудит 02.10.2026: агенты записывают сделанное, но в «кучу» — журнал изменений и
канал правок; разносить записи по местам было некому, кроме владельца; контрольные
вопросы базе не задавались неделями. Владелец 02.10: ночные задания не нужны — «хорошо
бы, чтобы какой-нибудь агент время от времени говорил: ой, пора обслужить базу, что-то
тут накопилось». Поэтому повод даёт hook входа (`due`), решает владелец («обслужи
базу»), а обход делает обычная сессия в проекте по плану (`plan`).

Счёт идёт от последнего обхода — коммита проекта, в сообщении которого есть «сервисный
обход базы» (так его и называет последний шаг плана). Пороги — по умолчанию ниже;
куда что разносить, решает карта проекта (его правила и маршруты KNOWLEDGE_INDEX):
скилл раскладку не навязывает.

Экзамен — изолированные агенты: Codex `exec --ignore-user-config` без приложений,
плагинов и MCP, только чтение (без Codex — Claude Code `-p` без пользовательских
настроек). Отвечающий видит только вопросы и копию проекта без файла контрольных
вопросов; проверяющий сверяет ответы с ожидаемыми.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_paths  # noqa: E402
import kb_turns  # noqa: E402

HOME = os.path.expanduser("~")
CODEX_APP = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
ISOLATE = ["--disable", "apps", "--disable", "plugins", "--disable", "remote_plugin",
           "--disable", "multi_agent", "--disable", "image_generation"]
MARKS = ("Сервисный обход базы", "сервисный обход базы", "СЕРВИСНЫЙ ОБХОД БАЗЫ")
# Любая явная отметка разбора: ✔/✅, [x], CLOSED, «статус: закрыт…» (проекты пишут по-разному:
# «статус CLOSED», «✔ код исправлен», «[x]»).
# «✔ Вход учтён» закрывает учёт входящего, а не предметное расхождение (capture → corrections);
# «не ✔ закрыто» — отрицание (K4, 04.10.2026).
CLOSED = re.compile(r"(?<![Нн]е )(?<![Нн]е\xa0)(?:(?:✔|✅)(?!\s*[Вв]ход\s+учт[её]н)|\[x\]|"
                    r"(?:статус|status)\W{0,3}(?:закрыт|closed|resolved|"
                    r"учтен|учтён|применен|применён|решен|решён))", re.IGNORECASE)
# Статус заглавными — «**ЗАКРЫТО.**» (tg-archive: 37 записей). Строчное «закрыт» — обычное слово
# текста («порт закрыт»), поэтому только заглавные и без «НЕ» (внешний аудит, 03.10.2026).
CLOSED_UPPER = re.compile(r"(?<!НЕ )(?<!не )\bЗАКРЫТО\b")
# «CLOSED» — пометка, только если стоит как статус: в начале строки или после «·», «—», «|», «:»
# («· CLOSED 2026-09-18:», «— **CLOSED**»); «система показывает CLOSED» — текст, не закрытие.
CLOSED_MARK = re.compile(r"(?:^|[·—|:]|\s[-–])[ \t*]*CLOSED\b", re.MULTILINE)
# Запись начинается датой: ISO или ДД.ММ.ГГГГ / ДД/ММ/ГГГГ, в том числе жирной (UAD «## 10.09.2026»,
# другой проект «- **25/09/2026»): прежде такие записи склеивались с соседними или не считались.
DATE = r"(?:\*\*)?(?:\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})"
# Запись может начинаться и голой датой после пустой строки («2026-10-03 — `id` …»):
# в tg-archive 32 такие записи счётчик не видел (сервисный обход 03.10.2026).
ENTRY = re.compile(r"\n(?=(?:- |\| |## )" + DATE + r")|(?<=\n\n)(?=" + DATE + r"(?!\d))")
ENTRY_DATE = re.compile(r"(?:- |\| |## )?(?:\*\*)?(?:(\d{4})-(\d{2})-(\d{2})|(\d{2})[./](\d{2})[./](\d{4}))")
# Отдельная запись «закрытие двух записей `A` и `B` выше» закрывает записи выше с этими
# метками (проект компании, 05.09): метка записи — первый `…` её первой строки.
LABEL = re.compile(r"`([^`\n]+)`")
CLOSES_OTHERS = re.compile(r"(?:закрыти\w*|закрыва\w*)\s+(?:\S+\s+){0,2}запис|"
                           r"closes?\s+(?:\S+\s+){0,2}entr", re.IGNORECASE)
# Пример из шаблона канала правок — не запись.
TEMPLATE_EXAMPLE = ("path/to/file.md", "утверждает X, на самом деле Y")
NOW_LIMIT = 20 * 1024
THRESHOLDS = {"open_corrections": 15, "unrecorded_turns": 10, "work_commits": 60,
              "days_with_work": 14, "exam_days": 30, "registry_days": 7}


def git(root, *args, timeout=30):
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                           timeout=timeout, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout if r.returncode == 0 else ""


def state_dir(*parts):
    base = os.environ.get("KB_ENTRY_STATE") or os.path.join(HOME, ".cache", "kb-architect", "entry")
    path = os.path.join(base, "service", *parts)
    os.makedirs(path, exist_ok=True)
    return path


def key(root):
    return hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- что накопилось

def last_service(root):
    """(дата, sha) последнего обхода: коммит этого проекта с «сервисный обход базы» в
    сообщении. Несколько написаний — git сравнивает кириллицу без учёта регистра только в
    UTF-8 локали."""
    out = git(root, "log", "-1", "-i", *[f"--grep={m}" for m in MARKS], "--format=%cs %H",
              "--", ".")
    parts = out.split()
    return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def is_git(root):
    return bool(git(root, "rev-parse", "--git-dir").strip())


def visible_corrections(text):
    """Внешний аудит 03.10.2026: скрыть цитаты и код, сохранив позиции записей. Блок без
    закрывающей метки блоком не считается: иначе он прятал бы все следующие записи (ревью 7.7.0)."""
    out, fence = [], None
    lines = text.splitlines(keepends=True)
    marks = [re.match(r"(`{3,}|~{3,})", re.sub(r"^\s*[-*]\s+", "", l).lstrip()) for l in lines]
    for i, line in enumerate(lines):
        m = marks[i]
        if fence is None and m and not any(
                n and n.group(1)[0] == m.group(1)[0] and len(n.group(1)) >= len(m.group(1))
                for n in marks[i + 1:]):
            out.append(line)                  # незакрытый «блок» — обычный текст
            continue
        value = re.sub(r"^\s*[-*]\s+", "", line).lstrip()
        mark = re.match(r"(`{3,}|~{3,})", value)
        hidden = fence is not None or value.startswith(">") or mark is not None
        if mark and not value.startswith(">"):
            if fence is None:
                fence = mark.group(1)
            elif (mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence)
                  and not value[mark.end():].strip()):
                fence = None
        if hidden:
            out.append(re.sub(r"[^\r\n]", " ", line))
        else:
            out.append(re.sub(r"(`+)(?!`).*?(?<!`)\1(?!`)",
                              lambda m: " " * len(m.group(0)), line))
    return "".join(out)


def open_corrections(root):
    """[(дата, текст)] записей канала правок без отметки разбора, новые первыми."""
    loc = kb_paths.locate(root, "corrections")
    if not loc.path:
        return []
    text = kb_paths.read(loc.path)
    # Дата внутри блока кода — пример, не запись: начала записей ищутся по видимому тексту.
    starts = sorted({0, len(text)} | {m.end() for m in ENTRY.finditer(visible_corrections(text))})
    opened = []                       # [(метка, дата, текст)] в порядке файла
    for start, end in zip(starts, starts[1:]):
        block = text[start:end]
        b = block.strip()
        m = ENTRY_DATE.match(b)
        if not m:
            continue
        first = b.splitlines()[0]
        # Цитаты и код скрываются внутри записи: незакрытый блок кода в одной записи
        # не прячет отметки всех следующих (tg-archive, 03.10.2026).
        status = visible_corrections(block)
        if (CLOSED.search(status) or CLOSED_UPPER.search(status)
                or CLOSED_MARK.search(status) or all(t in b for t in TEMPLATE_EXAMPLE)):
            if CLOSES_OTHERS.search(first):
                named = set(LABEL.findall(first))
                opened = [o for o in opened if o[0] not in named]
            continue
        label = LABEL.search(first)
        date = (f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m.group(1)
                else f"{m.group(6)}-{m.group(5)}-{m.group(4)}")
        opened.append((label.group(1) if label else None, date, b))
    return sorted(((d, b) for _, d, b in opened), key=lambda x: x[0], reverse=True)


def exam_report(root):
    try:
        with open(os.path.join(state_dir("exam"), key(root) + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def exam_age(root, questions, today):
    """Дней с последнего экзамена: отчёт этой машины или журнал прогонов в самом проекте."""
    ages = []
    report = exam_report(root)
    if report and report.get("status") == "OK":
        ages.append((today - datetime.date.fromisoformat(report["date"])).days)
    if questions:
        text = kb_paths.read(questions)
        log = text[text.find("Журнал прогонов"):] if "Журнал прогонов" in text else ""
        dates = re.findall(r"(20\d\d)-(\d\d)-(\d\d)", log)
        for y, m, d in dates:
            try:
                ages.append((today - datetime.date(int(y), int(m), int(d))).days)
            except ValueError:
                pass
    ages = [a for a in ages if a >= 0]
    return min(ages) if ages else None


def postponed(root, today):
    try:
        with open(os.path.join(state_dir("later"), key(root)), encoding="utf-8") as f:
            return today < datetime.date.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return False


def accumulated(root, today=None):
    """Что накопилось с прошлого обхода: числа и причины; «пора» — при двух основных
    причинах или одной очень большой. Экзамен — причина второго ряда: сам по себе не зовёт."""
    today = today or datetime.date.today()
    since, since_sha = last_service(root)
    days = (today - datetime.date.fromisoformat(since)).days if since else None
    corrections = open_corrections(root)
    entry = kb_paths.locate(root, "entry")
    now_size = os.path.getsize(entry.path) if entry.path else 0
    if since_sha:
        commits = git(root, "rev-list", "--count", "--no-merges", f"{since_sha}..HEAD", "--", ".")
    else:
        commits = git(root, "rev-list", "--count", "--no-merges", "--since=30.days", "HEAD", "--", ".")
    commits = int(commits.strip() or 0)
    # Внешний аудит 03.10.2026: календарный день повторно включал работу до обхода.
    service_ts = git(root, "show", "-s", "--format=%ct", since_sha).strip() if since_sha else ""
    turns = kb_turns.summary(root, days=30, whole_only=True,
                             since_epoch=int(service_ts) if service_ts else None)
    registry_days = ((time.time() - turns["first_trigger_ts"]) / 86400
                     if turns.get("first_trigger_ts") is not None else 0)
    unrecorded = turns["turns_with_work"] - turns["work_recorded"]
    questions = kb_paths.locate(root, "questions").path
    age = exam_age(root, questions, today)
    primary, secondary = [], []
    if len(corrections) >= THRESHOLDS["open_corrections"]:
        primary.append(f"ждут разнесения записей канала правок: {len(corrections)}")
    if now_size > NOW_LIMIT:
        primary.append(f"NOW {now_size // 1024} КБ: проверь, не стал ли NOW хроникой; размер сам по себе не ошибка")
    if unrecorded >= THRESHOLDS["unrecorded_turns"] and registry_days >= THRESHOLDS["registry_days"]:
        primary.append(f"ходов с работой без записи в базу: {unrecorded}")
    if commits >= THRESHOLDS["work_commits"] and (days is None or days >= THRESHOLDS["days_with_work"]):
        primary.append(f"коммитов с прошлого обхода: {commits} за {days} дн." if days is not None
                       else f"коммитов за 30 дней: {commits}, обхода ещё не было")
    if questions and (age is None or age >= THRESHOLDS["exam_days"]):
        secondary.append("экзамен базы " + (f"был {age} дн. назад" if age is not None
                                            else "ещё не проводился"))
    git_ok = is_git(root)
    due = git_ok and (len(primary) >= 2 or len(corrections) >= 3 * THRESHOLDS["open_corrections"]
                      or now_size > 2 * NOW_LIMIT)
    return {"since": since, "corrections": len(corrections), "now_bytes": now_size,
            "commits": commits, "unrecorded_turns": unrecorded, "exam_age": age,
            "has_questions": bool(questions), "git": git_ok,
            "reasons": primary + secondary, "due": bool(due)}


def due_text(root, once_a_day=False):
    """Строки для входа, если пора; иначе пусто. Hook считает раз в день на проект (подсчёт
    в большом проекте — 1–2 с) и молчит, пока владелец отложил обход (`kb_service.py later`)."""
    today = datetime.date.today()
    if postponed(root, today):
        return ""
    flag = os.path.join(state_dir("said"), f"{key(root)}-{today.isoformat()}")
    if once_a_day and os.path.exists(flag):
        return ""
    # Внешний аудит 03.10.2026: дневной успех только после расчёта; ошибка
    # разрешает повтор через час, чтобы hook не платил дорогой расчёт на каждом старте.
    retry = os.path.join(state_dir("retry"), key(root))
    if once_a_day:
        try:
            if time.time() - os.path.getmtime(retry) < 3600:
                return ""
        except OSError:
            pass
    try:
        a = accumulated(root, today)
    except Exception:
        if once_a_day:
            with open(retry, "w"):
                pass
            os.utime(retry, (time.time(), time.time()))
        raise
    if once_a_day:
        with open(flag, "w"):
            pass
        try:
            os.remove(retry)
        except FileNotFoundError:
            pass
    if not a["due"]:
        return ""
    when = f"с прошлого обхода ({a['since']})" if a["since"] else "обхода ещё не было"
    return ("Пора обслужить базу — " + when + ": " + "; ".join(a["reasons"][:4]) + ". "
            "Скажи это владельцу одной фразой в первом ответе; по его «обслужи базу» — "
            f"python3 {shlex.quote(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kb_service.py'))}"
            f" plan {shlex.quote(root)} и по шагам; «позже» — `kb_service.py later "
            f"{shlex.quote(root)} --days 7`.")


# ---------------------------------------------------------------- план обхода

# Не «работа без описания»: только тесты, картинки и документы-вложения (внешний аудит 03.10: в
# списке были коммиты одних тестов и PNG).
NOT_WORK = re.compile(r"(?:^|/)(?:tests?|__tests__)/|(?:^|/)test_[^/]+$|_test\.\w+$|"
                      r"\.(?:png|jpe?g|gif|svg|webp|ico|pdf)$", re.IGNORECASE)


def entry_line(text, block):
    """Номер строки начала записи в файле канала — адрес для обхода."""
    pos = text.find(block.splitlines()[0]) if block else -1
    return text.count("\n", 0, pos) + 1 if pos >= 0 else None


def plan(root, show_all=False):
    a = accumulated(root)
    corrections = open_corrections(root)
    _, since_sha = last_service(root)
    rng = [f"{since_sha}..HEAD"] if since_sha else ["--since=30.days", "HEAD"]
    log = git(root, "log", "--no-merges", "--relative", "--format=@@%h %s", "--name-only",
              *rng, "--", ".")
    commits, cur = [], None
    for line in log.splitlines():
        if line.startswith("@@"):
            cur = [line[2:], []]
            commits.append(cur)
        elif line.strip() and cur:
            cur[1].append(line.strip())
    try:
        import kb_check
        inbox = kb_check.inbox_dir(root)
        inbox_rel = os.path.relpath(inbox, root).rstrip("/") + "/" if inbox else None
    except Exception:
        inbox_rel = None
    know = set(kb_turns.split_knowledge(root, {p for _, ps in commits for p in ps})[0])
    undocumented = [s_ for s_, ps in commits
                    if ps and not (set(ps) & know)
                    and not all((inbox_rel and p.startswith(inbox_rel)) or NOT_WORK.search(p)
                                for p in ps)]
    scripts = os.path.dirname(os.path.abspath(__file__))
    q = shlex.quote
    print(f"# Сервисный обход базы — {os.path.basename(root)}")
    print(f"Прошлый обход: {a['since'] or 'не было'}. Причины сейчас: "
          + ("; ".join(a["reasons"]) or "порог не достигнут, обход по просьбе владельца") + ".")
    print("\nКуда что разносить, решает карта проекта: его правила и маршруты KNOWLEDGE_INDEX. "
          "Нет места для повторяющегося вида знания — предложи владельцу завести его "
          "(из справочников скилла или своё), не складывай в журнал.\n")
    print(f"## 1. Разнести накопленное ({len(corrections)} записей канала правок без отметки)")
    print("Новые первыми. Действующий факт — в его место по карте (NOW для текущего, глава для "
          "устойчивого); в записи — отметка разбора проекта («✔ учтено → <файл § раздел>»). "
          "Устаревшее — отметить учтённым со ссылкой. Спорное и требующее решения — не угадывать, "
          "собрать списком для владельца.")
    loc = kb_paths.locate(root, "corrections")
    channel = kb_paths.read(loc.path) if loc.path else ""
    name = os.path.relpath(loc.path, root) if loc.path else "канал правок"
    shown = corrections if show_all else corrections[:12]
    for _, text in shown:
        line = entry_line(channel, text)
        print(f"- {name}:{line} " + re.sub(r"\s+", " ", text)[:220 if not show_all else 160])
    if len(corrections) > len(shown):
        print(f"- … ещё {len(corrections) - len(shown)}; полный список с адресами — "
              f"`kb_service.py plan {q(root)} --all`; за один обход — столько, сколько успеешь без спешки")
    print(f"\n## 2. Работа без описания ({len(undocumented)} коммитов с прошлого обхода, "
          "показаны первые 15)")
    for s in undocumented[:15]:
        print(f"- {s[:200]}")
    print("Описать то, что изменилось в системе или решено, в месте по карте; мелочь — пропустить.")
    print("\n## 3. Починить")
    print(f"- долги знания: python3 {q(scripts + '/kb_debts.py')} {q(root)} --summary — закрыть или PENDING")
    print(f"- целостность: python3 {q(scripts + '/kb_check.py')} {q(root)} — битые ссылки, просроченное")
    print("- NOW: прошедшие сроки и устаревшие пункты — обновить")
    print("\n## 4. Экзамен")
    if a["has_questions"]:
        print(f"- python3 {q(scripts + '/kb_service.py')} exam {q(root)} — итог строкой в журнал прогонов "
              "контрольных вопросов; провал — значит знание не на месте или его нет: поправить")
    else:
        print("- контрольных вопросов нет: предложи владельцу 3–5 вопросов, которые он реально задаёт")
    print("\n## 5. Реорганизация (только с согласия владельца)")
    if a["now_bytes"] > NOW_LIMIT:
        print(f"- NOW {a['now_bytes'] // 1024} КБ: проверь, не стал ли NOW хроникой; размер сам по себе не ошибка. "
              "Если хроника — карточка (где мы, что открыто, решения, чего ждём), хронику дословно "
              "в архивный файл со ссылкой (references/service-layer.md → service_pass)")
    print("- главы больше ~100 КБ — предложить деление по смыслу; места для повторяющихся видов "
          "знания, которых нет в карте, — предложить завести")
    print("\n## 6. Отметка")
    print(f"Коммит по правилам проекта; в сообщении — «Сервисный обход базы: <что сделано>». "
          "С него начнётся новый счёт. Владельцу — итог в 3–5 строках и список «нужно решение».")
    return 0


# ---------------------------------------------------------------- экзамен

EXTRACT = """ИЗВЛЕЧЕНИЕ. Прочитай файл {rel} в этом каталоге — контрольные вопросы проекта.
Верни ТОЛЬКО JSON-массив активных контрольных вопросов (без журнала прогонов, архива и
пояснений): [{{"id": "1", "question": "…", "expected": "…"}}]. expected — ожидаемый ответ
или граница ответа и источник так, как они записаны в файле; если не записаны — "".
Ничего не меняй в файлах."""

EXAMINE = """ЭКЗАМЕН. Ты — новый агент проекта без памяти о нём. Этот каталог — копия базы
знаний проекта (файла с контрольными вопросами в нём нет). Ответь на вопросы ниже, опираясь
только на файлы этого каталога: правила, NOW, главы, реестры. Для каждого вопроса: краткий
ответ; источник — файл и раздел; уверенность — высокая, средняя или низкая. Если ответа в
файлах нет или он противоречив — так и скажи, не выдумывай и не опирайся на общие знания.
Ничего не меняй в файлах. Верни ТОЛЬКО JSON-массив:
[{{"id": "…", "answer": "…", "source": "…", "confidence": "…"}}]

Вопросы:
{questions}"""

GRADE = """ПРОВЕРКА. Сверь ответы агента без памяти с ожидаемыми ответами проекта.
PASS — ответ верен по сути и назван источник; PARTIAL — верно частично, без источника или
неуверенно там, где ответ в базе есть; FAIL — неверно, выдумано, или уверенный ответ там,
где база правильного ответа не даёт. Ничего не меняй в файлах. Верни ТОЛЬКО JSON-массив:
[{{"id": "…", "verdict": "PASS|PARTIAL|FAIL", "reason": "одна короткая фраза: что не так"}}]

Данные:
{data}"""


def agent_argv(prompt, cwd, out):
    custom = os.environ.get("KB_AGENT_CMD")
    if custom:
        return shlex.split(custom) + ["--cwd", cwd, "--out", out, prompt]
    codex = shutil.which("codex") or (CODEX_APP if os.path.exists(CODEX_APP) else None)
    if codex:
        model = os.environ.get("KB_AGENT_MODEL", "gpt-6.1-sol")
        return [codex, *ISOLATE, "exec", "--ignore-user-config", "-m", model, "-s", "read-only",
                "--skip-git-repo-check", "--ephemeral", "-C", cwd, "-o", out, prompt]
    claude = shutil.which("claude") or os.path.join(HOME, ".local", "bin", "claude")
    if os.path.exists(claude):
        return [claude, "-p", prompt, "--setting-sources", "", "--strict-mcp-config",
                "--allowedTools", "Read(./**)", "Grep(./**)", "Glob(./**)"]
    raise RuntimeError("нет агента для экзамена: ни codex, ни claude")


def isolated_home():
    """Пустой CODEX_HOME только с авторизацией: без глобальных правил и памяти владельца,
    которые указывают агенту на настоящий проект (ревью 7.6.0)."""
    home = tempfile.mkdtemp(prefix="kb-codex-home-")
    auth = os.path.join(os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex"), "auth.json")
    if os.path.exists(auth):
        shutil.copy2(auth, os.path.join(home, "auth.json"))
        os.chmod(os.path.join(home, "auth.json"), 0o600)
    return home


def run_agent(prompt, cwd, timeout=2400):
    fd, out = tempfile.mkstemp(prefix="kb-agent-", suffix=".txt")
    os.close(fd)
    home = isolated_home()
    try:
        r = subprocess.run(agent_argv(prompt, cwd, out), cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=dict(os.environ, KB_ENTRY_HOOK="off",
                                                     KB_ENTRY_UPDATE="off", CODEX_HOME=home))
        with open(out, encoding="utf-8") as f:
            text = f.read()
    finally:
        shutil.rmtree(home, ignore_errors=True)
        try:
            os.remove(out)
        except OSError:
            pass
    return text if text.strip() else r.stdout


def json_list(text):
    """Последний JSON-массив объектов в ответе агента (скобки в тексте вокруг не мешают)."""
    decoder, found = json.JSONDecoder(), []
    text = text or ""
    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            found.append(value)
    return found[-1] if found else []


def leaked(source, qname, copy):
    """Источник вне копии базы или файл с ответами. Путь внутри копии (агент часто пишет
    полный путь своего каталога) и «NOW.md / раздел» — не утечка."""
    s = str(source or "")
    for prefix in sorted({copy, os.path.realpath(copy)}, key=len, reverse=True):
        s = s.replace(prefix + os.sep, "").replace(prefix, "")
    return qname in s.lower() or bool(re.search(r"(?:^|[\s(«\"'`])~?/[\w.-]", s))


def inside(path, root):
    """Внешний аудит 03.10.2026: путь с .. или symlink не должен выйти из копии."""
    return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)


def exam(root):
    root = os.path.realpath(root)
    report = {"project": os.path.basename(root), "date": datetime.date.today().isoformat(),
              "status": "OK", "questions": 0, "pass": 0, "partial": 0, "fail": 0,
              "ungraded": 0, "items": [], "snapshot": None, "questions_dirty": False}
    loc = kb_paths.locate(root, "questions")
    declared_path = loc.path or (os.path.join(root, loc.broken) if loc.broken else None)
    if declared_path and not inside(declared_path, root):
        report.update(status="UNSAFE_QUESTIONS", reason="файл вопросов вне проекта; экзамен запрещён")
        return report
    if not is_git(root):
        report["status"] = "NOT_GIT"
        return report
    # Внешний аудит 03.10.2026: вопросы, база и проверка из одного HEAD;
    # archive SHA:prefix даёт корень вложенного проекта, без соседних проектов.
    head = git(root, "rev-parse", "HEAD").strip()
    top = git(root, "rev-parse", "--show-toplevel").strip()
    if not head or not top or not inside(root, top):
        report["status"] = "COPY_FAILED"
        return report
    report["snapshot"] = head
    if loc.path:
        report["questions_dirty"] = bool(git(root, "status", "--porcelain", "--",
                                              os.path.relpath(loc.path, root)).strip())
    prefix = os.path.relpath(root, os.path.realpath(top))
    tree = head if prefix == "." else head + ":" + prefix.replace(os.sep, "/")
    copy = os.path.realpath(tempfile.mkdtemp(prefix="kb-exam-"))
    try:
        archive = subprocess.Popen(["git", "-C", top, "archive", "--format=tar", tree],
                                   stdout=subprocess.PIPE)
        untar = subprocess.run(["tar", "-x", "-C", copy], stdin=archive.stdout, timeout=1800)
        archive.stdout.close()
        if archive.wait(timeout=60) or untar.returncode:
            report["status"] = "COPY_FAILED"
            return report
        snapshot_loc = kb_paths.locate(copy, "questions")
        hidden = snapshot_loc.path
        # Внешний аудит 03.10.2026: абсолютный адрес внутри исходного проекта
        # переводится в адрес HEAD-копии; исходный файл не читаем и не удаляем.
        declared = (snapshot_loc.declared or "").split()
        declared = declared[0].strip("«»\"'`,;") if declared else ""
        if declared and os.path.isabs(declared) and inside(declared, root):
            hidden = os.path.join(copy, os.path.relpath(declared, root))
        if not hidden:
            report["status"] = "NO_QUESTIONS_IN_HEAD" if loc.path else "NO_QUESTIONS"
            return report
        if not inside(hidden, copy):
            report.update(status="UNSAFE_QUESTIONS", reason="файл вопросов вне временной копии; экзамен запрещён")
            return report
        if not os.path.isfile(hidden):
            report["status"] = "NO_QUESTIONS_IN_HEAD"
            return report
        # Относительный alias не должен оставить ответы в его физическом файле.
        hidden = os.path.realpath(hidden)
        rel = os.path.relpath(hidden, copy)
        report["questions_dirty"] = report["questions_dirty"] or bool(
            git(root, "status", "--porcelain", "--", rel).strip())
        questions = [q for q in json_list(run_agent(EXTRACT.format(rel=rel), copy))
                     if isinstance(q, dict) and q.get("question")][:20]
        for n, q in enumerate(questions, 1):
            q["id"] = str(n)                  # номера модели повторяются по разделам
        if not questions:
            report["status"] = "EXTRACT_FAILED"
            return report
        # Повторная проверка непосредственно перед удалением защищает и от symlink.
        if not inside(hidden, copy):
            report.update(status="UNSAFE_QUESTIONS", reason="файл вопросов вне временной копии; удаление запрещено")
            return report
        os.remove(hidden)
        asked = [{"id": str(q.get("id")), "question": q["question"]} for q in questions]
        answers = json_list(run_agent(EXAMINE.format(
            questions=json.dumps(asked, ensure_ascii=False, indent=1)), copy))
        by_id = {str(a.get("id")): a for a in answers if isinstance(a, dict)}
        data = [{"id": str(q.get("id")), "question": q["question"], "expected": q.get("expected", ""),
                 "answer": by_id.get(str(q.get("id")), {}).get("answer", "(нет ответа)"),
                 "source": by_id.get(str(q.get("id")), {}).get("source", "")} for q in questions]
        verdicts = {str(v.get("id")): v for v in json_list(run_agent(
            GRADE.format(data=json.dumps(data, ensure_ascii=False, indent=1)), copy))
            if isinstance(v, dict)}
    finally:
        shutil.rmtree(copy, ignore_errors=True)
    qname = os.path.basename(rel).lower()
    for d in data:
        v = verdicts.get(d["id"], {})
        verdict = str(v.get("verdict", "")).upper()
        verdict = verdict if verdict in ("PASS", "PARTIAL", "FAIL") else "UNGRADED"
        if leaked(d.get("source", ""), qname, copy):
            verdict, v = "FAIL", {"reason": "источник вне копии базы или файл с ответами — "
                                            "ответ не засчитан"}
        d.update({"verdict": verdict, "reason": str(v.get("reason", ""))[:300]})
        report[verdict.lower()] += 1
    report["questions"] = len(data)
    report["items"] = data
    if not by_id or report["ungraded"] == len(data):
        report["status"] = "EXAM_FAILED"      # агент не ответил или не оценил — не «экзамен сдан»
        return report
    with open(os.path.join(state_dir("exam"), key(root) + ".json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report


def print_exam(report):
    print(f"ЭКЗАМЕН {report['project']} {report['date']}: {report['status']}; вопросов "
          f"{report['questions']}: верно {report['pass']}, частично {report['partial']}, "
          f"неверно {report['fail']}" + (f", без оценки {report['ungraded']}" if report['ungraded'] else ""))
    if report.get("snapshot"):
        print("Снимок экзамена: HEAD " + report["snapshot"])
    if report.get("questions_dirty"):
        print("Вопросы имеют незакоммиченные изменения; экзамен использует только HEAD.")
    if report.get("reason"):
        print(report["reason"])
    for item in report.get("items", []):
        if item["verdict"] != "PASS":
            print(f"- {item['id']} {item['verdict']}: {item['question'][:120]} — {item['reason']}")
    if report["status"] == "OK":
        print("Строку итога — в журнал прогонов контрольных вопросов; провалы — поправить место "
              "знания или завести его.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=("due", "plan", "exam", "later"))
    parser.add_argument("root")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--all", action="store_true", help="plan: все записи канала правок с адресами")
    args = parser.parse_args()
    root = os.path.realpath(args.root)
    if args.cmd == "later":
        until = datetime.date.today() + datetime.timedelta(days=max(1, args.days))
        with open(os.path.join(state_dir("later"), key(root)), "w", encoding="utf-8") as f:
            f.write(until.isoformat())
        print(f"SERVICE_LATER: напоминание об обходе {os.path.basename(root)} — после {until}")
        return 0
    if args.cmd == "due":
        a = accumulated(root)
        if args.json:
            print(json.dumps(a, ensure_ascii=False))
        elif a["due"] and postponed(root, datetime.date.today()):
            print("SERVICE_LATER: владелец отложил обход; накопилось: " + "; ".join(a["reasons"]))
        else:
            print(("SERVICE_DUE: " + due_text(root)) if a["due"] else
                  "SERVICE_OK: " + ("; ".join(a["reasons"]) or "накопленного немного"))
        return 0
    if args.cmd == "plan":
        return plan(root, show_all=args.all)
    report = exam(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print_exam(report)
    return 0 if report["status"] in ("OK", "NO_QUESTIONS") else 1


if __name__ == "__main__":
    sys.exit(main())
