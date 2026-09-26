#!/usr/bin/env python3
"""
kb_debts.py — долги знания: работа, которая уже случилась, а в базу не дошла.

    python3 kb_debts.py <корень базы> [--json | --summary] [--area <путь>]
    python3 kb_debts.py --sweep <каталог проектов> [--json]

Остальные проверки сверяют базу саму с собой: ссылки, дороги, поля. База
может пройти их все и при этом быть пустой там, где идёт основная работа.
26.09.2026 это выяснилось на двух проектах сразу. В программном продукте
на Odoo шла обширная разработка, а каждый следующий чат начинал
с исследования кода — описания кода не было или оно отстало. В
управленческом проекте (UAD) пакеты специалистов неделями лежали «принятыми»
в инбоксе, работа супервизоров оставалась в ветках и worktree, а файлы о
настоящем устаревали молча. Все проверки говорили «чисто»; владелец заметил
случайно.

Здесь база сверяется с потоками работы — с тем, что можно посчитать по
Git и файлам, без заявлений сессии:

  входящие   agent-message адресовано проекту, а его message_id или имя
             файла не упомянуты нигде вне конвертов: ни в каноне, ни в
             реестре разбора. Внесение с провенансом оставляет след само.
  работа     linked worktree с незакоммиченным или невлитым; ветки с
             уникальными коммитами старше порога. Обрыв сессии не стирает
             работу — он её прячет.
  код        модуль (каталог с manifest или верхний каталог исходников) без
             описания; описание, отставшее от кода на N коммитов модуля.
  поток      за окно код меняется, а знание не растёт.
  свежесть   файл о настоящем с observed_at старше порога: «свежесть UNKNOWN»
             честна, но должна быть видна.

Это не проверка целостности: exit 0 означает сформированный отчёт. Долг —
не ошибка, а обязанность с адресом: закрывается внесением, явным отказом
с причиной либо объявленным исключением. Пороги объявляет проект строками
в правилах; значения по умолчанию названы в отчёте.
"""

import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_check
import kb_index
import kb_paths

# Параллельные писатели — норма (UAD 26.09: 20 worktree, в основном checkout
# шло слияние). Диагностика не берёт необязательных index.lock в чужих деревьях.
# Внутри git hook окружение указывает на индекс текущего дерева; с ним
# `git -C <другой worktree> status` падает, и чужая работа выглядела чистой
# (ревью 7.3.0). Переменные репозитория снимаются, решает `-C`.
GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX",
                        "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")}
GIT_ENV.update(GIT_OPTIONAL_LOCKS="0", LC_ALL="C")

DEFAULTS = {
    "inbound_grace_days": 3,
    "work_stale_days": 3,
    "dirty_idle_hours": 6,
    "code_lag_commits": 10,
    "flow_window_days": 30,
    "flow_min_code_commits": 10,
    "freshness_days": 14,
}
DECLARED = {
    "inbound_grace_days": ("срок внесения входящих", "inbound grace days"),
    "work_stale_days": ("срок невлитой работы", "unmerged work days"),
    "dirty_idle_hours": ("срок незакоммиченного в часах", "uncommitted idle hours"),
    "code_lag_commits": ("отставание описания кода", "code description lag"),
    "freshness_days": ("срок свежести знания", "freshness days"),
}
CODE_ALLOWED_KEYS = ("код без описания допустим", "undocumented code allowed")

MANIFESTS = {"__manifest__.py", "__openerp__.py", "package.json", "pyproject.toml",
             "setup.py", "Cargo.toml", "go.mod", "composer.json", "pom.xml",
             "build.gradle", "build.gradle.kts", "Gemfile", "mix.exs", "Package.swift"}
SOURCE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
              ".go", ".rs", ".java", ".kt", ".kts", ".swift", ".rb", ".php", ".cs",
              ".c", ".h", ".cpp", ".hpp", ".sh", ".bash", ".sql", ".scala", ".ex", ".exs"}
DOC_EXT = {".md", ".markdown", ".rst", ".adoc"}
# Чужой код не описывается проектом: его описание — у автора.
VENDORED = re.compile(r"(^|/)(vendor|third_party|third-party|external|node_modules|"
                      r"site-packages|\.venv|venv|dist|build)(/|$)")
OBSERVED = re.compile(r"^\s*[-*>]?\s*[`*_]*observed_at[`*_]*\s*:\s*(\S+)", re.MULTILINE)
VALID_UNTIL = re.compile(r"^\s*[-*>]?\s*[`*_]*valid_until[`*_]*\s*:", re.MULTILINE)
CREATED = re.compile(r"^\s*created_at\s*:\s*[\"']?(\d{4}-\d{2}-\d{2})", re.MULTILINE)
MESSAGE_ID = re.compile(r"^\s*message_id\s*:\s*[\"']?([^\"'\s]+)", re.MULTILINE)
SENDER = re.compile(r"^\s*(?:from_megamozg|from_project|from)\s*:\s*(.+)$", re.MULTILINE)
ISO_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def git(root, *args, timeout=30):
    """Вывод git или None. None нигде не читается как «пусто»."""
    try:
        # Не-ASCII путь в log печатается в кавычках и escape, в ls-files -z —
        # как есть; без core.quotePath=false они не совпадали (ревью 7.3.0).
        r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), *args],
                           capture_output=True,
                           text=True, timeout=timeout, env=GIT_ENV)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def as_date(value):
    m = ISO_DATE.search(value or "")
    if not m:
        import kb_dates
        got, _ = kb_dates.parse_dates(value or "", day_first=True)
        return got[0] if got else None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def thresholds(root):
    out = dict(DEFAULTS)
    for key, names in DECLARED.items():
        raw, _ = kb_paths.declared_value(root, names)
        if raw and re.match(r"^\d+", raw):
            out[key] = int(re.match(r"^\d+", raw).group(0))
    return out


def tracked(root):
    raw = git(root, "ls-files", "-z")
    if raw is None:
        return None
    return [p for p in raw.split("\0") if p]


def read(root, rel, limit=None):
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="ignore") as f:
            return f.read(limit) if limit else f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------- входящие

def envelopes(root):
    """Входящие agent-message этого проекта: [(rel, message_id, дата, отправитель)]."""
    inbox = kb_check.inbox_dir(root)
    if not inbox:
        return None, []
    svoi = kb_check.imena_proekta(root, recipients=False)
    out = []
    for dirpath, dirnames, filenames in os.walk(inbox):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")
                       and d not in ("archive", "архив", "Archive")]
        for fn in sorted(filenames):
            if not fn.lower().endswith(".md"):
                continue
            full = os.path.join(dirpath, fn)
            text = kb_paths.read(full)
            fm = kb_check.FRONTMATTER.match(text)
            if not fm:
                continue
            head = fm.group(1)
            tip = kb_check.MSG_FIELD["type"].search(head)
            if not tip or "agent-message" not in tip.group(1).lower():
                continue
            ot = kb_check.MSG_FIELD["from"].search(head)
            if ot and kb_check.nash(ot.group(1), svoi):
                continue        # исходящее — забота проверки 6 kb_check
            mid = MESSAGE_ID.search(head)
            created = CREATED.search(head)
            sender = SENDER.search(head)
            out.append({
                "path": os.path.relpath(full, root),
                "message_id": mid.group(1) if mid else None,
                "date": as_date(created.group(1)) if created else None,
                "sender": (sender.group(1).strip().strip("\"'") if sender else "не назван")[:60],
            })
    return os.path.relpath(inbox, root), out


def inbound(root, files, today, grace):
    """Входящие без следа внесения.

    След — упоминание message_id (или имени файла) в любом tracked тексте,
    кроме самих конвертов: провенанс внесённого факта, строка реестра
    разбора «<id> — внесено в … / без дельты: …», ответ-квитанция. Упоминание
    появляется только при действии, поэтому считается как данные, а не как
    заявление (UAD FLOW 26.09: 5 из 9 пакетов неделю лежали вне канона,
    коммит «inbox: accept» выглядел завершением)."""
    where, items = envelopes(root)
    if where is None:
        return {"status": "NOT_APPLICABLE", "reason": "инбокса входящих нет"}
    own = {e["path"] for e in items}
    if files is None:
        # Не Git: след ищется по файлам на диске, а не объявляется отсутствующим.
        files, seen = [], set()
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            real = os.path.realpath(dirpath)
            if real in seen:
                dirnames[:] = []
                continue
            seen.add(real)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and d not in kb_paths.SKIP_DIRS]
            files.extend(os.path.relpath(os.path.join(dirpath, f), root) for f in filenames)
    corpus = []
    for rel in files:
        if rel in own or os.path.splitext(rel)[1].lower() not in DOC_EXT | {".json", ".txt",
                                                                            ".yaml", ".yml"}:
            continue
        try:
            size = os.path.getsize(os.path.join(root, rel))
        except OSError:
            continue
        # Выгрузки данных не пишут провенанс внесения; реестр разбора и индекс
        # малы (продукт на Odoo: 866 JSON на 153 МБ — почти всё выгрузки).
        if size > (2_000_000 if os.path.splitext(rel)[1].lower() in DOC_EXT else 256_000):
            continue
        corpus.append(read(root, rel))
    corpus = "\n".join(corpus)
    added = {}
    if any(e["date"] is None for e in items):
        raw = git(root, "log", "--relative", "--diff-filter=A", "--format=@%cs", "--name-only",
                  "--", where, timeout=60) or ""
        day = None
        for line in raw.splitlines():
            if line.startswith("@"):
                day = as_date(line[1:])
            elif line.strip() and day:
                added[line.strip()] = day      # log идёт от новых к старым
    keys_of = {}
    for e in items:
        stem = os.path.splitext(os.path.basename(e["path"]))[0]
        # Короткий ключ («42») совпадает с чем угодно («1420 EUR»); след — только
        # отдельный токен длиной от 6 символов (ревью 7.3.0).
        keys_of[e["path"]] = [k for k in (e["message_id"], stem) if k and len(k) >= 6]
    seen = set()
    for k in {k for ks in keys_of.values() for k in ks}:
        if k in corpus and re.search(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", corpus):
            seen.add(k)
    open_items = []
    for e in items:
        e["traced"] = any(k in seen for k in keys_of[e["path"]])
        if e["date"] is None:
            e["date"] = added.get(e["path"])
        e["age"] = (today - e["date"]).days if e["date"] else None
        if not e["traced"] and (e["age"] is None or e["age"] > grace):
            open_items.append(e)
    open_items.sort(key=lambda e: -(e["age"] or 0))
    return {"status": "DEBT" if open_items else "PASS", "inbox": where, "total": len(items),
            "traced": sum(1 for e in items if e["traced"]), "open": open_items}


# ---------------------------------------------------------------- работа

def stranded(root, today, stale_days, dirty_hours=6):
    """Работа вне канона: worktree с незакоммиченным/невлитым и старые ветки."""
    top = kb_paths.find_git(root)
    if not top:
        return {"status": "NOT_APPLICABLE", "reason": "репозитория нет"}
    head = (git(top, "rev-parse", "HEAD") or "").strip()
    listing = git(top, "worktree", "list", "--porcelain")
    if not head or listing is None:
        return {"status": "NOT_CHECKED", "reason": "git не ответил"}
    trees, cur = [], {}
    for line in listing.splitlines() + [""]:
        if not line.strip():
            if cur:
                trees.append(cur)
            cur = {}
        elif " " in line:
            k, v = line.split(" ", 1)
            cur[k] = v
        else:
            cur[line] = True
    here = os.path.realpath(top)
    worktrees, missing, unchecked = [], 0, []
    for t in trees:
        path = t.get("worktree")
        if not path or t.get("bare"):
            continue
        if not os.path.isdir(path):
            missing += 1
            continue
        own = os.path.realpath(path) == here
        status = git(path, "status", "--porcelain", timeout=60)
        wt_head = t.get("HEAD", "")
        ahead = unique_commits(top, head, wt_head) if wt_head else 0
        if status is None or ahead is None:
            unchecked.append(path)      # неответ git — не «чисто»
            continue
        dirty = [ln for ln in status.splitlines() if ln.strip()]
        last = as_date(git(path, "log", "-1", "--format=%cs") or "")
        touched, idle_hours = None, None
        if dirty:
            stamps = []
            for ln in dirty[:200]:
                rel = ln[3:].split(" -> ")[-1].strip().strip('"')
                try:
                    stamps.append(os.path.getmtime(os.path.join(path, rel)))
                except OSError:
                    pass
            if stamps:
                touched = datetime.date.fromtimestamp(max(stamps))
                idle_hours = (datetime.datetime.now().timestamp() - max(stamps)) / 3600
        activity = max([d for d in (last, touched) if d] or [today])
        age = (today - activity).days
        unique = ahead or 0
        if (dirty or unique) and (not own or dirty):
            worktrees.append({
                "path": path, "branch": t.get("branch", "(detached)").replace("refs/heads/", ""),
                "own": own, "dirty": len(dirty), "unmerged_commits": unique,
                "last_activity": activity.isoformat(), "age": age,
                "idle_hours": None if idle_hours is None else round(idle_hours, 1),
                "merge": bool(os.path.exists(os.path.join(
                    (git(path, "rev-parse", "--absolute-git-dir") or "").strip(), "MERGE_HEAD"))),
            })
    # Незакоммиченное в чужом worktree интегратору не передано: оно становится
    # долгом, когда файлы не трогали дольше срока в часах (UAD 26.09: два
    # супервизора закоммитили зону, а правки общих файлов оставили в рабочих
    # копиях в тот же день; нашёл их только ручной обход worktree). Живую
    # работу соседней сессии порог не задевает; невлитые коммиты — по дням.
    def overdue(w):
        if w["merge"] or w["age"] >= stale_days:
            return True
        return (not w["own"] and w["dirty"] and w["idle_hours"] is not None
                and w["idle_hours"] >= dirty_hours)
    stale = [w for w in worktrees if overdue(w)]
    # Ветки без worktree: работа, у которой больше нет рабочего места.
    with_tree = {t.get("branch", "").replace("refs/heads/", "") for t in trees}
    refs = git(top, "for-each-ref", "--format=%(refname:short)\t%(committerdate:short)",
               "refs/heads/") or ""
    # Ветка, живущая только на origin, — тоже работа без места в каноне
    # (клубный проект 26.09: 10 коммитов с ролью юриста и урегулированием только в
    # origin/codex/new-season-banner). Двойник локальной ветки не повторяется.
    local = {ln.partition("\t")[0] for ln in refs.splitlines()}
    remote = git(top, "for-each-ref", "--format=%(refname:short)\t%(committerdate:short)",
                 "refs/remotes/") or ""
    for line in remote.splitlines():
        name = line.partition("\t")[0]
        short = name.split("/", 1)[-1]
        if name.endswith("/HEAD") or short in local or "/" not in name:
            continue
        refs += ("\n" if refs else "") + line
    # Squash-слияние оставляет коммиты «уникальными», хотя содержимое уже в
    # каноне; kb_check называет такие ветки «содержимое уже в каноне», и долг
    # не должен ему противоречить (ревью 7.3.0). Решает сверка содержимого.
    vetki, vetki_why = kb_paths.unmerged_refs(top)
    lost = None if vetki_why else {v.name: v.lost for v in vetki}
    branches = []
    for line in refs.splitlines():
        name, _, date = line.partition("\t")
        if not name or name in with_tree:
            continue
        if lost is not None:
            # Локальная ветка, совпавшая с origin-двойником, в unmerged_refs
            # показана под именем двойника.
            here_lost = lost.get(name)
            if here_lost is None:
                here_lost = next((n for k, n in lost.items() if k.endswith("/" + name)), 0)
            if here_lost == 0:
                continue
        cnt = unique_commits(top, head, name)
        if cnt is None:
            unchecked.append(name)
            continue
        when = as_date(date)
        if cnt and when and (today - when).days >= stale_days:
            branches.append({"branch": name, "unmerged_commits": cnt,
                             "last": when.isoformat(), "age": (today - when).days})
    branches.sort(key=lambda b: -b["age"])
    stale.sort(key=lambda w: -w["age"])
    # Отложенное в stash и расхождение с опубликованной веткой — тоже работа
    # вне канона: проект стартапа 08.09 (stash на 7 файлов, kb_due «всё закоммичено»),
    # UAD 26.09 (main впереди origin на 5 и позади на 3, в checkout слияние).
    stashes = [ln for ln in (git(top, "stash", "list", "--format=%cs %gs") or "").splitlines()
               if ln.strip()]
    upstream = None
    lr = git(top, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    if lr and len(lr.split()) == 2:
        ahead_n, behind_n = (int(x) for x in lr.split())
        # Только впереди — «не запушено», это уже говорит kb_due. Долг —
        # расхождение: транспорт пишет в origin, сессия коммитит локально (UAD).
        if behind_n:
            upstream = {"ahead": ahead_n, "behind": behind_n}
    conflicts = [ln[3:] for ln in (git(top, "status", "--porcelain") or "").splitlines()
                 if ln[:2] in ("UU", "AA", "DU", "UD", "AU", "UA", "DD")]
    debt = bool(stale or branches or stashes or upstream or conflicts)
    return {"status": "DEBT" if debt else ("NOT_CHECKED" if unchecked else "PASS"),
            "worktrees": stale,
            "fresh_worktrees": len(worktrees) - len(stale),
            "fresh": [w for w in worktrees if w not in stale and not w["own"] and w["dirty"]],
            "branches": branches,
            "missing_worktrees": missing, "stashes": stashes, "upstream": upstream,
            "conflicts": conflicts, "unchecked": unchecked,
            "reason": f"git не ответил по {len(unchecked)} деревьям/веткам" if unchecked else None}


def unique_commits(top, base, ref):
    """Коммиты ref, чьих патчей нет в base: перенесённое cherry-pick не долг."""
    raw = git(top, "rev-list", "--count", "--right-only", "--cherry-pick", f"{base}...{ref}")
    return int(raw) if raw and raw.strip().isdigit() else None


# ---------------------------------------------------------------- код

def knowledge_paths(root, files):
    """Что считается знанием: документация, правила, current, индекс, роли."""
    roots, _ = kb_index.knowledge_roots(__import__("pathlib").Path(root))
    inbox = kb_check.inbox_dir(root)
    inbox_rel = os.path.relpath(inbox, root) + "/" if inbox else None
    out = set()
    for rel in files:
        if inbox_rel and rel.startswith(inbox_rel):
            continue
        ext = os.path.splitext(rel)[1].lower()
        in_root = any(rel.startswith(r.rstrip("/") + "/") for r in roots)
        if ext in DOC_EXT or rel in ("KNOWLEDGE_INDEX.json", "PROJECT_ROLES.json") \
                or (in_root and ext in {".json", ".yaml", ".yml", ".txt"}):
            out.add(rel)
    return out


# Выходы (отчёты, выгрузки, сборки) — результат, не модуль продукта.
# Тесты описываются вместе со своим модулем; архив — история, не продукт.
OUTPUT_DIR = re.compile(r"(^|/)_?(reports?|outputs?|out|exports?|_out|site|public|tests?|"
                        r"archive|архив|_archive|fixtures)(/|$)", re.I)


def not_code(root, files):
    """Каталоги, чьи исходники модулями продукта не являются.

    Аудит 26.09: UAD получил «модули» из корня знания (зеркала исходников), каталога
    ролей и отчётов; семейный проект — из выгруженного сайта-отчёта; вложенный проект
    со своими правилами описывает свой код сам."""
    import pathlib
    roots, _ = kb_index.knowledge_roots(pathlib.Path(root))
    skip = {r.strip("/") for r in roots}
    inbox = kb_check.inbox_dir(root)
    if inbox:
        skip.add(os.path.relpath(inbox, root))
    skip.update({"_megamozg", "skills"})
    try:
        registry = json.loads(read(root, "PROJECT_ROLES.json") or "{}")
        for skill in registry.get("skills", []) if isinstance(registry, dict) else []:
            if isinstance(skill, dict) and isinstance(skill.get("canonical"), str):
                skip.add(skill["canonical"].strip("/"))
    except ValueError:
        pass
    for rel in files:
        if os.path.basename(rel) in kb_paths.RULES_NAMES and "/" in rel:
            skip.add(os.path.dirname(rel))          # вложенный проект
    return skip


def code_units(files, skip=()):
    """Модули кода: каталоги с manifest; исходники вне них — по верхнему каталогу."""
    def excluded(rel):
        return VENDORED.search(rel) or OUTPUT_DIR.search(rel) or any(
            rel == s or rel.startswith(s + "/") for s in skip)
    units = set()
    for rel in files:
        if os.path.basename(rel) in MANIFESTS and "/" in rel and not excluded(rel):
            units.add(os.path.dirname(rel))
    # Вложенный manifest владеет своим поддеревом. Исходники, не принадлежащие
    # ни одному manifest, группируются по верхнему каталогу: найденный где-то
    # вложенный package.json не должен выключать поиск основного кода.
    source = [r for r in files if os.path.splitext(r)[1].lower() in SOURCE_EXT
              and not excluded(r)]
    counts = {}
    for rel in source:
        if any(rel.startswith(u + "/") for u in units):
            continue
        top = rel.split("/", 1)[0] if "/" in rel else "."
        counts[top] = counts.get(top, 0) + 1
    units |= {u for u, n in counts.items() if n >= 3 and u != "."}
    owned = {}
    for rel in source:
        best = None
        for u in units:
            if rel.startswith(u + "/") and (best is None or len(u) > len(best)):
                best = u
        if best:
            owned.setdefault(best, []).append(rel)
    return {u: owned.get(u, []) for u in sorted(units) if owned.get(u)}


def route_code(root):
    """Маршруты индекса с полем `code`: [(globs, описания)]."""
    path = os.path.join(root, kb_index.DEFAULT_INDEX)
    try:
        data = json.loads(read(root, kb_index.DEFAULT_INDEX)) if os.path.isfile(path) else {}
    except ValueError:
        return []
    out = []
    for route in data.get("routes", []) if isinstance(data, dict) else []:
        if isinstance(route, dict) and isinstance(route.get("code"), list):
            globs = [g for g in route["code"] if isinstance(g, str)]
            out.append((globs, kb_index.local_paths(route)))
    return out


# Журнал упоминает модуль в каждой записи и меняется каждый день; засчитать
# его описанием значит никогда не увидеть отставания (продукт на Odoo 26.09:
# BACKLOG, SLOMALOS и история «описывали» модули, которых новый чат не понимал).
JOURNAL_NAME = re.compile(r"(?:CHANGELOG|BACKLOG|SLOMALOS|CORRECTIONS|JOURNAL|HISTORY|"
                          r"ИСТОРИ|ЖУРНАЛ|ПРАВКИ|history|changelog|journal)", re.IGNORECASE)


def anchors_for(unit, files_in_unit, docs, texts, routes):
    """Описание модуля: [(файл, как)], где как — whole (весь файл о модуле) или
    section (заголовок раздела называет модуль). Строка в списке не описание."""
    found = {}
    for globs, paths in routes:
        if any(fnmatch.fnmatch(f, g) for g in globs for f in files_in_unit):
            for p in paths:
                found[p] = "whole"
    for readme in ("README.md", "README.rst", "README"):
        if f"{unit}/{readme}" in docs:
            found[f"{unit}/{readme}"] = "whole"
    name = unit.rsplit("/", 1)[-1]
    distinctive = len(name) >= 4 and name.lower() not in {"src", "lib", "app", "apps", "code",
                                                          "tools", "scripts", "test", "tests",
                                                          "automation", "server", "client"}
    # Путь верхнего каталога совпадает с его именем: «tools» в любом заголовке
    # описанием не является, `tools/` — является.
    path_form = re.escape(unit) + (r"/" if "/" not in unit else r"(?![\w-])")
    heading = re.compile(r"^#{1,6}[^\n]*?(?<![\w-])(?:" + path_form
                         + (r"|" + re.escape(name) + r"(?![\w-])" if distinctive else "") + r")",
                         re.MULTILINE)
    for rel, text in texts.items():
        if rel in found or JOURNAL_NAME.search(os.path.basename(rel)):
            continue
        if rel.startswith(unit + "/"):
            continue        # файлы внутри модуля, кроме README, — его код и данные
        # Целый токен имени файла: «shop» не описан файлом WORKSHOP.md (ревью 7.3.0).
        tokens = re.split(r"[-_. ]+", os.path.splitext(os.path.basename(rel))[0].lower())
        parts = re.split(r"[-_. ]+", name.lower())
        if distinctive and any(tokens[i:i + len(parts)] == parts
                               for i in range(len(tokens) - len(parts) + 1)):
            found[rel] = "whole"
        elif heading.search(text):
            found[rel] = "section"
    return sorted(found.items())


def described_at(root, unit, anchors):
    """(sha, дата) последнего изменения описания: файла целиком либо строк про модуль.

    Граница метода: строка версии модуля внутри раздела тоже считается правкой
    описания (продукт на Odoo: сверка версий обновляла все модули разом)."""
    name = unit.rsplit("/", 1)[-1]
    best = None
    for rel, how in anchors:
        args = ["log", "-1", "--no-merges", "--format=%H %ct %cs"]
        if how == "section":
            args += ["-G", re.escape(name)]
        raw = (git(root, *args, "--", rel) or "").split()
        if len(raw) == 3 and (best is None or int(raw[1]) > int(best[1])):
            best = raw
    return (best[0], best[2]) if best else (None, None)


def history(root):
    """Один проход по истории: [(sha, время, {файлы})], новые первыми."""
    # --relative: проект может быть подкаталогом большего репозитория, а пути
    # модулей считаются от корня проекта (ревью 7.3.0).
    raw = git(root, "log", "--relative", "--no-merges", "--format=@%H %ct", "--name-only", "HEAD",
              timeout=120)
    if raw is None:
        return None
    out, cur = [], None
    for line in raw.splitlines():
        if line.startswith("@"):
            sha, _, ct = line[1:].partition(" ")
            cur = (sha, int(ct or 0), set())
            out.append(cur)
        elif line.strip() and cur is not None:
            cur[2].add(line.strip())
    return out


def touches(files, unit, skip=()):
    prefix = unit + "/"
    return any(f.startswith(prefix) and f not in skip for f in files)


def code(root, files, today, lag_limit):
    units = code_units(files, not_code(root, files))
    if not units:
        return {"status": "NOT_APPLICABLE", "reason": "модулей кода не найдено"}
    docs = knowledge_paths(root, files)
    texts = {rel: read(root, rel, 200000) for rel in docs}
    routes = route_code(root)
    raw_allowed, _ = kb_paths.declared_value(root, CODE_ALLOWED_KEYS)
    allowed = [g.strip().strip("`\"'«»") for g in re.split(r"[,;]", raw_allowed or "") if g.strip()]
    log = history(root)
    if log is None:
        return {"status": "NOT_CHECKED", "reason": "git log не ответил — отставание описаний не посчитано"}
    head_time = log[0][1] if log else 0
    positions = {commit: i for i, (commit, _, _) in enumerate(log)}
    missing, lagging, described, excused = [], [], [], []
    for unit, owned in units.items():
        if any(fnmatch.fnmatch(unit, g.rstrip("/")) or fnmatch.fnmatch(unit + "/", g)
               for g in allowed):
            excused.append(unit)
            continue
        recent = sum(1 for _, ct, fs in log if ct >= head_time - 90 * 86400 and touches(fs, unit))
        anchors = anchors_for(unit, owned, docs, texts, routes)
        if not anchors:
            missing.append({"unit": unit, "files": len(owned), "commits_90d": recent})
            continue
        sha, when = described_at(root, unit, anchors)
        inside = {a for a, _ in anchors if a.startswith(unit + "/")}
        lag = 0
        if sha and sha in positions:
            for commit, _, fs in log[:positions[sha]]:
                lag += touches(fs, unit, inside)
        elif sha:
            raw = git(root, "rev-list", "--count", "--no-merges", f"{sha}..HEAD", "--", unit,
                      *[f":(exclude){a}" for a in inside])
            lag = int(raw) if raw and raw.strip().isdigit() else 0
        entry = {"unit": unit, "files": len(owned), "commits_90d": recent,
                 "anchors": [a for a, _ in anchors[:3]], "described_at": when, "lag_commits": lag}
        (lagging if lag >= lag_limit else described).append(entry)
    missing.sort(key=lambda u: (-u["commits_90d"], -u["files"]))
    lagging.sort(key=lambda u: -u["lag_commits"])
    return {"status": "DEBT" if missing or lagging else "PASS", "units": len(units),
            "described": len(described), "missing": missing, "lagging": lagging,
            "excused": excused, "routes_with_code": len(routes)}


def flow(root, files, window, min_code):
    """За окно: сколько коммитов меняли код и сколько из них принесли знание."""
    units = code_units(files, not_code(root, files))
    if not units:
        return {"status": "NOT_APPLICABLE", "reason": "модулей кода не найдено"}
    # Запись в журнале говорит «что поменяли», а не «как устроено».
    docs = {d for d in knowledge_paths(root, files)
            if not JOURNAL_NAME.search(os.path.basename(d))}
    code_files = {f for owned in units.values() for f in owned}
    log = git(root, "log", "--relative", f"--since={window}.days", "--no-merges", "--name-only",
              "--format=@%H", timeout=60)
    if log is None:
        return {"status": "NOT_CHECKED", "reason": "git log не ответил"}
    commits, cur = [], None
    for line in log.splitlines():
        if line.startswith("@"):
            cur = set()
            commits.append(cur)
        elif line.strip() and cur is not None:
            cur.add(line.strip())
    code_commits = [c for c in commits if c & code_files]
    with_knowledge = [c for c in code_commits if c & docs]
    knowledge_commits = [c for c in commits if c & docs]
    share = len(with_knowledge) / len(code_commits) if code_commits else None
    # Справка, не долг: на истории продукта на Odoo доля колебалась около 0.2
    # и не различала месяц без описаний от месяца починки. Различает счёт по
    # модулям выше; доля остаётся контекстом объёма работы.
    return {"status": "INFO", "window_days": window,
            "commits": len(commits), "code_commits": len(code_commits),
            "code_commits_with_knowledge": len(with_knowledge),
            "knowledge_commits": len(knowledge_commits),
            "share": None if share is None else round(share, 2)}


# ---------------------------------------------------------------- свежесть

def freshness(root, files, today, limit):
    """Файлы о настоящем, свежесть которых не подтверждалась дольше порога.

    Правило 7.1 честно запретило выдумывать valid_until и велело писать
    observed_at; ни один скрипт это поле не читал, и честная запись стала
    невидимой (UAD PAYS 26.09: карта зоны 11 дней держала «блокер» после
    двух выкладок)."""
    roots, _ = kb_index.knowledge_roots(__import__("pathlib").Path(root))
    scope = [f for f in files or [] if os.path.splitext(f)[1].lower() in DOC_EXT
             and ("/" not in f or any(f.startswith(r.rstrip("/") + "/") for r in roots))]
    old, counted = [], 0
    for rel in scope:
        head = read(root, rel, 6000)
        m = OBSERVED.search(head)
        if not m or VALID_UNTIL.search(head):
            continue
        when = as_date(m.group(1))
        if not when:
            continue
        counted += 1
        age = (today - when).days
        if age > limit:
            old.append({"path": rel, "observed_at": when.isoformat(), "age": age})
    old.sort(key=lambda x: -x["age"])
    if not counted:
        return {"status": "NOT_APPLICABLE", "reason": "файлов с observed_at нет"}
    return {"status": "DEBT" if old else "PASS", "files": counted, "stale": old,
            "limit_days": limit}


# ---------------------------------------------------------------- current

DEADLINE_CUE = re.compile(r"(?:\bдо|\bк|\bсрок\w*|\bдедлайн\w*|\bне\s+поз(?:же|днее)|"
                          r"\bdeadline|\bby|\buntil|\bdue)\s*:?\s*(\d{1,2})\.(\d{1,2})(?!\.?\d)",
                          re.IGNORECASE)
# «обновить Python до 3.11» — версия, а не срок (ревью 7.3.0).
VERSION_BEFORE = re.compile(r"(?:верси\w*|version|release|релиз\w*|python|node|php|java|"
                            r"postgres\w*|odoo|ubuntu|v)\s*$", re.IGNORECASE)
PAST_SECTIONS = ("ОТВЕРГЛИ", "ИСТОРИ", "ЖУРНАЛ", "HISTORY", "REJECTED", "ВЫПОЛНЕНО", "DONE")


def current(root, today):
    """Вход, по которому время уже прошло.

    Дата позже строки «Обновлено» была будущей, когда её писали: срок, план,
    ожидание. Если она уже наступила, а вход с тех пор не обновлялся, вход
    говорит о настоящем то, что стало прошлым (проект недвижимости: срок 15.09 при
    «Обновлено 2026-09-05», коммитов по теме нет; UAD: дата 24.09 в тексте при
    заголовке 23.09). Возраст входа kb_due уже считает; здесь — его содержание."""
    import kb_dates
    import kb_due
    entry = kb_paths.locate(root, "entry")
    if not entry.path:
        return {"status": "NOT_APPLICABLE", "reason": "файлового входа нет"}
    text = entry.text()
    stamp = kb_due.freshness_of(text)
    got, _ = kb_dates.parse_dates(stamp or "", day_first=True)
    if not got:
        return {"status": "NOT_CHECKED", "reason": "во входе нет распознанной строки «Обновлено»"}
    updated = max(got)
    passed, skip_level = [], None
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and any(s in m.group(2).upper() for s in PAST_SECTIONS):
                skip_level = level
            continue
        if skip_level is not None or re.match(r"^\s*(?:обновлено|updated)\s*:", line, re.I):
            continue
        dates, _ = kb_dates.parse_dates(line, day_first=True)
        cues = [(int(m.group(1)), int(m.group(2))) for m in DEADLINE_CUE.finditer(line)
                 if not VERSION_BEFORE.search(line[:m.start()].rstrip())]
        for d, mo in cues:
            try:
                when = datetime.date(updated.year, mo, d)
                # «до 10.01», записанное в декабре, — январь следующего года.
                if (updated - when).days > 180:
                    when = datetime.date(updated.year + 1, mo, d)
                dates.append(when)
            except ValueError:
                pass
        hits = sorted({d for d in dates if updated < d < today})
        if hits:
            passed.append({"date": hits[0].isoformat(), "line": line.strip()[:110]})
    rel = os.path.relpath(entry.path, root)
    dirty = git(root, "status", "--porcelain", "--", rel)
    head_text = git(root, "show", f"HEAD:./{rel}") if dirty and dirty.strip() else None
    head_stamp = None
    if head_text:
        hs, _ = kb_dates.parse_dates(kb_due.freshness_of(head_text) or "", day_first=True)
        head_stamp = max(hs).isoformat() if hs else None
    return {"status": "DEBT" if passed else "PASS", "entry": rel,
            "updated": updated.isoformat(), "passed": passed[:20], "passed_total": len(passed),
            "uncommitted": bool(dirty and dirty.strip()), "head_updated": head_stamp}


# ---------------------------------------------------------------- роли

ROLE_STATE = re.compile(r"(?:сломан|почин|не\s+работа|перестал|выложен|активирован|отключ|"
                        r"\b403\b|\bверси[яи]\s+\d+|\bbroken\b|\bfixed\b|\bdeployed\b)",
                        re.IGNORECASE)
ROLE_DATE = re.compile(r"\b\d{1,2}\.\d{1,2}(?:\.20\d{2})?\b|\b20\d{2}-\d{2}-\d{2}\b")


def roles(root):
    """Роль, объявленная методом, держит датированное состояние внешней системы.

    Метод обновляется реже фактов, поэтому факт в методе учит неверному дольше
    всего (UAD 26.09: роль аналитики 25 дней повторяла «покупки сломаны с
    11.08» после починки 01.09)."""
    path = os.path.join(root, "PROJECT_ROLES.json")
    try:
        data = json.loads(read(root, "PROJECT_ROLES.json")) if os.path.isfile(path) else None
    except ValueError:
        data = None
    if not data:
        return {"status": "NOT_APPLICABLE", "reason": "реестра ролей нет"}
    hits, checked = [], 0
    for skill in data.get("skills", []) if isinstance(data, dict) else []:
        if not isinstance(skill, dict):
            continue
        boundary = (skill.get("quality") or {}).get("knowledge_boundary") \
            or skill.get("knowledge_boundary")
        canonical = skill.get("canonical")
        if boundary != "method-only" or not isinstance(canonical, str):
            continue
        base = os.path.join(root, canonical)
        if not os.path.isdir(base):
            continue
        checked += 1
        for dirpath, _, filenames in os.walk(base):
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                for n, line in enumerate(read(root, rel).splitlines(), 1):
                    if ROLE_STATE.search(line) and ROLE_DATE.search(line):
                        hits.append({"path": f"{rel}:{n}", "line": line.strip()[:110]})
    if not checked:
        return {"status": "NOT_APPLICABLE", "reason": "ролей с границей method-only нет"}
    return {"status": "DEBT" if hits else "PASS", "roles": checked, "lines": hits[:20],
            "total": len(hits)}


# ---------------------------------------------------------------- сборка

def debts(root, today=None, area=None):
    root = os.path.abspath(root)
    today = today or datetime.date.today()
    t = thresholds(root)
    files = tracked(root)
    if files is None:
        base = {"status": "NOT_CHECKED", "reason": "не Git-репозиторий или git не ответил"}
        return {"root": root, "today": today.isoformat(), "thresholds": t,
                "inbound": inbound(root, None, today, t["inbound_grace_days"]),
                "work": base, "code": base, "flow": base, "freshness": base,
                "current": current(root, today), "roles": roles(root)}
    if area:
        area = area.strip("/")
    result = {
        "root": root, "today": today.isoformat(), "thresholds": t,
        "inbound": inbound(root, files, today, t["inbound_grace_days"]),
        "work": stranded(root, today, t["work_stale_days"], t["dirty_idle_hours"]),
        "code": code(root, files, today, t["code_lag_commits"]),
        "flow": flow(root, files, t["flow_window_days"], t["flow_min_code_commits"]),
        "freshness": freshness(root, files, today, t["freshness_days"]),
        "current": current(root, today),
        "roles": roles(root),
    }
    if area:
        inside = lambda p: p == area or p.startswith(area + "/")
        # Статус пересчитывается после отбора: долг вне области не должен
        # оставлять пустой DEBT (ревью 7.3.0: IndexError в сводке).
        c = result["code"]
        if c.get("missing") is not None:
            for key in ("missing", "lagging"):
                c[key] = [u for u in c[key] if inside(u["unit"])]
            c["status"] = "DEBT" if c["missing"] or c["lagging"] else "PASS"
        f = result["freshness"]
        if f.get("stale") is not None:
            f["stale"] = [x for x in f["stale"] if inside(x["path"])]
            f["status"] = "DEBT" if f["stale"] else "PASS"
        result["area"] = area
    return result


def summary_lines(d):
    """Короткие строки для kb_due/kb_check: одна на класс долга."""
    out, clean = [], []
    i = d["inbound"]
    if i["status"] == "DEBT":
        oldest = i["open"][0]
        age = f"{oldest['age']} дн." if oldest["age"] is not None else "возраст неизвестен"
        out.append(f"входящие без следа внесения: {len(i['open'])} из {i['total']} "
                   f"({i['inbox']}); самое давнее {age} — {oldest['path']} "
                   f"от {oldest['sender']}. Внеси с провенансом message_id или отметь "
                   f"исход строкой реестра разбора")
    elif i["status"] == "PASS":
        clean.append(f"входящие: у всех {i['total']} есть след внесения" if i["total"]
                     else "входящие: конвертов agent-message в инбоксе нет")
    w = d["work"]
    if w["status"] == "DEBT":
        parts = []
        if w["worktrees"]:
            top = w["worktrees"][0]
            parts.append(f"worktree с незавершённой работой: {len(w['worktrees'])} "
                         f"(старейший {top['age']} дн.: {top['branch']}, "
                         f"{top['dirty']} незакоммич., {top['unmerged_commits']} невлитых"
                         + (", идёт слияние" if top["merge"] else "") + ")")
        if w["branches"]:
            b = w["branches"][0]
            parts.append(f"ветки без рабочего места с невлитыми коммитами: {len(w['branches'])} "
                         f"(старейшая {b['branch']}, {b['age']} дн.)")
        if w.get("conflicts"):
            parts.append(f"в checkout незавершённое слияние, конфликтов: {len(w['conflicts'])}")
        if w.get("upstream"):
            u = w["upstream"]
            parts.append(f"ветка расходится с upstream: впереди {u['ahead']}, позади {u['behind']}")
        if w.get("stashes"):
            parts.append(f"отложено в stash: {len(w['stashes'])} (старейшее "
                         f"{w['stashes'][-1][:10]})")
        out.append("; ".join(parts) + ". Влей, закрой с записью причины или назови "
                   "владельца продолжения в current")
    elif w["status"] == "PASS":
        clean.append("невлитой работы в worktree/ветках старше порога нет")
    if w.get("fresh"):
        clean.append(f"worktree с текущей незакоммиченной работой: {len(w['fresh'])} "
                     f"({', '.join(x['branch'] for x in w['fresh'][:4])}) — моложе срока; "
                     f"незакоммиченное интегратору не передано")
    if w.get("unchecked"):
        clean.append(f"невлитая работа: git не ответил по {len(w['unchecked'])} деревьям/веткам "
                     f"({', '.join(os.path.basename(x) for x in w['unchecked'][:3])}) — они НЕ ПРОВЕРЕНЫ")
    c = d["code"]
    if c["status"] == "DEBT":
        bits = []
        if c["missing"]:
            names = ", ".join(u["unit"] for u in c["missing"][:4])
            bits.append(f"модулей кода без описания: {len(c['missing'])} из {c['units']} ({names}"
                        + (" …" if len(c["missing"]) > 4 else "") + ")")
        if c["lagging"]:
            u = c["lagging"][0]
            bits.append(f"описаний, отставших от кода: {len(c['lagging'])} "
                        f"(сильнее всего {u['unit']}: {u['lag_commits']} коммитов после "
                        f"{u['described_at']})")
        out.append("; ".join(bits) + ". Следующий чат будет читать код вместо описания")
    elif c["status"] == "PASS":
        clean.append(f"код: у всех {c['units']} модулей есть неотставшее описание")
    f = d["flow"]
    if f["status"] == "INFO" and f.get("code_commits"):
        clean.append(f"за {f['window_days']} дн. коммитов кода {f['code_commits']}, из них с "
                     f"описанием или current в том же коммите {f['code_commits_with_knowledge']}")
    fr = d["freshness"]
    if fr["status"] == "DEBT":
        s = fr["stale"][0]
        out.append(f"файлов о настоящем с observed_at старше {fr['limit_days']} дн.: "
                   f"{len(fr['stale'])} из {fr['files']} (старейший {s['path']}, {s['age']} дн.). "
                   f"Перед выводом сверь с источником или скажи UNKNOWN; обнови observed_at")
    elif fr["status"] == "PASS":
        clean.append(f"свежесть: {fr['files']} файлов с observed_at в пределах "
                     f"{fr['limit_days']} дн.")
    cur = d.get("current", {})
    if cur.get("status") == "DEBT":
        p = cur["passed"][0]
        out.append(f"вход {cur['entry']} (Обновлено {cur['updated']}) называет даты, которые уже "
                   f"прошли: {kb_check.skl(cur['passed_total'], 'строка', 'строки', 'строк')}, первая — {p['date']}: «{p['line'][:70]}». "
                   f"Срок наступил без обновления входа или вход правили, не обновив дату")
    if cur.get("uncommitted"):
        clean.append(f"вход {cur['entry']} изменён в рабочем дереве и не закоммичен; "
                     f"в HEAD «Обновлено» {cur.get('head_updated') or 'не распознано'} — другие "
                     f"сессии видят версию HEAD")
    ro = d.get("roles", {})
    if ro.get("status") == "DEBT":
        out.append(f"роль-метод держит датированное состояние: {kb_check.skl(ro['total'], 'строка', 'строки', 'строк')} "
                   f"(первая {ro['lines'][0]['path']}). Метод обновляют реже фактов — перенеси "
                   f"состояние в знание и дай роли ссылку")
    for key, label in (("inbound", "входящие"), ("work", "невлитая работа"), ("code", "код"),
                       ("freshness", "свежесть"), ("current", "вход")):
        if d[key]["status"] in ("NOT_CHECKED",):
            clean.append(f"{label} — НЕ ПРОВЕРЕНО: {d[key].get('reason')}")
    return out, clean


def print_report(d):
    lines, clean = summary_lines(d)
    print("ДОЛГИ ЗНАНИЯ — работа, не дошедшая до базы" + (f" (область {d['area']})" if d.get("area") else "") + ":")
    if not lines:
        print("  нет в проверенном охвате.")
    for line in lines:
        print(f"  • {line}")
    detail = d["inbound"]
    if detail.get("open"):
        print("\n  Входящие без следа (старейшие):")
        for e in detail["open"][:10]:
            age = f"{e['age']} дн." if e["age"] is not None else "возраст неизвестен"
            print(f"    {e['path']} — {age}, {e['sender']}, message_id {e['message_id']}")
    if d["work"].get("worktrees") or d["work"].get("branches"):
        print("\n  Невлитая работа:")
        for w in d["work"].get("worktrees", [])[:10]:
            idle = f", не трогали {w['idle_hours']:.0f} ч" if w.get("idle_hours") is not None else ""
            print(f"    {w['path']} [{w['branch']}] — {w['dirty']} незакоммич.{idle}, "
                  f"{w['unmerged_commits']} невлитых, активность {w['last_activity']}"
                  + (", MERGE_HEAD" if w["merge"] else ""))
        for b in d["work"].get("branches", [])[:10]:
            print(f"    ветка {b['branch']} — {b['unmerged_commits']} невлитых, последний {b['last']}")
        for c_ in d["work"].get("conflicts", [])[:5]:
            print(f"    конфликт слияния: {c_}")
        for s in d["work"].get("stashes", [])[:5]:
            print(f"    stash: {s[:90]}")
    if d["work"].get("missing_worktrees"):
        print(f"\n  Зарегистрированных worktree без каталога: {d['work']['missing_worktrees']} "
              f"(git worktree prune после проверки, что работа не нужна)")
    if d.get("current", {}).get("passed"):
        print("\n  Вход: даты после «Обновлено», которые уже прошли:")
        for p in d["current"]["passed"][:10]:
            print(f"    {p['date']} — {p['line']}")
    if d.get("roles", {}).get("lines"):
        print("\n  Роль-метод с датированным состоянием:")
        for r in d["roles"]["lines"][:10]:
            print(f"    {r['path']} — {r['line']}")
    c = d["code"]
    if c.get("missing") or c.get("lagging"):
        print("\n  Код без описания / с отставшим описанием:")
        for u in c.get("missing", [])[:15]:
            print(f"    {u['unit']} — {u['files']} файлов, коммитов за 90 дн.: {u['commits_90d']}; описания нет")
        for u in c.get("lagging", [])[:15]:
            print(f"    {u['unit']} — описание {', '.join(u['anchors'])} от {u['described_at']}, "
                  f"после него {u['lag_commits']} коммитов модуля")
    if d["freshness"].get("stale"):
        print("\n  Свежесть не подтверждена (старейшие):")
        for s in d["freshness"]["stale"][:10]:
            print(f"    {s['path']} — observed_at {s['observed_at']}, {s['age']} дн.")
    print("\nСведения и границы проверки:")
    for line in clean:
        print(f"  · {line}")
    t = d["thresholds"]
    print(f"  · пороги: внесение входящих {t['inbound_grace_days']} дн., невлитая работа "
          f"{t['work_stale_days']} дн., незакоммиченное в чужом worktree {t['dirty_idle_hours']} ч, "
          f"отставание описания {t['code_lag_commits']} коммитов, "
          f"окно потока {t['flow_window_days']} дн., свежесть {t['freshness_days']} дн. "
          f"Проект меняет их строками правил.")
    print("  · след — данные (упоминание, коммит, дата), а не заявление; упоминание не доказывает")
    print("    полноту внесения, его отсутствие не доказывает, что факт не внесён без провенанса.")
    print("DIAGNOSTIC_REPORT: exit 0 означает сформированный отчёт, не отсутствие долгов.")


def is_kb_project(path):
    return any(re.search(r"kb_standard_version\s*:", kb_paths.read(os.path.join(path, name)))
               for name in kb_paths.RULES_NAMES)


def sweep(parent):
    """Одна строка на проект: где база отстаёт от работы, без захода в каждый.

    Спящий проект не запускает kb_due и не узнаёт о своих долгах; аудит
    26.09.2026 нашёл 5 из 7 малых проектов без коммитов больше двух недель
    при открытых сроках во входе и 12 проектов ниже минимального уровня."""
    rows = []
    for name in sorted(os.listdir(parent)):
        path = os.path.join(parent, name)
        if name.startswith((".", "_")) or not os.path.isdir(path) or not is_kb_project(path):
            continue
        try:
            d = debts(path)
        except Exception as exc:       # один проект не останавливает обзор
            rows.append({"project": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        version, _ = kb_paths.project_version(path)
        last = (git(path, "log", "-1", "--format=%cs") or "").strip() or "—"
        c, w, i, cur = d["code"], d["work"], d["inbound"], d["current"]
        rows.append({
            "project": name, "version": version or "—", "last_commit": last,
            "now_updated": cur.get("updated", "—"),
            "inbound_open": len(i.get("open", [])), "inbound_total": i.get("total", 0),
            "code_missing": len(c.get("missing", [])), "code_lagging": len(c.get("lagging", [])),
            "code_units": c.get("units", 0),
            "work": len(w.get("worktrees", [])) + len(w.get("branches", []))
            + len(w.get("stashes", [])) + (1 if w.get("conflicts") else 0),
            "deadlines_passed": cur.get("passed_total", 0),
            "stale_present": len(d["freshness"].get("stale", [])),
            "role_state": d["roles"].get("total", 0),
        })
    return rows


def print_sweep(rows):
    minimum = kb_paths.skill_contract_line() or "?"
    print(f"ДОЛГИ ЗНАНИЯ ПО ПРОЕКТАМ (минимальный уровень проекта {minimum}):")
    print("  проект | уровень | последний коммит | NOW | входящие без следа | код без описания/"
          "отстал | невлитая работа | сроки прошли | свежесть | роль-факт")
    for r in rows:
        if r.get("error"):
            print(f"  {r['project']} | НЕ ПРОВЕРЕН: {r['error']}")
            continue
        print(f"  {r['project']} | {r['version']} | {r['last_commit']} | {r['now_updated']} | "
              f"{r['inbound_open']}/{r['inbound_total']} | {r['code_missing']}+{r['code_lagging']}"
              f"/{r['code_units']} | {r['work']} | {r['deadlines_passed']} | "
              f"{r['stale_present']} | {r['role_state']}")
    print("  Подробно по проекту: kb_debts.py <корень>. Закрывает долги сессия этого проекта.")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    if args[0] == "--sweep":
        rest = [a for a in args[1:] if not a.startswith("--")]
        parent = rest[0] if rest else "."
        if not os.path.isdir(parent):
            print(f"нет такой папки: {parent}")
            return 2
        rows = sweep(parent)
        if "--json" in args:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print_sweep(rows)
        return 0
    root = args[0]
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2
    area = None
    if "--area" in args:
        i = args.index("--area")
        area = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else None
        if area is None:
            print("--area требует путь области")
            return 2
    d = debts(root, area=area)
    if "--json" in args:
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    elif "--summary" in args:
        # Короткий блок для вывода внутри обновления (kb_update --project).
        lines, clean = summary_lines(d)
        for line in lines:
            print(f"  • {line}")
        for line in clean:
            if "НЕ ПРОВЕРЕН" in line:
                print(f"  · {line}")
        print(f"KNOWLEDGE_DEBTS={len(lines)}")
    else:
        print_report(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
