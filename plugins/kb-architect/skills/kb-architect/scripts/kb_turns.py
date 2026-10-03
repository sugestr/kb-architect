#!/usr/bin/env python3
"""
kb_turns.py — реестр ходов: что агент сделал за ход и дошло ли это до базы.

Модуль hook'а `kb_start.py` (события UserPromptSubmit, PreToolUse, Stop) и
инструмент замера:

    python3 kb_turns.py <корень проекта> [--days 7] [--json]   # сводка реестра

Почему. Аудит 02.10.2026: агенты пишут знание, но неполно и не туда; самопроверка
зелёная, пока провал идёт. До любых напоминаний агенту (шаг 3 плана) нужен честный
замер по каждому ходу и точность классификации действий (шаг 1: тихий режим).

Что записывается. В начале хода — отпечаток рабочей копии проекта (свой файл, не
состояние сессии): HEAD и изменённые файлы с mtime/размером, только внутри корня
проекта. По ходу — классы следствий разрешённых инструментов, БЕЗ текста команд, имён
хостов и адресов (в командах бывают значения доступов): «точно» — правка файла,
git-запись, удалённая машина, HTTP-запись, MCP-запись, деплой; «неясно» — прочая
оболочка и скрипты. Для правки файла хранится путь в проекте — чтобы в конце хода
отличить базу от работы. В конце хода — какие файлы проекта изменились: коммиты,
сделанные в этой рабочей копии за ход (по reflog; подтянутые `pull` не считаются), и
правки рабочей копии. База — по определению kb_debts.knowledge_paths. Строка реестра —
`~/.cache/kb-architect/entry/turns/<проект>.jsonl`, ротация после 5 МБ.

Границы. Ход, прерванный до конца (Esc, ошибка API), записывается при следующей
реплике как прерванный. Переименование видно как новый путь; подмодули не видны;
параллельные сессии в одной рабочей копии видят правки друг друга. Это замер, не суд.
"""

import argparse
import hashlib
import json
import os
import re
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
HTTP_WRITE = ("-X", "--request", "-d", "--data", "--data-raw", "--data-binary", "-F", "--form",
              "--json", "-T", "--upload-file", "--post-data", "--post-file", "--method")
SCRIPT = re.compile(r"^(?:python(?:3(?:\.\d+)?)?|node|ruby|perl|bash|sh|zsh|php|deno|bun)$")
DEPLOY = re.compile(r"deploy|release|migrate|six_", re.IGNORECASE)
LOCAL_COMMIT = ("commit", "cherry-pick", "revert", "am")
MAX_DIRTY = 4000
ROTATE_BYTES = 5_000_000


def state_root():
    return os.environ.get("KB_ENTRY_STATE") or os.path.join(
        os.path.expanduser("~"), ".cache", "kb-architect", "entry")


def root_key(root):
    return hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:12]


def git(root, *args, timeout=20):
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
    out = git(root, "reflog", "show", "--format=%H%x09%gs", "HEAD")
    if out is None:
        return None
    rows = []
    for line in out.decode("utf-8", "replace").splitlines():
        sha, _, subject = line.partition("\t")
        rows.append((sha, subject))
    return rows


def snapshot(root):
    prefix = repo_prefix(root)
    head = git(root, "rev-parse", "HEAD")
    dirty, truncated = dirty_files(root, prefix)
    log = reflog(root)
    return {"at": time.time(), "head": head.decode().strip() if head else None,
            "reflog_n": len(log) if log is not None else None,
            "dirty": dirty, "truncated": truncated}


def local_commits(root, snap):
    """Коммиты, созданные в этой рабочей копии за ход: новые записи reflog HEAD с темой
    commit / cherry-pick / revert / am. Подтянутые pull, checkout и merge сюда не входят.
    Счёт — по числу новых записей, а не по времени: часы и даты коммитов не важны."""
    log = reflog(root)
    before = snap.get("reflog_n")
    if log is None or before is None:
        return []
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
    if not snap:
        return set()
    prefix = repo_prefix(root)
    changed = set()
    shas = local_commits(root, snap)
    if shas:
        changed |= commit_files(root, shas, prefix)
    before = snap.get("dirty") or {}
    now, truncated = dirty_files(root, prefix)
    now = now or {}
    for rel, sig in now.items():
        if before.get(rel) != sig and (rel in before or not (truncated or snap.get("truncated"))):
            changed.add(rel)
    if not (truncated or snap.get("truncated")):
        for rel in before:
            if rel not in now:
                changed.add(rel)                     # закоммичен или откачен за ход
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


def shell_effects(cmd, segments, read_only):
    """[(класс, вид)] для команды оболочки — без текста, хостов и адресов."""
    if read_only(cmd):
        return []
    if segments is None:
        return [("uncertain", "shell")]
    effects = []
    for words in segments:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if not words or read_only(" ".join(words)):
            continue
        name = os.path.basename(words[0])
        if name == "git" and git_subcommand(words[1:]) in GIT_WRITE:
            effects.append(("certain", "git"))
        elif name in REMOTE:
            effects.append(("certain", "remote"))
        elif name in HTTP and any(w in HTTP_WRITE or w.startswith(("-XPOST", "-XPUT", "-XPATCH",
                                                                   "-XDELETE")) for w in words):
            effects.append(("certain", "http"))
        elif any(w.endswith(".sh") and DEPLOY.search(os.path.basename(w)) for w in words[:3]):
            effects.append(("certain", "deploy"))
        elif SCRIPT.match(name):
            effects.append(("uncertain", "script"))
        else:
            effects.append(("uncertain", "shell"))
    return effects


def snap_path(sid, root):
    return os.path.join(state_root(), "turns", "snap",
                        f"{re.sub(r'[^A-Za-z0-9._-]', '_', str(sid))[:120]}--{root_key(root)}.json")


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


def registry_path(root):
    return os.path.join(state_root(), "turns", root_key(root) + ".jsonl")


def record(root, row):
    path = registry_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if os.path.getsize(path) > ROTATE_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def summary(root, days=7, whole_only=False):
    """Сводка реестра проекта за N дней: ходы со следствиями и с записью в базу.
    whole_only — только ходы, которые служебные реплики уже не режут (строки с `trigger`,
    с 7.6.1): по ним считает сигнал обхода."""
    limit = time.time() - days * 86400
    rows = []
    for path in (registry_path(root) + ".1", registry_path(root)):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("ts_epoch", 0) >= limit and (not whole_only or "trigger" in row):
                        rows.append(row)
        except OSError:
            pass
    certain = [r for r in rows if r.get("certain")]
    work = [r for r in rows if r.get("certain") or r.get("work_files")]
    return {
        "turns": len(rows),
        "interrupted": sum(1 for r in rows if r.get("interrupted")),
        "turns_with_work": len(work),
        "work_recorded": sum(1 for r in work if r.get("knowledge_files")),
        "turns_certain": len(certain),
        "certain_recorded": sum(1 for r in certain if r.get("knowledge_files")),
        "uncertain_only": sum(1 for r in rows if r.get("uncertain") and not r.get("certain")),
        "decision_prompts": sum(1 for r in rows if r.get("decision")),
        "decision_recorded": sum(1 for r in rows if r.get("decision") and r.get("knowledge_files")),
        "sessions": len({r.get("session") for r in rows}),
        "by_environment": sum(1 for r in rows if r.get("trigger") in ("notification", "peer")),
        "first_ts": min((r.get("ts_epoch", 0) for r in rows), default=None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    s = summary(os.path.realpath(args.root), args.days)
    if args.json:
        print(json.dumps(s, ensure_ascii=False))
        return 0
    pct = (lambda a, b: f"{round(100 * a / b)} %" if b else "—")
    print(f"Реестр ходов {os.path.basename(os.path.realpath(args.root))} за {args.days} дн.: "
          f"ходов {s['turns']} (прервано {s['interrupted']}; начаты уведомлением или другой "
          f"сессией {s['by_environment']}), сессий {s['sessions']}")
    print(f"  ходы с работой: {s['turns_with_work']}, из них с записью в базу: "
          f"{s['work_recorded']} ({pct(s['work_recorded'], s['turns_with_work'])})")
    print(f"  ходы с точными следствиями: {s['turns_certain']}, записано: "
          f"{s['certain_recorded']} ({pct(s['certain_recorded'], s['turns_certain'])})")
    print(f"  только неясные действия: {s['uncertain_only']}; реплики с решениями: "
          f"{s['decision_prompts']}, записано: {s['decision_recorded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
