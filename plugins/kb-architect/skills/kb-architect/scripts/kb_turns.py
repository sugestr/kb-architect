#!/usr/bin/env python3
"""
kb_turns.py — реестр ходов: что агент сделал за ход и дошло ли это до базы.

Модуль hook'а `kb_start.py` (UserPromptSubmit, PreToolUse, Stop; необязательные
PostToolUse/Failure для результатов) и
инструмент замера:

    python3 kb_turns.py <корень проекта> [--days 7] [--json]   # сводка реестра

Почему. Аудит 02.10.2026: агенты пишут знание, но неполно и не туда; самопроверка
зелёная, пока провал идёт. До любых напоминаний агенту (шаг 3 плана) нужен честный
замер по каждому ходу и точность классификации действий (шаг 1: тихий режим).

Что записывается. В начале хода — отпечаток рабочей копии проекта (свой файл, не
состояние сессии): HEAD и изменённые файлы с mtime/размером, только внутри корня
проекта. По ходу — классы следствий разрешённых инструментов, БЕЗ текста команд, имён
хостов и адресов (в командах бывают значения доступов): «точно» — распознанная попытка
правки файла, git-записи, удалённого изменения, HTTP/MCP-записи, деплоя; «неясно» — прочая
оболочка и скрипты. Для правки файла хранится путь в проекте — чтобы в конце хода
отличить базу от работы. В конце хода — какие файлы проекта изменились: коммиты,
сделанные в этой рабочей копии за ход (по reflog; подтянутые `pull` не считаются), и
правки рабочей копии. База — по определению kb_debts.knowledge_paths. Строка реестра —
`~/.cache/kb-architect/entry/turns/<проект>.jsonl`, ротация после 5 МБ.
Внешний аудит 03.10.2026: `certain` — уверенность классификации, не успех; `outcomes`
и `certain_succeeded` подтверждают результат только при событии после инструмента.
Общий Git-каталог объединяет новые строки worktree; CLI исключает старые поколения.

Границы. Ход, прерванный до конца (Esc, ошибка API), записывается при следующей
реплике как прерванный. Переименование видно как новый путь; подмодули не видны;
параллельные сессии в одной рабочей копии видят правки друг друга. Это замер, не суд.
"""

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DECISION = re.compile(r"(?:решени|решил|правил[оа]|всегда\b|никогда\b|запомни|впредь|отныне|"
                      r"договорились|принимаю|утверждаю|согласен|делаем так)", re.IGNORECASE)
GIT_WRITE = {"commit", "push", "merge", "rebase", "reset", "cherry-pick", "revert", "am",
             "tag", "stash", "checkout", "switch", "restore", "rm", "mv", "pull"}
REMOTE = {"ssh", "scp", "rsync", "sftp"}
HTTP = {"curl", "wget", "http", "https"}
SCRIPT = re.compile(r"^(?:python(?:3(?:\.\d+)?)?|node|ruby|perl|bash|sh|zsh|php|deno|bun)$")
DEPLOY = re.compile(r"deploy|release|migrate|six_", re.IGNORECASE)
LOCAL_COMMIT = ("commit", "cherry-pick", "revert", "am")
MAX_DIRTY = 4000
ROTATE_BYTES = 5_000_000
# Внешний аудит 03.10.2026: общий бюджет меньше timeout hook'а; reflog ограничен.
GIT_BUDGET = 8
REFLOG_LIMIT = 501
DEADLINE = ContextVar("kb_turns_deadline", default=None)


@contextmanager
def git_budget():
    token = DEADLINE.set(DEADLINE.get() or time.monotonic() + GIT_BUDGET)
    try:
        yield
    finally:
        DEADLINE.reset(token)


@contextmanager
def file_lock(path):
    """Внешний аудит 03.10.2026: межпроцессный замок рядом с изменяемым файлом."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = DEADLINE.get() or time.monotonic() + GIT_BUDGET
    with open(path + ".lock", "a", encoding="utf-8") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("реестр: ожидание блокировки истекло")
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def state_root():
    return os.environ.get("KB_ENTRY_STATE") or os.path.join(
        os.path.expanduser("~"), ".cache", "kb-architect", "entry")


def root_key(root):
    canonical, _ = project_identity(root)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def project_identity(root):
    """Внешний аудит 03.10.2026: общий проект worktree, подпроекты не склеиваются."""
    root = os.path.realpath(root)
    out = git(root, "rev-parse", "--git-common-dir", "--git-dir", "--show-prefix", timeout=1)
    if out is None:
        return root, False
    lines = out.decode("utf-8", "replace").splitlines()
    if not lines:
        return root, False
    common = os.path.realpath(os.path.join(root, lines[0]))
    git_dir = os.path.realpath(os.path.join(root, lines[1])) if len(lines) > 1 else common
    prefix = lines[2] if len(lines) > 2 else ""
    # Отдельные --separate-git-dir в одном каталоге не должны получить один ключ.
    base = os.path.dirname(common) if os.path.basename(common) == ".git" else common
    canonical = os.path.realpath(os.path.join(base, prefix))
    return canonical, git_dir != common


def git(root, *args, timeout=20):
    deadline = DEADLINE.get()
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            return None
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=timeout,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def repo_prefix(root):
    """Путь корня проекта внутри репозитория (проект бывает подпапкой большого)."""
    out = git(root, "rev-parse", "--show-prefix")
    return out.decode("utf-8", "replace").strip() if out is not None else ""


def project_rel(path, prefix):
    """Путь от корня репозитория → путь от корня проекта; вне проекта — None."""
    if not prefix:
        return path
    return path[len(prefix):] if path.startswith(prefix) else None


def dirty_files(root, prefix):
    """({путь: [mtime_ns, size]}, обрезано?) для изменённых и новых файлов проекта."""
    out = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".")
    if out is None:
        return None, False
    items, truncated, entries, i = {}, False, out.split(b"\0"), 0
    while i < len(entries):
        item = entries[i]
        i += 1
        if len(item) < 4:
            continue
        code, rel = item[:2], project_rel(item[3:].decode("utf-8", "replace"), prefix)
        if code[:1] in (b"R", b"C"):
            i += 1                                   # исходное имя переименования
        if rel is None:
            continue
        if len(items) >= MAX_DIRTY:
            truncated = True
            break
        try:
            st = os.stat(os.path.join(root, rel))
            items[rel] = [st.st_mtime_ns, st.st_size]
        except OSError:
            items[rel] = [0, -1]                     # удалён
    return items, truncated


def reflog(root):
    """[(sha, тема)] записей HEAD, новые первыми; None — reflog недоступен."""
    out = git(root, "reflog", "show", f"-n{REFLOG_LIMIT}", "--format=%H%x09%gs", "HEAD")
    if out is None:
        return None
    rows = []
    for line in out.decode("utf-8", "replace").splitlines():
        sha, _, subject = line.partition("\t")
        rows.append((sha, subject))
    return rows


def snapshot(root):
    with git_budget():
        prefix = repo_prefix(root)
        head = git(root, "rev-parse", "HEAD")
        dirty, truncated = dirty_files(root, prefix)
        log = reflog(root)
    return {"at": time.time(), "head": head.decode().strip() if head else None,
            "reflog_n": len(log) if log is not None else None,
            "reflog_cursor": list(log[0]) if log else None,
            "incomplete": head is None or dirty is None or log is None,
            "dirty": dirty, "truncated": truncated}


def local_commits(root, snap):
    """Коммиты, созданные в этой рабочей копии за ход: новые записи reflog HEAD с темой
    commit / cherry-pick / revert / am. Подтянутые pull, checkout и merge сюда не входят.
    Счёт — по числу новых записей, а не по времени: часы и даты коммитов не важны."""
    log = reflog(root)
    before = snap.get("reflog_n")
    if log is None or before is None:
        snap["end_incomplete"] = True
        return []
    cursor = snap.get("reflog_cursor")
    if cursor:
        # Внешний аудит 03.10.2026: длина ограниченного reflog перестаёт расти.
        new = next((i for i, row in enumerate(log) if list(row) == cursor), None)
        if new is None:
            snap["end_incomplete"] = True
            return []
    else:
        new = len(log) - before
    if new <= 0 or new > 500:
        return []
    return [sha for sha, subject in log[:new]
            if subject.split(":", 1)[0].split(" ", 1)[0] in LOCAL_COMMIT]


def commit_files(root, shas, prefix):
    files = set()
    for sha in shas:
        out = git(root, "show", "-z", "--name-only", "--format=", sha, "--", ".")
        if not out:
            continue
        for raw in out.split(b"\0"):
            rel = project_rel(raw.decode("utf-8", "replace").strip(), prefix)
            if rel:
                files.add(rel)
    return files


def changed_since(root, snap):
    """Файлы проекта, изменённые за ход: свои коммиты хода и правки рабочей копии."""
    with git_budget():
        return _changed_since(root, snap)


def _changed_since(root, snap):
    if not snap:
        return set()
    prefix = repo_prefix(root)
    changed = set()
    shas = local_commits(root, snap)
    if shas:
        changed |= commit_files(root, shas, prefix)
    before = snap.get("dirty") or {}
    now, truncated = dirty_files(root, prefix)
    snap["end_incomplete"] = bool(snap.get("end_incomplete") or now is None or truncated
                                  or snap.get("truncated") or snap.get("dirty") is None)
    now = now or {}
    if snap.get("dirty") is not None:
        for rel, sig in now.items():
            if before.get(rel) != sig and (rel in before or not (truncated or snap.get("truncated"))):
                changed.add(rel)
    # Внешний аудит 03.10.2026: исчезновение грязного файла после отката — не запись.
    # Собственные коммиты уже учтены выше, удаления остаются в status с [0, -1].
    return changed


def split_knowledge(root, files):
    try:
        import kb_debts
        know = kb_debts.knowledge_paths(root, sorted(files))
    except Exception:
        know = {f for f in files if f.lower().endswith((".md", ".markdown"))}
    return sorted(know), sorted(set(files) - set(know))


# Реплики среды, а не владельца. Claude Code отдаёт hook'у UserPromptSubmit и уведомление о
# фоновой задаче, и сообщение другой сессии: 02.10 в одной сессии 97 уведомлений резали ходы
# на куски («прервано» — треть ходов) и по словам из отчётов агентов считались решениями.
# Только с начала текста: владелец, цитирующий такую метку, остаётся владельцем (ревью 7.6.1).
MACHINE_PROMPTS = (
    ("notification", re.compile(r"\A\s*(?:\[SYSTEM NOTIFICATION[^\]\n]*\][^<]{0,400})?<task-notification>")),
    ("peer", re.compile(r"\A\s*(?:Another Claude session sent a message:\s*<"
                        r"|<cross-session-message\b|<agent-message\b)")))


def prompt_kind(prompt):
    """human | notification | peer — по началу текста реплики."""
    text = str(prompt or "")
    for kind, rx in MACHINE_PROMPTS:
        if rx.match(text):
            return kind
    return "human"


def is_decision(prompt):
    return (bool(prompt) and prompt_kind(prompt) == "human"
            and bool(DECISION.search(prompt)))


def git_subcommand(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in ("-C", "-c") and i + 1 < len(args):
            i += 2
            continue
        i += 1
    return args[i] if i < len(args) else ""


def partial_segments(cmd):
    """Внешний аудит 03.10.2026: узнаваемые команды вне тела heredoc сохраняются.
    Это только сбор кандидатов; неподдержанная оболочка остаётся uncertain."""
    segments, delimiters = [], []
    for line in cmd.splitlines():
        if delimiters:
            delimiter, tabs = delimiters[0]
            if (line.lstrip("\t") if tabs else line) == delimiter:
                delimiters.pop(0)
            continue
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            tokens = list(lex)
        except ValueError:
            continue
        current = []
        for i, tok in enumerate(tokens):
            if tok == "<<" and i + 1 < len(tokens):
                delimiter = tokens[i + 1]
                tabs = delimiter.startswith("-")
                delimiters.append((delimiter[1:] if tabs else delimiter, tabs))
            if tok in (";", "&&", "||", "|", "&"):
                if current:
                    segments.append(current)
                current = []
            elif re.match(r"^[();<>|&]+$", tok):
                if current:
                    segments.append(current)
                current = []
            else:
                current.append(tok)
        if current:
            segments.append(current)
    return segments


def remote_effects(words, read_only, depth):
    """Внешний аудит 03.10.2026: SSH классифицируется по удалённой команде."""
    name, args = os.path.basename(words[0]), words[1:]
    if name == "ssh":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            option = args[i]
            if option == "--":
                i += 1
                break
            # ProxyCommand/LocalCommand и неизвестные опции могут исполнять код.
            if option.startswith("-o") or option.startswith("-F"):
                return [("uncertain", "remote")]
            if option in ("-p", "-i", "-l", "-J", "-b", "-c", "-D", "-E", "-L", "-R", "-S", "-W", "-w"):
                i += 2
            elif option in ("-T", "-t", "-tt", "-q", "-v", "-vv", "-vvv", "-n", "-4", "-6", "-A", "-a", "-C", "-x", "-X", "-Y"):
                i += 1
            else:
                return [("uncertain", "remote")]
        payload = " ".join(args[i + 1:])
        if not payload or depth >= 4:
            return [("uncertain", "remote")]
        import kb_start
        effects = shell_effects(payload, kb_start.shell_segments(payload), read_only, depth + 1)
        return [(c, "remote" if c == "uncertain" else k) for c, k in effects]
    if name in ("scp", "rsync"):
        positional, i = [], 0
        with_value = {"-e", "-P", "-S", "-i", "-o", "-F",
                      "--exclude", "--include", "--filter", "--rsh", "--files-from"}
        while i < len(args):
            if args[i] in with_value:
                i += 2
                continue
            if not args[i].startswith("-"):
                positional.append(args[i])
            i += 1
        if len(positional) >= 2 and re.match(r"^(?:[^/]+:|rsync://)", positional[-1]):
            if name == "rsync" and any(a in ("-n", "--dry-run") for a in args):
                return [("uncertain", "remote")]
            return [("certain", "remote")]
    return [("uncertain", "remote")]


def http_effects(words):
    """Внешний аудит 03.10.2026: метод, тело и локальный файл HTTP различаются."""
    name, args = os.path.basename(words[0]), words[1:]
    method, body, writes_file, unknown = "GET", False, name == "wget", False
    for i, arg in enumerate(args):
        flag, _, value = arg.partition("=")
        if arg in ("-X", "--request", "--method"):
            method = args[i + 1].upper() if i + 1 < len(args) else "?"
        elif flag in ("--request", "--method"):
            method = value.upper()
        elif arg.startswith("-X"):
            method = arg[2:].upper()
        if flag.startswith("--data") or flag in ("--form", "--json", "--upload-file", "--post-data", "--post-file") \
                or arg.startswith(("-d", "-F", "-T")):
            body = True
        if arg in ("-o", "--output", "-O", "--output-document", "--remote-name"):
            writes_file = arg in ("-O", "--remote-name") and name == "curl" or i + 1 >= len(args) or args[i + 1] not in ("/dev/null", "-")
        elif flag in ("--output", "--output-document") and value:
            writes_file = value not in ("/dev/null", "-")
        elif arg.startswith("-o") and len(arg) > 2:
            writes_file = arg[2:] not in ("/dev/null", "-")
        if flag in ("--config", "-K"):
            unknown = True
    if name in ("http", "https") and args and args[0].upper() in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"):
        method = args[0].upper()
    effects = [("certain", "file")] if writes_file else []
    if body or method not in ("GET", "HEAD", "OPTIONS"):
        effects.append(("certain", "http"))
    if unknown:
        effects.append(("uncertain", "http"))
    return effects


def shell_effects(cmd, segments, read_only, depth=0):
    """[(класс, вид)] для команды оболочки — без текста, хостов и адресов."""
    if read_only(cmd):
        return []
    incomplete = segments is None
    if incomplete:
        segments = partial_segments(cmd)
    effects = [("uncertain", "shell")] if incomplete else []
    for words in segments:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if not words or read_only(shlex.join(words)):
            continue
        name = os.path.basename(words[0])
        if name == "git" and git_subcommand(words[1:]) in GIT_WRITE:
            effects.append(("certain", "git"))
        elif name in REMOTE:
            effects.extend(remote_effects(words, read_only, depth))
        elif name in HTTP:
            effects.extend(http_effects(words))
        elif name in ("cp", "mv", "rm", "mkdir", "touch", "chmod"):
            effects.append(("certain", "file"))
        elif name in ("kill", "pkill"):
            effects.append(("certain", "process"))
        elif name in ("systemctl", "service") and any(a in ("start", "stop", "restart", "reload", "enable", "disable") for a in words[1:]):
            effects.append(("certain", "process"))
        elif any(w.endswith(".sh") and DEPLOY.search(os.path.basename(w)) for w in words[:3]):
            effects.append(("certain", "deploy"))
        elif SCRIPT.match(name):
            effects.append(("uncertain", "script"))
        else:
            effects.append(("uncertain", "shell"))
    return effects


def snap_path(sid, root):
    # Внешний аудит 03.10.2026: отпечатки остаются отдельными для каждого worktree.
    key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:12]
    return os.path.join(state_root(), "turns", "snap",
                        f"{re.sub(r'[^A-Za-z0-9._-]', '_', str(sid))[:120]}--{key}.json")


def save_snap(sid, root, snap):
    path = snap_path(sid, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f)
    os.replace(tmp, path)


def load_snap(sid, root):
    try:
        with open(snap_path(sid, root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def registry_path(root, key=None):
    return os.path.join(state_root(), "turns", (key or root_key(root)) + ".jsonl")


def record(root, row):
    path = registry_path(root, row.get("project_key"))
    with file_lock(path):
        try:
            if os.path.getsize(path) > ROTATE_BYTES:
                os.replace(path, path + ".1")
        except FileNotFoundError:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def summary(root, days=7, whole_only=False, since_epoch=None):
    """Сводка реестра проекта за N дней: ходы со следствиями и с записью в базу.
    whole_only — только ходы, которые служебные реплики уже не режут (строки с `trigger`,
    с 7.6.1): по ним считает сигнал обхода."""
    # Внешний аудит 03.10.2026: обход сбрасывает счёт в точное время коммита;
    # возраст полного реестра не зависит от выбранного окна подсчёта.
    limit = since_epoch if since_epoch is not None else time.time() - days * 86400
    rows = []
    first_trigger_ts = None
    for path in (registry_path(root) + ".1", registry_path(root)):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    ts = row.get("ts_epoch", 0)
                    if "trigger" in row:
                        first_trigger_ts = ts if first_trigger_ts is None else min(first_trigger_ts, ts)
                    if ts >= limit and (not whole_only or "trigger" in row):
                        rows.append(row)
        except OSError:
            pass
    certain = [r for r in rows if r.get("certain")]
    # Внешний аудит 03.10.2026: попытка — не результат. Пока события результата (PostToolUse) не
    # установлены, исход неизвестен, и точное следствие считается работой, как до 7.7; когда
    # результат пришёл, считается только удавшееся.
    def observed(r):
        o = r.get("outcomes") or {}
        return (o.get("succeeded", 0) + o.get("failed", 0)) > 0
    work = [r for r in rows if r.get("work_files") or r.get("certain_succeeded")
            or (r.get("certain") and not observed(r))]
    return {
        "turns": len(rows),
        "interrupted": sum(1 for r in rows if r.get("interrupted")),
        "turns_with_work": len(work),
        "work_recorded": sum(1 for r in work if r.get("knowledge_files")),
        "turns_certain": len(certain),
        "turns_attempted": sum(1 for r in rows if r.get("outcomes", {}).get("attempt")
                               or ("outcomes" not in r and (r.get("certain") or r.get("uncertain")))),
        "turns_succeeded": sum(1 for r in rows if r.get("certain_succeeded")),
        "turns_failed": sum(1 for r in rows if r.get("outcomes", {}).get("failed")),
        "certain_recorded": sum(1 for r in certain if r.get("knowledge_files")),
        "uncertain_only": sum(1 for r in rows if r.get("uncertain") and not r.get("certain")),
        "decision_prompts": sum(1 for r in rows if r.get("decision")),
        "decision_recorded": sum(1 for r in rows if r.get("decision") and r.get("knowledge_files")),
        "sessions": len({r.get("session") for r in rows}),
        "by_environment": sum(1 for r in rows if r.get("trigger") in ("notification", "peer")),
        "first_ts": min((r.get("ts_epoch", 0) for r in rows), default=None),
        "first_trigger_ts": first_trigger_ts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all-generations", action="store_true",
                        help="включить старые строки без trigger")
    args = parser.parse_args()
    s = summary(os.path.realpath(args.root), args.days, whole_only=not args.all_generations)
    if args.json:
        print(json.dumps(s, ensure_ascii=False))
        return 0
    pct = (lambda a, b: f"{round(100 * a / b)} %" if b else "—")
    print(f"Реестр ходов {os.path.basename(os.path.realpath(args.root))} за {args.days} дн.: "
          f"ходов {s['turns']} (прервано {s['interrupted']}; начаты уведомлением или другой "
          f"сессией {s['by_environment']}), сессий {s['sessions']}")
    print(f"  ходы с работой: {s['turns_with_work']}, из них с записью в базу: "
          f"{s['work_recorded']} ({pct(s['work_recorded'], s['turns_with_work'])})")
    print(f"  ходы с распознанными попытками изменений: {s['turns_certain']}, с записью: "
          f"{s['certain_recorded']} ({pct(s['certain_recorded'], s['turns_certain'])})")
    print(f"  исход не подтверждён: {s['turns_attempted']}; успешное изменение: "
          f"{s['turns_succeeded']}; ошибка инструмента: {s['turns_failed']}")
    print(f"  только неясные действия: {s['uncertain_only']}; реплики с решениями: "
          f"{s['decision_prompts']}, записано: {s['decision_recorded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
