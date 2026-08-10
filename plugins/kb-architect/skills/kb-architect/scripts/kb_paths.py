#!/usr/bin/env python3
"""
kb_paths.py — где у проекта вход, журнал и контрольные вопросы.

Общий поиск для kb_due.py и kb_check.py.

Почему отдельным модулем. Каждый скрипт искал вход своим списком имён и
только в корне — два источника правды об одном факте, ровно то, что
запрещает первое правило контракта. Счёт пришёл с проекта, у которого вход
лежит в подпапке: kb_check.py файла не нашёл, пропустил проверку потолка
и напечатал «чисто», а kb_due.py отнёс это в «в порядке». Вход при этом
был превышен в 1.8 раза и рос дальше.

Порядок поиска — по убыванию надёжности:

  1. Объявление в правилах проекта: строка «вход: <путь>» в блоке
     «Соответствие». Проект и так обязан там называть, чем реализован
     инвариант, — новых обязательств не вводится.
  2. Известные имена в корне.
  3. Они же на два уровня вглубь.
  4. Раздел с подходящим заголовком внутри файла правил: журнал и вопросы
     часто ведут прямо там, и справочник сам это предлагает.
  5. Не найдено — ОТДЕЛЬНЫЙ исход, а не «всё в порядке».

Пункт 5 — главное здесь. Любой поиск когда-нибудь промахнётся; дефект не
в промахе, а в том, что при промахе инструмент печатает «чисто».
Отсутствие проверки внешне неотличимо от пройденной — это fail-open, тот
самый класс, за который контракт изъял у себя четвёртое поле. Поэтому
«не найдено» возвращается отдельным значением, и вызывающий обязан его
различить: расширение поиска чинит случай, различение исходов чинит класс.
"""

import os
import re

RULES_NAMES = ("CLAUDE.md", "AGENTS.md", "ПРАВИЛА.md")

# Документы, в которых имеет смысл искать объявления и разделы. Набор узкий
# намеренно: широкий поиск по всей базе нашёл бы заголовок «Журнал
# эксплуатации» в отчёте о дефекте и в чужой цитате, а ложная тревога
# обходится дороже, чем кажется — после второй раздел перестают читать.
KB_NAMES = ("KB.md", "КБ.md", "KNOWLEDGE.md")

SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "_raw", "_work",
             "archive", "архив", "Archive", "dist", "build", "vendor"}

KINDS = {
    "entry": {
        "что": "вход",
        "names": ("NOW.md", "STATUS.md", "СЕЙЧАС.md"),
        "keys": ("вход", "entry"),
        "headings": ("СЕЙЧАС", "ТЕКУЩЕЕ СОСТОЯНИЕ"),
    },
    "journal": {
        "что": "журнал эксплуатации",
        "names": ("SLOMALOS.md", "СЛОМАЛОСЬ.md", "JOURNAL.md"),
        "keys": ("журнал", "journal"),
        "headings": ("ЖУРНАЛ ЭКСПЛУАТАЦИИ", "ЖУРНАЛ"),
    },
    "corrections": {
        "что": "канал правок",
        "names": ("CORRECTIONS.md", "ПРАВКИ.md"),
        "keys": ("канал правок", "corrections"),
        "headings": ("КАНАЛ ПРАВОК", "CORRECTIONS"),
    },
    "questions": {
        "что": "контрольные вопросы",
        "names": ("QUESTIONS.md", "ВОПРОСЫ.md"),
        "keys": ("контрольные вопросы", "вопросы", "questions"),
        "headings": ("КОНТРОЛЬНЫЕ ВОПРОСЫ",),
    },
}


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def rules_path(root):
    for n in RULES_NAMES:
        p = os.path.join(root, n)
        if os.path.isfile(p):
            return p
    return None


def context_docs(root):
    """Где проект объявляет свои соглашения — по убыванию вероятности.

    Не только файл правил. На живом проекте `kb_standard_version` оказался
    в шапке входа, а журнал — разделом в `docs/KB.md`; искать объявления
    в одном CLAUDE.md значит снова не найти то, что есть."""
    root = os.path.abspath(root)
    out = []
    rp = rules_path(root)
    if rp:
        out.append(rp)
    out.extend(by_name(root, KB_NAMES))
    out.extend(by_name(root, KINDS["entry"]["names"]))
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def declared_value(root, keys, docs=None):
    """Значение строки «<ключ>: <значение>» из документов соглашений.

    Незаполненный плейсхолдер шаблона (`<версия>`) значением не считается:
    иначе шаблон отчитается за проект, который его не заполнял.
    Возвращает (значение, где нашли) либо (None, None)."""
    # Разметка вокруг объявления допускается: живые проекты пишут строку
    # маркером списка, в обратных кавычках, полужирным. Строгий разбор «ключ
    # с начала строки» один раз уже соврал «редакция не записана» о записанной
    # редакции — оформление не должно решать, видит ли инструмент факт.
    for path in (docs if docs is not None else context_docs(root)):
        text = read(path)
        for key in keys:
            m = re.search(r"^[ \t]*(?:[-*>+][ \t]*)?[`*_\"']{0,2}[ \t]*"
                          + re.escape(key) + r"[`*_\"']{0,2}[ \t]*:[ \t]*(.+)$",
                          text, re.IGNORECASE | re.MULTILINE)
            if m:
                val = m.group(1).strip().strip("`*_ ").strip()
                if val and not val.startswith("<"):
                    return val, path
    return None, None


def section(text, headings):
    """Раздел от заголовка до следующего заголовка того же или высшего уровня.

    Возвращает пустую строку, если раздел есть, но пуст, и None, если
    заголовка нет вовсе. Различие несущее: пустой журнал — это «не
    наблюдали», отсутствующий — «разбирать будет нечего»."""
    level, out = None, []
    for ln in text.splitlines():
        m = re.match(r"^(#{1,6})[ \t]+(.*)$", ln)
        if m:
            if level is None:
                if any(h.upper() in m.group(2).upper() for h in headings):
                    level = len(m.group(1))
                continue
            if len(m.group(1)) <= level:
                break
            out.append(ln)
            continue
        if level is not None:
            out.append(ln)
    if level is None:
        return None
    return "\n".join(out).strip()


def by_name(root, names, max_depth=2):
    """Известные имена в корне и на два уровня вглубь, ближние первыми."""
    root = os.path.abspath(root)
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = ([] if depth >= max_depth else
                       [d for d in dirnames
                        if d not in SKIP_DIRS and not d.startswith(".")])
        for i, n in enumerate(names):
            if n in filenames:
                hits.append((depth, i, os.path.join(dirpath, n)))
    hits.sort()
    return [h[2] for h in hits]


class Located:
    """Четыре исхода поиска, а не два.

    path     — нашёлся файл
    section  — ведётся разделом внутри файла правил (может быть пустым)
    declared — объявлен в правилах, но не файлом: запрос, панель, генератор
    ничего  — не найден; проверять нечего, и об этом надо сказать вслух
    """

    def __init__(self, kind, path=None, section=None, how=None,
                 declared=None, others=(), broken=None):
        self.kind = kind
        self.path = path
        self.section = section
        self.how = how
        self.declared = declared
        self.others = list(others)
        self.broken = broken   # объявленный путь, которого нет

    @property
    def found(self):
        return self.path is not None or self.section is not None

    def text(self):
        if self.path:
            return read(self.path)
        return self.section or ""

    def size(self):
        """Байты. Строка в плотном markdown с таблицами — не единица объёма."""
        if self.path:
            try:
                return os.path.getsize(self.path)
            except OSError:
                return None
        if self.section is not None:
            return len(self.section.encode("utf-8"))
        return None

    def where(self, root=None):
        if self.path:
            return os.path.relpath(self.path, root) if root else self.path
        if self.section is not None:
            return self.how or "раздел внутри файла правил"
        if self.declared:
            return f"объявлен не файлом: «{self.declared}»"
        return None


def find_section(root, headings, docs=None):
    """Раздел с таким заголовком в документах соглашений: (текст, где)."""
    for path in (docs if docs is not None else context_docs(root)):
        sec = section(read(path), headings)
        if sec is not None:
            return sec, path
    return None, None


def locate(root, kind):
    spec = KINDS[kind]
    root = os.path.abspath(root)
    docs = context_docs(root)

    # Кандидаты по именам считаются ВСЕГДА, даже когда есть объявление.
    # Ранний возврат на объявлении прятал второй вход: объявили `NOW.md`,
    # рядом лежит `STATUS.md`, дубль не находился. Инвариант входа — один,
    # и проверять это надо независимо от того, что записано в правилах.
    files = by_name(root, spec["names"])

    raw, _ = declared_value(root, spec["keys"], docs)
    if raw:
        token = raw.split()[0].strip("«»\"'`,;")
        cand = os.path.join(root, token)
        if os.path.isfile(cand):
            extra = [f for f in files if os.path.abspath(f) != os.path.abspath(cand)]
            return Located(kind, path=cand, others=extra,
                           how="объявлен в правилах проекта", declared=raw)
        sec, where = find_section(root, spec["headings"], docs)
        if sec is not None:
            return Located(kind, section=sec, declared=raw,
                           how=f"раздел внутри {os.path.relpath(where, root)}")
        # Объявление, похожее на путь, но никуда не ведущее, — это опечатка,
        # а не «вычисляемый вход». Разница решающая: во втором случае
        # проверка объёма законно не применяется, в первом она молча
        # отключается опиской. Так fail-open вернулся через дверь,
        # построенную для честных исключений.
        looks_like_path = ("/" in token or token.lower().endswith(
            (".md", ".txt", ".yml", ".yaml", ".json")))
        if looks_like_path:
            return Located(kind, declared=raw, broken=token, others=files,
                           how="объявлен путём, которого нет")
        return Located(kind, declared=raw, how="объявлен не файлом")

    if files:
        in_root = os.path.dirname(files[0]) == root
        return Located(kind, path=files[0], others=files[1:],
                       how="найден по имени в корне" if in_root
                           else "найден по имени в подпапке")

    sec, where = find_section(root, spec["headings"], docs)
    if sec is not None:
        return Located(kind, section=sec,
                       how=f"раздел внутри {os.path.relpath(where, root)}")

    return Located(kind)


ABSENT = ("нет", "не ведётся", "не ведется", "отсутствует", "не заводим",
          "не заведён", "не заведен", "none", "no")


def declared_absent(raw):
    """Объявленное отсутствие — это ответ, а не молчание.

    Контракт разрешает не брать элемент, если отказ объявлен. Тогда
    напоминать о нём каждую сессию значит превращать раздел «ПОРА»
    в шум: после второй ложной тревоги его перестают читать. Разница
    между «журнала нет» и «журнал не заводим, вот почему» — вся."""
    if not raw:
        return False
    head = raw.strip().lower().lstrip("«\"'")
    return any(head.startswith(w) for w in ABSENT)


def how_to_declare(kind):
    """Что сказать человеку, когда не нашли. Без этого текста находка
    «не найдено» превращается в упрёк без адреса действия."""
    spec = KINDS[kind]
    return (f"Искали {', '.join(spec['names'])} в корне и на два уровня вглубь, "
            f"и раздел «{spec['headings'][0].capitalize()}» в файле правил. "
            f"Есть — впиши в правила проекта строку «{spec['keys'][0]}: <путь>»; "
            f"нет — это отступление, и его тоже пишут в «Соответствие»")


def project_version(root):
    """Редакция контракта, по которой живёт проект: (номер, как записано).

    Номер отделён от записи намеренно. На живом проекте поле было заполнено
    фразой «редакция от 2026-08-02 (три поля, четыре правила…)» — человеку
    понятно, сравнить нельзя. Поле, которое нельзя сравнить, не отличается
    от незаполненного, и сказать об этом должен инструмент, а не следующая
    поломка."""
    raw, _ = declared_value(root, ("kb_standard_version",))
    if not raw:
        return None, None
    m = re.search(r"\d+\.\d+", raw)
    return (m.group(0) if m else None), raw


def skill_version():
    """Редакция установленного скилла — из шапки SKILL.md рядом со скриптами."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "SKILL.md")
    m = re.search(r'^\s*version:\s*"?([0-9][0-9.]*)"?', read(p), re.MULTILINE)
    return m.group(1) if m else None


def published_version():
    """Что лежит в источнике скилла, если он установлен из репозитория.

    Три редакции расходятся независимо: загруженная в сессию, установленная
    на диске и опубликованная в источнике. Первую отсюда не видно никогда,
    вторую читает skill_version(), третью — эта функция.

    Сети не требует: если установка сделана симлинком в git-репозиторий,
    источник спрашивается локально. Установлен файлом — вернётся None,
    и это говорится вслух, а не подменяется молчанием.

    Возвращает тройку (версия, отставание, почему_неизвестно). Отставание
    None означает **не спросили**, а не ноль: пока сюда не добавили fetch,
    сравнение шло с последним скачанным состоянием, и давно не обновлявшаяся
    установка уверенно печатала «новее ничего не опубликовано». Восьмой
    случай того же класса — отсутствие проверки, неотличимое от пройденной.
    """
    import subprocess
    d = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    try:
        top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        if top.returncode != 0:
            return None, None, "установка не из репозитория"
        up = subprocess.run(["git", "-C", d, "rev-parse", "--abbrev-ref", "@{u}"],
                            capture_output=True, text=True, timeout=10)
        if up.returncode != 0:
            return skill_version(), None, "у клона нет upstream — сравнивать не с чем"
        # Без fetch сравнение идёт с последним скачанным состоянием, то есть
        # отвечает на вопрос «что я видел в прошлый раз», притворяясь ответом
        # на «что вышло». Сеть может быть недоступна — тогда так и говорим.
        f = subprocess.run(["git", "-C", d, "fetch", "--quiet"],
                           capture_output=True, text=True, timeout=45)
        if f.returncode != 0:
            why = (f.stderr.strip().splitlines() or ["нет связи с источником"])[0]
            return skill_version(), None, f"источник не опрошен: {why}"
        behind = subprocess.run(["git", "-C", d, "rev-list", "--count", "HEAD..@{u}"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        if not behind.isdigit():
            return skill_version(), None, "не удалось посчитать отставание"
        return skill_version(), int(behind), None
    except Exception as e:
        return None, None, f"источник не опрошен: {e}"


def pull_skill():
    """Подтянуть источник скилла — только вперёд и только на чистом дереве.

    Обновление кода и применение редакции к базе — разные действия.
    Здесь делается первое; второе делает сессия по таблице выпусков,
    и вслух говорится, что загруженные инструкции не перечитаются:
    обещать горячую перезагрузку нельзя, её нет.

    Возвращает (было, стало) при успехе, иначе (None, причина).
    """
    import subprocess
    d = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    before = skill_version()
    try:
        dirty = subprocess.run(["git", "-C", d, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=15).stdout.strip()
        if dirty:
            return None, "в рабочем дереве источника есть незакоммиченные правки"
        r = subprocess.run(["git", "-C", d, "pull", "--ff-only"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None, (r.stderr.strip().splitlines() or ["pull не прошёл"])[0]
        return before, skill_version()
    except Exception as e:
        return None, f"не удалось: {e}"
