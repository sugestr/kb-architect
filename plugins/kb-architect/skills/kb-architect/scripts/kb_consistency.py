#!/usr/bin/env python3
"""kb_consistency.py — согласованность и форма живого канона.

Остальные проверки отвечают «записано ли?» и «находится ли?». Эта отвечает, где база
вероятно противоречит себе или потеряла форму, и проверял ли это кто-нибудь. Сама она
противоречий не ищет — она находит горячие главы и помнит, какие их версии прочитаны.

    python3 kb_consistency.py <корень> [--json]           горячие главы и статус
    python3 kb_consistency.py <корень> --area <путь>      карточка области перед записью
    python3 kb_consistency.py review <корень> [--chapter <путь>] [--agent codex|claude]
                                            [--print-prompt] [--force]
                                                         модель читает горячие главы, только чтение
    python3 kb_consistency.py record <корень> <путь> --found N --confirmed M --fixed K
                                     [--open "<что осталось>"] [--by "<кто проверял>"]

Горячая глава (сигналы без модели; проект с быстрым ростом базы, 11–12.10.2026):
  рост — с её последней проверки, а если её не проверяли — за всю её историю: не меньше
         20 коммитов и 2 000 добавленных слов, удалено меньше 5 % добавленного, файл от
         40 КБ — новое ложится поверх старого;
  форма — строка вне кода длиннее 4 КБ или больше 20 КБ на заголовок, и за последние
         14 дней файл правили не меньше 3 раз.
Отметка «Сервисный обход базы» на окна не влияет: горячую главу закрывает только чтение.
Размер файла и цена маршрута — справка: большие структурированные документы бывают
правильными. Сигналов нет — значит «сигналов нет», а не «противоречий нет».

Журнал проверок KB_CONSISTENCY.json в корне хранит для каждой прочитанной главы хеш её
содержимого, коммит, дату, проверяющего и исход. Это журнал проверок, не канон фактов.
Изменилась глава — её отметка больше не действует. Подтверждённое, но не исправленное
противоречие держит статус FAIL до новой записи. Переименование начинает историю заново.

Статус: PASS · PENDING (есть непрочитанные горячие главы) · FAIL (известные противоречия
не исправлены) · UNKNOWN (git не ответил — проверка не состоялась) · NOT_APPLICABLE (не Git).
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_index  # noqa: E402
import kb_paths  # noqa: E402

RECORD = "KB_CONSISTENCY.json"
LIMITS = {"commits": 20, "words": 2000, "ratio": 0.05, "size": 40_000,
          "line": 4096, "per_heading": 20_000, "form_size": 8_000, "form_commits": 3,
          "window_days": 14, "route": 150_000}
# Журналы и снимки — не живой канон: дописывание в них норма.
JOURNAL = re.compile(r"(?i)(?:^|/)(?:changelog|corrections|slomalos|history|correspondence|"
                     r"timeline|releases|release-notes|переписка|хроника|журнал)[^/]*\.md$"
                     r"|(?:^|/)[^/]*(?:archive|архив)[^/]*(?:/|\.md$)"
                     r"|(?<!\d)20\d{2}-\d{2}(?:-\d{2})?(?!\d)")
FENCE = re.compile(r"(?ms)^ {0,3}(`{3,}|~{3,}).*?^ {0,3}\1[^\n]*$")
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+\S", re.M)
STATUS = re.compile(r"(?i)при[её]мк|жд[её]м|жд[её]т|открыт|вопрос|не сделан|\bTBD\b|PENDING")
CONFIDENCE = {"high", "medium", "low"}


class GitFailed(Exception):
    """Git не ответил: проверка не состоялась, это не «сигналов нет»."""


def git(root, *args, timeout=60, required=True):
    try:
        r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=off", *args],
                           capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        if required:
            raise GitFailed(f"git {args[0]}: {type(exc).__name__}")
        return None
    if r.returncode != 0:
        if required:
            raise GitFailed(f"git {args[0]}: {r.stderr.strip()[:160]}")
        return None
    return r.stdout


# ---------------------------------------------------------------- журнал проверок

class BadRecord(Exception):
    pass


def load_record(root, strict=False):
    """{"schema": 1, "reviews": {путь: запись}}. Повреждённый журнал при strict — отказ,
    иначе пустой (проверка его не исполняет); record его никогда не перезаписывает."""
    path = os.path.join(root, RECORD)
    if not os.path.exists(path):
        return {"schema": 1, "reviews": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("reviews"), dict):
            raise ValueError("нет словаря reviews")
    except (OSError, ValueError) as exc:
        if strict:
            raise BadRecord(f"{RECORD} повреждён ({exc}); исправь или убери его руками")
        return {"schema": 1, "reviews": {}, "broken": str(exc)}
    reviews, bad = {}, []
    for rel, entry in data["reviews"].items():
        if isinstance(entry, dict) and isinstance(entry.get("blob"), str):
            reviews[rel] = entry
        else:
            bad.append(rel)
    if bad:
        if strict:
            raise BadRecord(f"{RECORD}: повреждены записи {', '.join(bad[:5])}; исправь их руками")
        data["broken"] = f"повреждены записи: {', '.join(bad[:5])}"
    data["reviews"] = reviews
    return data


def unresolved(entry):
    """Подтверждённое, но не исправленное, или названный остаток."""
    try:
        confirmed, fixed = int(entry.get("confirmed") or 0), int(entry.get("fixed") or 0)
    except (TypeError, ValueError):
        return True
    return confirmed > fixed or bool(entry.get("open"))


# ---------------------------------------------------------------- живой канон

def inside_root(root, rel):
    if not rel or os.path.isabs(rel) or rel.split("/")[0] == "..":
        return False
    real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, rel))
    return target == real or target.startswith(real + os.sep)


def canon_files(root):
    """Живой канон: корни знания, цели маршрутов и вход — без журналов, снимков,
    объявленного «вне знания», производных представлений и путей вне корня."""
    path = Path(root)
    roots, _ = kb_index.knowledge_roots(path)
    listed = git(root, "ls-files", "-z", "--", *(roots or ["."]))
    files = {p for p in listed.split("\0") if p.endswith(".md")}
    try:
        index = json.loads((path / kb_index.DEFAULT_INDEX).read_text(encoding="utf-8"))
        for route in index.get("routes", []) if isinstance(index, dict) else []:
            files.update(os.path.normpath(p) for p in kb_index.local_paths(route)
                         if isinstance(p, str) and p.endswith(".md"))
    except (OSError, ValueError):
        pass
    entry = kb_paths.locate(root, "entry").path
    if entry:
        files.add(os.path.relpath(entry, root))
    excluded = kb_index.excluded_globs(path)
    try:
        import kb_check
        inbox = kb_check.inbox_dir(root)
        inbox = os.path.relpath(inbox, root).rstrip("/") + "/" if inbox else None
    except Exception:
        inbox = None
    keep = {}
    for f in sorted(files, key=lambda x: (os.path.islink(path / x), x)):
        if not (inside_root(root, f) and (path / f).is_file() and not JOURNAL.search(f)
                and not kb_index.is_excluded(f, excluded)
                and not (inbox and f.startswith(inbox))
                and not kb_index.is_generated_view(path, f)):
            continue
        keep.setdefault(os.path.realpath(path / f), f)   # одна физическая глава — один путь
    return sorted(keep.values())


def form(text):
    """(байт текста, самая длинная строка текста, заголовков) — вне кода и вне таблиц.

    Строка таблицы — запись справочника, а не абзац: справочник на 50 КБ с одним заголовком
    и длинными строками таблицы правилен (проект 16.10.2026: три ложные горячие главы)."""
    prose = FENCE.sub("", text)
    lines = [line for line in prose.splitlines() if not line.lstrip().startswith("|")]
    longest = max((len(line.encode("utf-8")) for line in lines), default=0)
    size = sum(len(line.encode("utf-8")) + 1 for line in lines)
    return size, longest, len(HEADING.findall(prose))


# ---------------------------------------------------------------- история

def history(root, files):
    """{файл: [(sha, время коммита), …]} от новых к старым — одним вызовом git."""
    if not files:
        return {}
    out = git(root, "log", "--no-merges", "-z", "--name-only", "--format=@@%H %ct", "--",
              *files, timeout=120)
    # Вывод: «@@<sha> <время>\0», затем «\n<первый путь>\0<путь>\0…». Путь сравнивается
    # с запрошенными целиком: «@@имя.md» или перевод строки в имени не ломают разбор.
    wanted, result, current, after_head = set(files), {}, None, False
    for token in out.split("\0"):
        head = re.fullmatch(r"\n?@@([0-9a-f]{40,64}) (\d+)", token)
        if head and token.lstrip("\n") not in wanted:
            current, after_head = (head.group(1), int(head.group(2))), True
            continue
        if after_head and token.startswith("\n"):
            token = token[1:]
        after_head = False
        if token in wanted and current:
            result.setdefault(token, []).append(current)
    return result


def cache_path(root):
    try:
        import kb_service
        folder = kb_service.state_dir("consistency")
    except Exception:
        folder = tempfile.gettempdir()
    return os.path.join(folder, hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:12]
                        + ".json")


def word_balance(root, rel, base, latest, cache):
    """(добавлено, удалено) слов по всем коммитам окна — сумма, а не чистая разница:
    чистая разница от пустого дерева не видит удалений вовсе."""
    key = f"{rel}\0{base or ''}\0{latest}"
    hit = cache.get(key)
    if isinstance(hit, list) and len(hit) == 2 and all(isinstance(x, int) and x >= 0 for x in hit):
        return tuple(hit)
    rng = [f"{base}..HEAD"] if base else ["HEAD"]
    out = git(root, "log", "--no-merges", "-p", "--word-diff=porcelain", "--format=@@%h",
              *rng, "--", rel, timeout=180)
    added = removed = 0
    for line in out.splitlines():
        if line.startswith(("+++ ", "--- ", "diff ", "index ", "@@")):
            continue
        if line[:1] == "+":
            added += len(line[1:].split())
        elif line[:1] == "-":
            removed += len(line[1:].split())
    cache[key] = [added, removed]
    return added, removed


def signals(root, today=None, only=None):
    """Горячие главы и статус согласованности (см. описание модуля)."""
    today = today or datetime.date.today()
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir"], capture_output=True,
                           text=True, timeout=30)
        not_repo = r.returncode != 0 and "not a git repository" in r.stderr.lower()
        failed = r.returncode != 0 and not not_repo
    except (OSError, subprocess.TimeoutExpired) as exc:
        not_repo, failed, r = False, True, None
    if not_repo:
        return {"status": "NOT_APPLICABLE", "reason": "не Git-репозиторий", "chapters": [],
                "pending": 0, "files": 0}
    if failed:
        return {"status": "UNKNOWN", "reason": "git не ответил на rev-parse", "chapters": [],
                "pending": 0, "files": 0}
    try:
        return _signals(root, today, only)
    except GitFailed as exc:
        return {"status": "UNKNOWN", "reason": f"git не ответил ({exc})", "chapters": [],
                "pending": 0, "files": 0}


def _signals(root, today, only):
    files = canon_files(root)
    if only is not None:
        files = [f for f in files if f == only or f.startswith(only.rstrip("/") + "/")]
    record = load_record(root)
    # Запись ищется по физической главе: путь через симлинк и сама глава — одно и то же.
    reviews = {}
    for key, entry in record["reviews"].items():
        reviews.setdefault(os.path.realpath(os.path.join(root, key)), (key, entry))
    hist = history(root, files)
    cutoff = datetime.datetime.combine(today - datetime.timedelta(days=LIMITS["window_days"]),
                                       datetime.time()).timestamp()
    try:
        with open(cache_path(root), encoding="utf-8") as f:
            cache = json.load(f)
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    size_before = len(cache)
    chapters, unreadable = [], []
    for rel in files:
        commits = hist.get(rel, [])
        review = reviews.pop(os.path.realpath(os.path.join(root, rel)), (None, None))[1]
        base = review.get("commit") if review else None
        if base and not (isinstance(base, str) and re.fullmatch(r"[0-9a-f]{7,64}", base)
                         and git(root, "cat-file", "-e", base + "^{commit}", required=False) is not None):
            base = None                       # недоступный коммит проверки — окно по всей истории
        if base:
            after = git(root, "rev-list", "--no-merges", f"{base}..HEAD", "--", rel)
            window = len([x for x in after.split() if x])
        else:
            window = len(commits)
        recent = sum(1 for _, ts in commits if ts >= cutoff)
        reasons = []
        try:
            text = (Path(root) / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            unreadable.append(rel)
            text = ""
            reasons.append(f"не прочитана: {type(exc).__name__}")
        size, longest, headings = form(text)
        if text and window >= LIMITS["commits"] and size >= LIMITS["size"] and commits:
            added, removed = word_balance(root, rel, base, commits[0][0], cache)
            if added >= LIMITS["words"] and removed < LIMITS["ratio"] * added:
                since = "с последней проверки" if base else "за всю историю главы"
                reasons.append(f"рост без замены {since}: коммитов {window}, слов +{added}/−{removed}")
        per_heading = size / max(headings, 1)
        if text and recent >= LIMITS["form_commits"] and (
                longest > LIMITS["line"]
                or (size >= LIMITS["form_size"] and per_heading > LIMITS["per_heading"])):
            reasons.append(f"форма: самая длинная строка {longest / 1024:.1f} КБ, заголовков "
                           f"{headings} на {size // 1024} КБ")
        current = git(root, "hash-object", "--", rel).strip() if review and text else None
        reviewed = bool(review and current and review.get("blob") == current)
        conflict = bool(review and unresolved(review))
        if conflict:
            reasons.append("известные противоречия не исправлены: подтверждено "
                           f"{review.get('confirmed')}, исправлено {review.get('fixed')}"
                           + (f"; осталось: {'; '.join(map(str, review.get('open') or []))}"
                              if review.get("open") else ""))
        if not reasons:
            continue
        chapters.append({"path": rel, "reasons": reasons, "commits": window, "recent": recent,
                         "bytes": size, "longest_line": longest, "headings": headings,
                         "reviewed": reviewed and not conflict, "conflict": conflict,
                         "last_review": review.get("date") if review else None})
    # Неисправленное под исчезнувшим именем (переименование, удаление) не пропадает молча.
    for real, (key, entry) in reviews.items():
        if unresolved(entry) and (only is None or key == only or key.startswith(only.rstrip("/") + "/")) \
                and not os.path.exists(real):
            chapters.append({"path": key, "reasons": [
                "запись о неисправленных противоречиях для главы, которой больше нет: найди её "
                "новое имя, проверь и запиши заново (или запиши исход для старого имени)"],
                "commits": 0, "recent": 0, "bytes": 0, "longest_line": 0, "headings": 0,
                "reviewed": False, "conflict": True, "last_review": entry.get("date")})
    if len(cache) != size_before:
        try:
            tmp = cache_path(root) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp, cache_path(root))
        except OSError:
            pass
    pending = [c for c in chapters if not c["reviewed"] and not c["conflict"]]
    conflicts = [c for c in chapters if c["conflict"]]
    status = "FAIL" if conflicts else "PENDING" if pending else "PASS"
    state = {"status": status, "files": len(files), "chapters": chapters,
             "pending": len(pending), "conflicts": len(conflicts)}
    problems = ([f"журнал {RECORD}: {record['broken']}"] if record.get("broken") else []) + \
               ([f"не прочитаны: {', '.join(unreadable[:5])}"] if unreadable else [])
    if problems and status != "FAIL":
        # Без журнала или файла нельзя знать, нет ли там неисправленного: не «чисто».
        state.update(status="UNKNOWN", reason="; ".join(problems))
    elif problems:
        state["reason"] = "; ".join(problems)
    return state


def status_line(state):
    """Строка охвата для kb_check и плана."""
    status = state["status"]
    if status in ("NOT_APPLICABLE", "UNKNOWN"):
        word = "НЕ ПРОВЕРЕНО" if status == "UNKNOWN" else "NOT_APPLICABLE"
        return f"согласованность — {word} ({state['reason']})"
    tail = f"; {state['reason']}" if state.get("reason") else ""
    if status == "FAIL":
        names = ", ".join(c["path"] for c in state["chapters"] if c["conflict"])
        return f"согласованность — FAIL: известные противоречия не исправлены ({names}){tail}"
    if status == "PENDING":
        names = ", ".join(c["path"] for c in state["chapters"] if not c["reviewed"])
        return f"согласованность — PENDING: горячих глав без проверки {state['pending']} ({names}){tail}"
    done = [c for c in state["chapters"] if c["reviewed"]]
    return ("согласованность — PASS: " + (f"горячие главы прочитаны в этой версии ({len(done)})"
                                          if done else f"сигналов нет ({state['files']} файлов канона)")
            + tail)


def last_service_sha(root):
    try:
        import kb_service
        return kb_service.last_service(root)[1]
    except Exception:
        return None


def evicted(root, base, limit=12):
    """Куски строк со словом статуса, выпавшие из входа с base, — список для чтения,
    не долг: пересказ и перенос отсюда не отличить (строку сокращают, а не удаляют)."""
    entry = kb_paths.locate(root, "entry").path
    if not entry or not base:
        return []
    rel = os.path.relpath(entry, root)
    out = git(root, "diff", "--no-color", "--word-diff=porcelain", base, "--", rel,
              required=False) or ""
    pieces, line, removed = [], [], []
    for row in out.splitlines():
        if row.startswith(("+++ ", "--- ", "diff ", "index ", "@@")):
            continue
        if row == "~":
            gone = " ".join(removed).strip()
            if gone and len(gone) >= 15 and STATUS.search(" ".join(line)):
                pieces.append(gone[:220])
            line, removed = [], []
        elif row[:1] in " -":
            line.append(row[1:])
            if row[0] == "-":
                removed.append(row[1:])
    return pieces[:limit]


def heavy_routes(root):
    """[(маршрут, байт)] дороже порога — справка с подсказкой section-целей."""
    path = Path(root)
    try:
        index = json.loads((path / kb_index.DEFAULT_INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = []
    for route in index.get("routes", []) if isinstance(index, dict) else []:
        units = []
        for item in kb_index.targets(route):
            if not isinstance(item, dict) or item.get("kind") == "project":
                continue
            rel = str(item.get("path", ""))
            target = path / rel
            if not inside_root(root, rel) or not target.is_file():
                continue
            try:
                span = (kb_index.section_span(target, item["section"])
                        if item.get("kind") == "section" else (0, target.stat().st_size))
            except (ValueError, KeyError, OSError):
                span = (0, target.stat().st_size)
            units.append((target, *span))
        cost = kb_index.read_set_bytes(units)
        if cost > LIMITS["route"]:
            rows.append((str(route.get("id") or route.get("task") or "?"), cost))
    return sorted(rows, key=lambda r: -r[1])


def area_card(root, rel):
    """Строки перед записью в область: горячая ли она и чем. Считает только область."""
    rel = (os.path.relpath(os.path.realpath(os.path.join(root, rel)), os.path.realpath(root))
           if os.path.isabs(rel) else os.path.normpath(rel))
    state = signals(root, only=rel)
    lines = []
    for c in state.get("chapters", []):
        mark = ("известные противоречия не исправлены" if c["conflict"]
                else "прочитана в этой версии" if c["reviewed"] else "не проверена на противоречия")
        lines.append(f"горячая глава {c['path']} ({mark}): " + "; ".join(c["reasons"]))
    if lines:
        lines.append("Пишешь сюда — правь на месте: новое заменяет старое, копии найди цитатой и "
                     "замени ссылкой, закрытое убери; дописывать в конец поверх прежнего нельзя.")
    return lines


# ---------------------------------------------------------------- проверка моделью

REVIEW = """ПРОВЕРКА СОГЛАСОВАННОСТИ. Прочитай целиком файл {rel} в этом каталоге. Ничего не меняй.
Найди места, где глава противоречит себе: два разных действующих утверждения об одном предмете
(число, срок, роль, правило, владелец); «открыто/ждём», которое в той же главе уже сделано или
решено; правило, заменённое более поздним решением, но оставшееся как действующее. Разница
формулировок, разные предметы, явная история («до 08.10 было …») — не противоречие.
Если файл прочитать не удалось, ответь одним словом НЕ_ПРОЧИТАНО.
Иначе ответь только JSON-списком, не больше 30 элементов, без текста вокруг:
[{{"subject": "предмет", "a": "точная цитата 1", "a_line": номер строки, "b": "точная цитата 2",
"b_line": номер строки, "confidence": "high|medium|low", "check": "чем проверить: код, система, git, владелец"}}]
Пустой список [], если противоречий нет."""


def parse_review(text):
    """Список находок или None: ответ — ровно JSON-список (допустим блок ```json), у каждой
    находки предмет, две цитаты и уверенность. Иначе проверка не состоялась."""
    body = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.S)
    if fenced:
        body = fenced.group(1)
    if "НЕ_ПРОЧИТАНО" in body:
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    if not isinstance(value, list):
        return None
    for item in value:
        if not (isinstance(item, dict)
                and all(isinstance(item.get(k), str) and item[k].strip()
                        for k in ("subject", "a", "b", "check"))
                and all(isinstance(item.get(k), int) and item[k] > 0 for k in ("a_line", "b_line"))
                and item.get("confidence") in CONFIDENCE):
            return None
    return value


def review(root, chapter=None, agent=None, force=False, print_prompt=False):
    import kb_service
    if chapter:
        chapter = os.path.normpath(chapter)
        if not inside_root(root, chapter) or not (Path(root) / chapter).is_file():
            print(f"REVIEW_FAILED {chapter}: файла нет в корне проекта")
            return 1
        todo = [chapter]
    else:
        state = signals(root)
        if state["status"] in ("UNKNOWN", "NOT_APPLICABLE"):
            print(f"REVIEW_FAILED: {status_line(state)}")
            return 1
        todo = [c["path"] for c in state.get("chapters", []) if not c["reviewed"]]
    if not todo:
        print("REVIEW_NOTHING: горячих глав без проверки нет")
        return 0
    if print_prompt:
        for rel in todo:
            print(f"## задание для {rel}\n{REVIEW.format(rel=rel)}")
        print("REVIEW_PROMPT_ONLY: модель не запускалась; задание выше можно отдать агенту самому")
        return 0
    # 8.3.2 (продукт на Odoo, отчёт 26.10 §4): до запуска — кто и с каким пределом; своп почти полон — не стартовать.
    print(f"REVIEW_RUN: {kb_service.agent_label(agent)}, предел {kb_service.AGENT_TIMEOUT} с на главу, "
          f"глав {len(todo)}; только задание — --print-prompt")
    # Подставной агент (KB_AGENT_CMD, тесты и пилоты) — не модель: защита свопа его не касается.
    pct, note = kb_service.swap_usage() if not os.environ.get("KB_AGENT_CMD") else (None, "")
    if pct is not None and pct > 70 and not force:
        print(f"REVIEW_BLOCKED: своп занят {pct:.0f} % ({note}) — параллельная модель замедлит или "
              "уронит соседние сессии; подожди, освободи память или запусти с --force")
        return 1
    failed = False
    for rel in todo:
        try:
            text = kb_service.run_agent(REVIEW.format(rel=rel), root, family=agent, check=True)
        except Exception as exc:
            print(f"REVIEW_FAILED {rel}: агент не отработал ({type(exc).__name__}: {exc})")
            failed = True
            continue
        found = parse_review(text)
        if found is None:
            print(f"REVIEW_FAILED {rel}: ответ агента — не список находок; проверка не состоялась")
            failed = True
            continue
        high = [x for x in found if x.get("confidence") == "high"]
        print(f"## {rel}: находок {len(found)}, высокой уверенности {len(high)}")
        for x in sorted(found, key=lambda x: {"high": 0, "medium": 1}.get(x.get("confidence"), 2)):
            print(f"- [{x.get('confidence')}] {x.get('subject')}: "
                  f"стр. {x.get('a_line')} «{str(x.get('a'))[:160]}» ⟷ "
                  f"стр. {x.get('b_line')} «{str(x.get('b'))[:160]}» — {x.get('check')}")
    print("\nНаходки — данные, не истина. Сверь каждую с источником правды проекта, исправь "
          "подтверждённое точной заменой, затем запиши исход: python3 "
          f"{os.path.abspath(__file__)} record <корень> <глава> --found N --confirmed M --fixed K "
          "[--open \"…\"] [--by \"…\"].")
    return 1 if failed else 0


def record(root, rel, found, confirmed, fixed, open_items, by):
    rel = os.path.normpath(rel)
    if not inside_root(root, rel):
        print(f"RECORD_REFUSED: нет файла {rel} в корне проекта")
        return 2
    if not (Path(root) / rel).exists():
        # Исход для исчезнувшей главы: снять запись о неисправленном можно только явным исходом.
        try:
            data = load_record(root, strict=True)
        except BadRecord as exc:
            print(f"RECORD_REFUSED: {exc}")
            return 2
        if rel in data["reviews"] and fixed == confirmed and not open_items:
            del data["reviews"][rel]
            write_record(root, data)
            print(f"RECORDED: запись для исчезнувшей {rel} снята — исход: исправлено {fixed} из {confirmed}")
            return 0
        print(f"RECORD_REFUSED: нет файла {rel} в корне проекта")
        return 2
    rel = os.path.relpath(os.path.realpath(os.path.join(root, rel)), os.path.realpath(root))
    if not (Path(root) / rel).is_file():
        print(f"RECORD_REFUSED: нет файла {rel} в корне проекта")
        return 2
    if git(root, "ls-files", "--error-unmatch", "--", rel, required=False) is None:
        print(f"RECORD_REFUSED: {rel} не отслеживается Git — отметка не переживёт clone")
        return 2
    if min(found, confirmed, fixed) < 0 or confirmed > found or fixed > confirmed:
        print("RECORD_REFUSED: нужно 0 ≤ исправлено ≤ подтверждено ≤ найдено")
        return 2
    try:
        data = load_record(root, strict=True)
        current = git(root, "hash-object", "--", rel).strip()
        head = git(root, "rev-parse", "HEAD").strip()
    except (BadRecord, GitFailed) as exc:
        print(f"RECORD_REFUSED: {exc}")
        return 2
    data.pop("broken", None)
    data["reviews"][rel] = {"blob": current, "commit": head,
                            "date": datetime.date.today().isoformat(), "by": by,
                            "found": found, "confirmed": confirmed, "fixed": fixed,
                            "open": open_items}
    write_record(root, data)
    left = confirmed > fixed or open_items
    print(f"RECORDED: {rel} — найдено {found}, подтверждено {confirmed}, исправлено {fixed}"
          + (f", осталось: {'; '.join(open_items)}" if open_items else "")
          + (". Статус главы — FAIL, пока остаток не исправлен и не записан заново" if left else "")
          + f". Закоммить {RECORD} вместе с правкой главы.")
    return 0


def write_record(root, data):
    fd, tmp = tempfile.mkstemp(prefix=".kb-consistency-", dir=root)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, os.path.join(root, RECORD))


def print_state(root, state):
    print(status_line(state))
    for c in state.get("chapters", []):
        mark = ("НЕ ИСПРАВЛЕНО" if c["conflict"] else "прочитана" if c["reviewed"] else "НЕ ПРОВЕРЕНА")
        print(f"  {mark}: {c['path']} — " + "; ".join(c["reasons"]))
    if state["status"] in ("PENDING", "FAIL"):
        print(f"Проверь: python3 {os.path.abspath(__file__)} review {root} "
              "[--agent codex|claude — другого семейства, чем писавший]; затем `record`.")


def main(argv):
    args = list(argv)
    if args and args[0] in ("review", "record"):
        cmd, args = args[0], args[1:]
    else:
        cmd = "status"
    if not args or not os.path.isdir(args[0]):
        print(__doc__)
        return 2
    root = os.path.abspath(args[0])

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            return args[i + 1] if i + 1 < len(args) else default
        return default

    if cmd == "review":
        return review(root, chapter=opt("--chapter"), agent=opt("--agent"),
                      force="--force" in args, print_prompt="--print-prompt" in args)
    if cmd == "record":
        if len(args) < 2:
            print("record <корень> <путь> --found N --confirmed M --fixed K")
            return 2
        try:
            nums = [int(opt(k, "0")) for k in ("--found", "--confirmed", "--fixed")]
        except ValueError:
            print("--found, --confirmed, --fixed — числа")
            return 2
        open_items = [opt("--open")] if opt("--open") else []
        return record(root, args[1], *nums, open_items, opt("--by", "не указан"))
    if "--area" in args:
        for line in area_card(root, opt("--area", "")):
            print(line)
        return 0
    state = signals(root)
    if "--json" in args:
        print(json.dumps(state, ensure_ascii=False, indent=1))
    else:
        print_state(root, state)
    return 0 if state["status"] in ("PASS", "NOT_APPLICABLE") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
