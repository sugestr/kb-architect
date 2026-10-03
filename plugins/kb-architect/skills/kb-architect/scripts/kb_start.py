#!/usr/bin/env python3
"""
kb_start.py — исполняемый вход в KB-проект: hook сессии, замок правок, подтверждение.

    python3 kb_start.py hook --agent claude|codex        # событие hook — JSON на stdin
    python3 kb_start.py confirm <корень> --token <метки> [--bundle <файл входа>]
                                         [--no-role "<почему роль не нужна>"]
    python3 kb_start.py text <корень> [--role <id>]...    # вход без hook (человек, агент без hook)
    python3 kb_start.py status <корень> [--session <id>]
    python3 kb_start.py install --agent claude|codex [--project <корень>] [--check | --remove]

Почему. Вход был описан словами, и сессии его пропускали: 18.09 и 29.09 при
передаче работы читали начала файлов, 29.09 «вопрос казался справкой», 30.09
Codex и 01.10 Claude в продукте на Odoo начали работу без роли — 01.10 шесть
часов на боевой базе. Шаг с командой выполнялся, шаг прозой — нет; квитанция
`kb_entry.py` (7.3.3) тоже осталась просьбой. Выполняется только то, что
исполняет среда.

Как. Hook начала сессии (новый чат, /clear, сжатие, возобновление) находит
KB-проект — ближайший каталог с файлом правил, где `kb_standard_version: <номер>` —
собирает файл входа (`kb_entry.build`: current, обязательные файлы, маршруты
«всегда», метод роли по умолчанию `entry_role`, роли проекта последней частью)
и кладёт в контекст короткое сообщение. Весь вход в контекст Claude не кладётся:
Claude Code прячет больше 10 000 символов в файл и не просит его прочитать
(01.10: 35,6 КБ стали превью 2 КБ). Codex получает файл целиком.

Замок. До подтверждения hook перед инструментом запрещает правки файлов
проекта (по пути файла, не только по cwd), команды оболочки кроме чтения и
kb-скриптов, MCP-действия кроме чтения. Подтверждение — метки в конце каждой
части файла входа: `confirm --token <метки по порядку через «-»>`. Метки случайны
и есть только в файле. Команду подтверждения проверяет сам hook перед её
запуском: он знает id сессии и работает вне песочницы, поэтому подтверждение
не зависит от переменных окружения и прав на запись. Принимаются только файлы
входа, собранные после последнего взвода: после сжатия старые метки замок не
открывают. При ролях без `entry_role` нужна роль (`kb_entry.py --role <id>`)
или явное `--no-role "<почему>"`.

Границы. Защита от обычного пропуска входа, не от сознательного обхода — тот
же класс, что owner gate. Ошибка самого hook'а и событие без id сессии
открывают замок (с предупреждением, где его можно показать). Выключатель на
сессию: `KB_ENTRY_HOOK=off`. Состояние — `~/.cache/kb-architect/entry/`
(`KB_ENTRY_STATE`); в проект пишется только неотслеживаемый файл входа в
git-каталоге.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_entry
import kb_paths
import kb_turns

CONTEXT_LIMIT = 9000          # Claude Code: 10 000 символов на additionalContext
# Codex: предел задаёт сам hook (`additionalContextLimit: 0` — без предела).
INLINE_WHOLE = {"codex"}
# Та же разметка, что принимает kb_paths.declared_value (маркер списка, кавычки, `…`,
# **…**, регистр); заглушка шаблона «<…>» — не номер. tg-archive пишет номер в обратных
# кавычках, и hook 7.4.0 его не видел.
KB_MARK = re.compile(r"^[ \t]*(?:[-*>+][ \t]*)?[`*_\"']{0,2}[ \t]*kb_standard_version"
                     r"[`*_\"']{0,2}[ \t]*:[ \t`*_\"']*v?\d", re.MULTILINE | re.IGNORECASE)
AUTO_RULES = {"claude": ("CLAUDE.md",), "codex": ("AGENTS.md",)}
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")
DEDUP_SECONDS = 5             # два hook'а одного события приходят почти одновременно
READ_TOOLS = {"Read", "Glob", "Grep", "LS", "NotebookRead", "WebFetch", "WebSearch", "ToolSearch",
              "TodoWrite", "AskUserQuestion", "Skill", "Agent", "Task", "EnterPlanMode",
              "ExitPlanMode", "view_image", "read_file", "list_dir", "grep_files"}
FILE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
SHELL_TOOLS = {"Bash", "shell", "local_shell", "exec_command", "container.exec", "unified_exec"}
PLAIN_READ = {"cat", "head", "tail", "less", "more", "wc", "ls", "pwd", "grep", "egrep", "fgrep",
              "stat", "file", "du", "df", "echo", "printf", "date", "which", "whoami", "hostname",
              "diff", "cmp", "cut", "tr", "nl", "basename", "dirname", "realpath", "readlink",
              "test", "[", "true", "shasum", "sha256sum", "md5", "column", "od", "strings", "ps",
              "pdfinfo", "jq", "cd", "rg", "find", "tree", "sort", "uniq", "sed", "pdftotext", "env",
              "git", "journalctl", "sleep"}
GIT_READ = {"status", "log", "show", "diff", "rev-parse", "ls-files", "blame", "describe", "grep",
            "cat-file", "shortlog", "rev-list", "for-each-ref", "ls-remote", "show-ref",
            "merge-base", "name-rev", "count-objects"}
# Внешний аудит 03.10.2026: единственная операция p, включая адрес /регулярка/.
SED_ADDRESS = r"(?:\d+|\$|/(?:\\.|[^/\\\n])*/[IM]?)"
SED_PRINT = re.compile(rf"^(?:{SED_ADDRESS}(?:,{SED_ADDRESS})?)?p$")
KB_READ_SCRIPTS = {"kb_due.py", "kb_check.py", "kb_debts.py"}
MCP_READ = re.compile(r"^(?:get|list|search|read|find|query|describe|fetch|whoami|identity|"
                      r"server_info|server_status|vault_status|chat_info|chat_rights|"
                      r"delivery_status|transport_health|labels?|label_values|loki_query|"
                      r"prometheus_query)", re.IGNORECASE)
MCP_WRITE = re.compile(r"create|update|delete|remove|set_|send|post|write|modify|archive|move|"
                       r"trash|complete|enroll|register|publish|revoke|pin|edit|forward|copy|"
                       r"import|execute|upload|apply|install|merge|push|approve", re.IGNORECASE)
PATCH_PATH = re.compile(r"^\*\*\* (?:(Add|Update|Delete) File|Move to): (.+)$", re.MULTILINE)
# (событие, matcher Claude, matcher Codex, timeout, статус). Строка команды и
# состав записи — ключ доверия Codex: их правка требует нового одобрения владельца.
# Последнее поле — строка состояния. Codex показывает её и как имя hook'а в настройках
# (поля «имя» у него нет): без неё владелец видел «Хук 1» трижды (03.10.2026). Claude Code
# показывает её только как статус, поэтому частым событиям она там не ставится.
HOOK_EVENTS = (
    ("SessionStart", "startup|resume|clear|compact", "startup|resume|clear|compact", 120,
     "База знаний: вход в проект"),
    ("UserPromptSubmit", None, None, 20, "База знаний: начало шага"),
    ("PreToolUse", "Bash|Edit|Write|MultiEdit|NotebookEdit|mcp__.*",
     "Bash|apply_patch|Edit|Write|mcp__.*", 20, "База знаний: проверка перед действием"),
    ("Stop", None, None, 20, "База знаний: итог шага"),
)
# Реестр хода (7.5): «record» — только запись; «advise» и «block» — после недели замера.
CAPTURE_MODES = ("record", "advise", "block")
NOW_LIMIT = 20 * 1024        # сигнал проверить назначение NOW; размер сам по себе не ошибка
MEMORY_FILE = re.compile(r"/\.claude/projects/[^/]+/memory/[^/]+\.md$")
MEMORY_KIND = re.compile(r"^\s*type\s*:\s*[\"']?(project|reference)\b",
                         re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------- состояние

def state_root():
    return os.environ.get("KB_ENTRY_STATE") or os.path.join(
        os.path.expanduser("~"), ".cache", "kb-architect", "entry")


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value))[:120] or "_"


def root_key(root):
    return hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:12]


def state_path(sid, root):
    """Своё состояние на пару «сессия, проект»: сессия, зашедшая в другой
    KB-проект, проходит его вход и не теряет вход своего."""
    return os.path.join(state_root(), "sessions", f"{safe_name(sid)}--{root_key(root)}.json")


def load_state(sid, root):
    if not sid or not root:
        return None
    try:
        with open(state_path(sid, root), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    return state if state.get("root") == os.path.realpath(root) else None


def save_state(state):
    path = state_path(state["session"], state["root"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


def iso_time(value):
    try:
        return datetime.datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def prune_old(days=30):
    limit = time.time() - days * 86400
    for folder in (os.path.join(state_root(), "sessions"),
                   os.path.join(state_root(), "turns", "snap"),
                   os.path.join(state_root(), "service", "said")):
        try:
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.getmtime(path) < limit:
                    os.remove(path)
        except OSError:
            pass


def claim(sid, root, key):
    """Пользовательский и проектный hook одного события — один вход: второй молчит."""
    lock = os.path.join(state_root(), "sessions",
                        f"{safe_name(sid)}--{root_key(root)}.{safe_name(key)}.lock")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    try:
        if time.time() - os.path.getmtime(lock) > DEDUP_SECONDS:
            os.remove(lock)
    except OSError:
        pass
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        return False


# ---------------------------------------------------------------- проект

def find_root(start):
    """KB-проект вверх от пути: ближайший каталог с файлом правил решает.

    Номер в `kb_standard_version` — KB-проект (заглушка шаблона «<…>» — нет);
    файл правил без него (вложенное приложение, профиль бота) — граница не-KB
    области, hook там молчит."""
    try:
        path = os.path.realpath(start or os.getcwd())
    except OSError:
        return None
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    home = os.path.realpath(os.path.expanduser("~"))
    while True:
        rules = [os.path.join(path, n) for n in kb_paths.RULES_NAMES
                 if os.path.isfile(os.path.join(path, n))]
        if rules:
            return path if any(KB_MARK.search(kb_paths.read(r)) for r in rules) else None
        parent = os.path.dirname(path)
        if parent == path or path == home:
            return None
        path = parent


def scripts_dir():
    return os.path.dirname(os.path.abspath(__file__))


def q(value):
    return shlex.quote(str(value))


def session_from_env():
    for name in SESSION_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def due_summary(root, limit=1800):
    """Блок ПОРА из kb_due — раз в день на проект: медленный проект не платит таймаут на
    каждом старте. Внешний аудит 03.10.2026: ненулевой выход больше не читается как «ПОРА
    пусто», а неудача запоминается только на час (повтор без суточной слепоты); «не
    проверено» из отчёта переносится в блок и кэшируется вместе с ним — это честный итог."""
    day = datetime.date.today().isoformat()
    cache = os.path.join(state_root(), "due", f"{root_key(root)}-{day}.txt")
    failed = os.path.join(state_root(), "due",
                          f"{root_key(root)}-{day}-{datetime.datetime.now().hour:02d}.fail")
    for path in (cache, failed):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    try:
        out = subprocess.run([sys.executable, os.path.join(scripts_dir(), "kb_due.py"), root],
                             capture_output=True, text=True, timeout=20,
                             env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        if out.returncode != 0:
            raise RuntimeError(f"exit {out.returncode}")
        lines, inside = [], False
        for line in out.stdout.splitlines():
            if line.startswith("ПОРА"):
                inside = True
                continue
            if inside:
                if not line.strip():
                    break
                lines.append(line[:300])
        unknown = [line[:300] for line in out.stdout.splitlines()
                   if "НЕ ПРОВЕРЕН" in line or "NOT_CHECKED" in line]
        lines.extend(line for line in unknown if line not in lines)
        text, path = ("\n".join(lines) if lines else "ПОРА пусто."), cache
    except Exception as exc:  # диагностика не должна ломать вход
        text = f"kb_due не выполнен ({exc if isinstance(exc, RuntimeError) else type(exc).__name__}); " \
               "запусти kb_due.py вручную"
        path = failed
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0] + "\n  … (полностью: kb_due.py)"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    return text


# ---------------------------------------------------------------- обновление до входа

OFF = ("off", "0", "no", "false")


UPDATE_DEADLINE = 15         # сек.: старт не ждёт сеть дольше, а host даёт hook'у 120


def update_skill():
    """Свежий stable скилла до входа: сессия ещё ничего не прочитала — граница
    безопаснее некуда. «Автообновление» до 7.4.1 было шагом 2 правил проекта,
    той же прозой, что и пропущенный вход: ни планировщика, ни hook'а (02.10).
    Проверка — ls-remote (~0,6 с без новой версии); недоступная сеть не мешает
    входу, а называется. Выключатель — `KB_ENTRY_UPDATE=off`."""
    if os.environ.get("KB_ENTRY_UPDATE", "").strip().lower() in OFF:
        return {"status": "OFF", "line": "обновление скилла на входе выключено (KB_ENTRY_UPDATE)"}
    home = os.path.realpath(os.path.expanduser("~"))
    if not os.path.realpath(scripts_dir()).startswith(home + os.sep):
        # Prime: копию ставит адаптер выпуска лаборатории (ссылка в /srv/…); свой
        # updater там только клонировал бы public на каждом старте.
        return {"status": "EXTERNAL", "line": f"скилл {kb_paths.skill_version() or '?'} ставит "
                "установщик выпуска лаборатории, не сессия"}
    cache = os.path.join(state_root(), "update-last.json")
    try:
        with open(cache, encoding="utf-8") as f:
            last = json.load(f)
        if last.get("status") not in ("CURRENT", "INSTALLED") and \
                time.time() - last.get("at", 0) < 3600:
            return {"status": "SKIPPED", "line": f"обновление скилла: прошлая проверка — "
                    f"{last.get('status')}, повтор через час; вручную — kb_update.py --public"}
    except (OSError, ValueError, AttributeError):
        pass
    import fcntl
    os.makedirs(state_root(), exist_ok=True)
    lock = open(os.path.join(state_root(), "update.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return {"status": "BUSY", "line": "скилл обновляется в другой сессии прямо сейчас"}
    try:
        proc = subprocess.Popen([sys.executable, os.path.join(scripts_dir(), "kb_update.py"),
                                 "--public", "--fast", "--сделать"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=UPDATE_DEADLINE)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, 9)          # вместе с git clone, без сирот
            except OSError:
                pass
            proc.communicate()
            out = "UPDATE_STATUS=TIMEOUT\n"
    except Exception as exc:
        out = f"UPDATE_STATUS=FAILED ({type(exc).__name__})\n"
    finally:
        lock.close()
    status = next((l.split("=", 1)[1].strip() for l in out.splitlines()
                   if l.startswith("UPDATE_STATUS=")), "UNKNOWN")
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"at": time.time(), "status": status.split()[0]}, f)
    except OSError:
        pass
    changed = [l.strip() for l in out.splitlines() if "→" in l][:2]
    edition = next((l.split(":", 1)[1].strip() for l in out.splitlines()
                    if l.strip().startswith("редакция:")), None) or kb_paths.skill_version() or "?"
    line = {"CURRENT": f"скилл {edition} — свежий (public)",
            "INSTALLED": "скилл обновлён до входа: " + ("; ".join(changed) or "новая редакция")}.get(
        status, f"обновление скилла: {status} — kb_update.py --public вручную")
    return {"status": status, "line": line}


def project_update(root):
    """Уровень проекта против установленного скилла: дельта и действия выпуска.

    Сессия их видит до первой правки и называет в первом ответе; сама миграция —
    работа «обновись» с owner gates проекта, не условие замка."""
    try:
        out = subprocess.run([sys.executable, os.path.join(scripts_dir(), "kb_apply.py"), root],
                             capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return {"open": None, "short": "уровень проекта не проверен", "lines": [str(exc)]}
    text = out.stdout
    actions = [l.strip()[2:] for l in text.splitlines() if l.strip().startswith("• ")]
    head = next((l for l in text.splitlines()
                 if l.startswith(("NEEDS_APPLICATION", "APPLICATION_UNPROVEN"))), None)
    if out.returncode == 1 and head:
        version = re.search(r"цель (\d+\.\d+\.\d+)", text)
        short = "дельта проекта открыта" + (f" (цель {version.group(1)})" if version else "")
        return {"open": True, "short": short, "lines": [head.strip()] + actions}
    if out.returncode != 0 or "НЕ ПРОВЕРЕНЫ" in text:
        return {"open": None, "short": "уровень проекта не проверен",
                "lines": [((text + out.stderr).strip().splitlines()
                           or [f"kb_apply код {out.returncode}"])[-1]]}
    if actions:
        return {"open": True, "short": f"действий выпуска: {len(actions)}", "lines": actions}
    return {"open": False, "short": "проект на уровне скилла", "lines": []}


def update_section(root, skill, project):
    lines = ["", "## Обновление (hook сделал до входа)", f"- {skill['line']}"]
    if project["open"] is False:
        lines.append("- проект на уровне скилла, действий выпуска нет")
        return lines
    lines.append(f"- проект: {project['short']}")
    lines += [f"  · {l[:400]}" for l in project["lines"][:8]]
    if project["open"]:
        cmd = (f"python3 {q(os.path.join(scripts_dir(), 'kb_update.py'))} --public --fast "
               f"--сделать --project {q(root)}")
        lines += ["- Дотянуть проект — работа этой сессии: назови это в первом ответе; задача не "
                  "срочная — начни с «обновись» (" + cmd + "); срочная — сначала она, а "
                  "незакрытое — PENDING в NOW с адресом. Приёмка и push — по правилам проекта."]
    return lines


# ---------------------------------------------------------------- вход

def needs_role(root, roles):
    """Роль обязательна, если у проекта есть роли, а в файле входа — ни одной."""
    return bool(kb_entry.declared_roles(root)[0]) and not roles


def start_entry(root, sid, agent, source, roles=None):
    """Собирает файл входа и взводит замок сессии до подтверждения."""
    armed_at = now_iso()                  # до сборки: файлы входа раньше взвода не принимаются
    all_roles, default = kb_entry.declared_roles(root)
    wanted = default if roles is None else roles
    result = kb_entry.build(root, wanted, (), skip=AUTO_RULES.get(agent, ()))
    out = kb_entry.default_out(root)
    digest, fragments = kb_entry.write(root, result, out)
    state = {"schema": 2, "session": sid, "agent": agent, "root": os.path.realpath(root),
             "source": source, "armed_at": armed_at, "bundle": out, "parts": len(fragments),
             "part_sha256": [kb_entry.part_hash(x) for x in fragments],
             "roles": result["found_roles"], "missing": result["missing"],
             "blocking": result["blocking"],
             "receipt": kb_entry.receipt_line(result, digest), "bytes": result["total"],
             "confirmed": None}
    if sid:
        save_state(state)
    return state, all_roles


def role_lines(all_roles, limit=2400):
    lines = [f"- {r['id']}: {'; '.join(r.get('load_when', [])[:3])[:220]}" for r in all_roles]
    text = "\n".join(lines) or "- ролей в PROJECT_ROLES.json нет"
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n- …"


def confirm_command(root, bundle=None):
    cmd = f"python3 {q(os.path.join(scripts_dir(), 'kb_start.py'))} confirm {q(root)}"
    if bundle:
        cmd += f" --bundle {q(bundle)}"
    return cmd + " --token <метки>"


def entry_command(root, agent):
    tail = f" --agent {agent}" if agent in AUTO_RULES else ""
    return f"python3 {q(os.path.join(scripts_dir(), 'kb_entry.py'))} {q(root)} --role <id>{tail}"


def entry_message(state, all_roles, event, due=None, agent="claude", inline=True, update=None):
    root, bundle = state["root"], state["bundle"]
    roles = ", ".join(state["roles"]) or "не выбрана"
    rules = ", ".join(AUTO_RULES.get(agent, ())) or "правила проекта"
    role_step = (f"2. Роль — по задаче владельца. В файле роль {roles}; задача под другую роль "
                 f"(поводы ниже) — собери её вход: {entry_command(root, agent)}, читай его файл.")
    if needs_role(root, state["roles"]):
        role_step = ("2. Роль по умолчанию не объявлена (`entry_role`), а роли у проекта есть: "
                     f"выбери по задаче и собери её вход — {entry_command(root, agent)} — "
                     "и подтверждай его файл (current в нём есть). Задача вне ролей — "
                     "этот файл и `--no-role \"<почему>\"` в подтверждении.")
    head = [f"# KB-ВХОД — {os.path.basename(root)} (kb-architect {kb_paths.skill_version() or '?'}, "
            f"{event})",
            "",
            "Вход НЕ завершён. До подтверждения hook запрещает правки файлов проекта, команды "
            "оболочки (кроме чтения и kb-скриптов) и MCP-действия; чтение разрешено.",
            f"1. Прочитай файл входа целиком: {bundle}",
            f"   частей: {state['parts']}, {state['bytes']} B. Большой файл — частями до конца. "
            "В конце каждой части — метка.",
            role_step,
            "3. Подтверди метками прочитанного файла по порядку через «-» (проверяет hook):",
            f"   {confirm_command(root)}",
            "   для файла роли добавь --bundle <его путь> из ENTRY_BUNDLE.",
            "4. После подтверждения в первом ответе — строка ENTRY_RECEIPT; перед записью в "
            f"область базы — python3 {q(os.path.join(scripts_dir(), 'kb_debts.py'))} {q(root)} "
            "--area <путь>.",
            f"Правила ({rules}) агент загрузил сам; в файле входа их нет.",
            f"Квитанция этого файла: {state['receipt']}"]
    for line in state.get("missing", [])[:6]:
        head.append(f"! {line}")
    if update:
        head += update
    head += ["", "Роли проекта (id: поводы):", role_lines(all_roles)]
    if due:
        head += ["", "ПОРА (kb_due, раз в день):", due]
    text = "\n".join(head)
    if len(text) > CONTEXT_LIMIT:
        text = text[:CONTEXT_LIMIT - 40].rsplit("\n", 1)[0] + "\n… (сокращено до предела hook)"
    try:
        with open(bundle, encoding="utf-8") as f:
            body = f.read()
    except OSError:
        body = None
    whole = inline and agent in INLINE_WHOLE
    if body is not None and (whole or len(text) + len(body) + 200 <= CONTEXT_LIMIT):
        text = text.replace(f"1. Прочитай файл входа целиком: {bundle}",
                            f"1. Файл входа ниже целиком (копия: {bundle})", 1)
        text += "\n\n======== ФАЙЛ ВХОДА ========\n" + body
    return text


def reminder(state):
    return (f"KB-вход не подтверждён ({os.path.basename(state['root'])}): файл входа "
            f"{state['bundle']}, подтверждение — {confirm_command(state['root'])}. Роль — по "
            "задаче (список в файле входа). До подтверждения правки, команды и MCP-действия "
            "закрыты.")


# ---------------------------------------------------------------- подтверждение

def sidecar(path):
    try:
        with open(path + ".json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("part_sha256") is not None else None


def candidates(root, state=None, bundle=None, since=0.0):
    """Файлы входа этого проекта, собранные не раньше `since` (момента взвода)."""
    root = os.path.realpath(root)
    out, seen = [], set()

    def add(item):
        key = os.path.realpath(item.get("bundle") or "")
        if key in seen or item.get("root") != root or iso_time(item.get("created")) < since:
            return
        seen.add(key)
        out.append(item)

    if state and state.get("bundle"):
        add({"bundle": state["bundle"], "root": state["root"], "created": state.get("armed_at"),
             "part_sha256": state["part_sha256"], "roles": state.get("roles", []),
             "missing": state.get("missing"), "blocking": state.get("blocking"),
             "receipt": state.get("receipt", "")})
    if bundle:
        side = sidecar(bundle)
        if side:
            add(side)
    folder = kb_entry.git_dir(root)
    folder = os.path.join(folder, "kb-entry") if folder else None
    if folder and os.path.isdir(folder):
        for name in sorted((n for n in os.listdir(folder) if n.endswith(".md.json")),
                           reverse=True)[:50]:
            side = sidecar(os.path.join(folder, name[:-5]))
            if side:
                add(side)
    return out


def check_marks(cands, fragments):
    """(подошедший файл, None) или (None, текст причины)."""
    if not cands:
        return None, ("нет файла входа этого проекта, собранного после последнего взвода; "
                      "для файла роли укажи --bundle <путь из ENTRY_BUNDLE>")
    near = None
    for c in cands:
        hashes = c.get("part_sha256") or []
        if len(fragments) == len(hashes) and all(
                kb_entry.part_hash(f) == h for f, h in zip(fragments, hashes)):
            return c, None
        if near is None:
            wrong = [str(i + 1) for i, h in enumerate(hashes)
                     if i >= len(fragments) or kb_entry.part_hash(fragments[i]) != h]
            near = (f"файл {c.get('bundle')}: частей {len(hashes)}, не совпали части: "
                    f"{', '.join(wrong) or '—'}")
    return None, (f"метки не совпали. {near}. Дочитай эти части и повтори; подтверждаешь "
                  "файл роли — добавь --bundle <путь из ENTRY_BUNDLE>.")


def fragments_of(token):
    return [x.lower() for x in re.split(r"[-\s,;]+", token or "") if x]


def verify(root, state, token, bundle=None, no_role=None):
    """(confirmation, None) или (None, причина) для подтверждения в этой сессии."""
    since = iso_time(state.get("armed_at")) if state else 0.0
    found, why = check_marks(candidates(root, state, bundle, since), fragments_of(token))
    if not found:
        return None, why
    # Внешний аудит 03.10.2026: чтение оставшихся частей не доказывает вход роли. Держит замок
    # только пробел роли (метод не найден или не прочитан, сломан предок); выход — другая роль
    # или «без роли». Файл входа до 7.7 (без поля) принимается как прежде.
    if found.get("blocking"):
        return None, ("вход роли неполон: " + "; ".join(found["blocking"])
                      + ". Выход: собери вход с другой ролью ("
                      + entry_command(root, (state or {}).get("agent"))
                      + ") либо без роли (та же команда без --role) и подтверди его метками; "
                        "без роли — с --no-role \"<почему задача вне ролей>\".")
    if needs_role(root, found.get("roles")) and not (no_role or "").strip():
        return None, ("у проекта есть роли, а в этом файле входа — ни одной. Собери вход роли по "
                      f"задаче ({entry_command(root, (state or {}).get('agent'))}) и подтверди "
                      "его метками, либо добавь --no-role \"<почему задача вне ролей>\".")
    receipt = found.get("receipt", "")
    if state and state.get("project_update"):
        receipt += f" · проект: {state['project_update']}"
    return {"at": now_iso(), "bundle": found.get("bundle"), "roles": found.get("roles", []),
            "receipt": receipt, "no_role": (no_role or "").strip() or None}, None


def parse_confirm(cmd):
    """Аргументы `kb_start.py confirm …` из команды оболочки, иначе None."""
    for line in cmd.splitlines():
        try:
            words = shlex.split(line)
        except ValueError:
            continue
        for i, w in enumerate(words):
            if os.path.basename(w) == "kb_start.py" and i + 1 < len(words) \
                    and words[i + 1] == "confirm":
                parser = argparse.ArgumentParser(add_help=False)
                parser.add_argument("root")
                parser.add_argument("--token", default="")
                parser.add_argument("--bundle")
                parser.add_argument("--no-role")
                parser.add_argument("--session")
                try:
                    args, _ = parser.parse_known_args(words[i + 2:])
                except SystemExit:
                    return None
                return args
    return None


# ---------------------------------------------------------------- замок

def command_of(tool_input):
    cmd = (tool_input.get("command") or tool_input.get("cmd")) if isinstance(tool_input, dict) else None
    if isinstance(cmd, list):
        if len(cmd) >= 3 and os.path.basename(str(cmd[0])) in ("bash", "sh", "zsh") \
                and cmd[1] in ("-c", "-lc"):
            return str(cmd[2])
        return " ".join(shlex.quote(str(x)) for x in cmd)
    return cmd if isinstance(cmd, str) else ""


OPERATOR = re.compile(r"^[();<>|&]+$")
CONTROL = {";", "&", "&&", "|", "||"}


def shell_segments(cmd):
    """Команды по управляющим операторам; None — если есть то, что исполняет код
    или пишет в файл (подстановка, подоболочка, heredoc, вывод не в /dev/null)."""
    if "`" in cmd or "$(" in cmd or "<(" in cmd or ">(" in cmd:
        return None
    segments = []
    for line in cmd.splitlines():
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            tokens = list(lex)
        except ValueError:
            return None
        current, i = [], 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in CONTROL:
                segments.append(current)
                current = []
            elif OPERATOR.match(tok):
                nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
                if tok in (">&", "<&") and nxt.isdigit():
                    pass
                elif tok in (">", ">>", "&>", "&>>", ">|") and nxt == "/dev/null":
                    pass
                elif tok == "<" and nxt and not OPERATOR.match(nxt):
                    pass
                else:
                    return None
                if current and current[-1].isdigit():
                    current.pop()             # «2» из 2>&1 — номер потока, не аргумент
                i += 1                        # цель перенаправления — не аргумент
            else:
                current.append(tok)
            i += 1
        segments.append(current)
    return [s for s in segments if s]


def positional(args):
    return [a for a in args if not a.startswith("-")]


def git_read_only(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in ("-C", "-c") and i + 1 < len(args):
            i += 2
            continue
        i += 1
    if i >= len(args):
        return False
    sub, rest = args[i], args[i + 1:]
    if any(a.startswith("--output") for a in rest):
        return False
    if sub in GIT_READ:
        return True
    if sub in ("branch", "tag"):
        return not positional(rest) or rest[:1] in (["-l"], ["--list"])
    if sub == "stash":
        return rest[:1] in (["list"], ["show"])
    if sub == "reflog":
        return not rest or rest[:1] == ["show"]
    if sub == "worktree":
        return rest[:1] == ["list"]
    if sub == "remote":
        return not positional(rest) or rest[:1] in (["get-url"], ["show"])
    if sub == "config":
        return any(a in ("--get", "--get-all", "--get-regexp", "--list", "-l") for a in rest)
    return False


def kb_script_read_only(words):
    """`python3 [-u] …/kb_<x>.py …` — только читающие вызовы скриптов скилла."""
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 1
    if i >= len(words):
        return False
    script, rest = os.path.basename(words[i]), words[i + 1:]
    if script in KB_READ_SCRIPTS:
        return True
    if script == "kb_entry.py":
        return "--out" not in rest and not any(a.startswith("--out=") for a in rest)
    if script == "kb_start.py":
        return rest[:1] in (["confirm"], ["status"], ["text"])
    return False


def command_read_only(words):
    name, args = os.path.basename(words[0]), words[1:]
    if re.match(r"^python(?:3(?:\.\d+)?)?$", name):
        return kb_script_read_only(words)
    if name not in PLAIN_READ:
        return False
    if name == "git":
        return git_read_only(args)
    if name == "sleep":
        return len(args) == 1 and bool(re.fullmatch(r"\d+(?:\.\d+)?", args[0]))
    if name == "journalctl":
        return not any(a.startswith(("--vacuum", "--rotate", "--flush", "--sync", "--relinquish", "--setup-keys", "--update-catalog")) for a in args)
    if name == "sed":
        if any(a == "-i" or a.startswith("-i") or a.startswith("--in-place") for a in args):
            return False
        if not any(a in ("-n", "--quiet", "--silent") for a in args):
            return False
        if any(a in ("-e", "-f") or a.startswith(("--expression", "--file")) for a in args):
            return False
        scripts = positional(args)[:1]
        return bool(scripts) and all(SED_PRINT.match(s) for s in scripts)
    if name == "find":
        return not any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir")
                       or a.startswith("-fprint") or a.startswith("-fls") for a in args)
    if name == "sort":
        return not any(a.startswith("-o") or a.startswith("--output") for a in args)
    if name == "uniq":
        return len(positional(args)) <= 1
    if name == "tree":
        return "-o" not in args
    if name == "rg":
        return not any(a.startswith("--pre") for a in args)
    if name == "pdftotext":
        return "-" in args
    if name == "env":
        return not args
    return True


def shell_read_only(cmd):
    """Команда только читает: каждое звено — из короткого списка, без записи в файл."""
    if not (cmd or "").strip():
        return False
    segments = shell_segments(cmd)
    if segments is None:
        return False
    for words in segments:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if words and not command_read_only(words):
            return False
    return True


def mcp_read_only(tool):
    name = tool.split("__")[-1]
    return bool(MCP_READ.match(name)) and not MCP_WRITE.search(name)


def inbox_delivery(tool, path, root):
    """Новый файл в каталоге входящих другого проекта — доставка, а не работа в нём.

    02.10.2026: письмо в инбокс соседнего проекта потребовало полного входа в
    чужой проект и загрузки его роли. Доставке нужен вход отправителя (cwd), а
    не адресата; правка существующего файла адресата — уже работа в его проекте."""
    if tool not in ("Write", "apply_patch:Add") or os.path.exists(path):
        return False
    try:
        import kb_check
        inbox = kb_check.inbox_dir(root)
    except Exception:
        inbox = None
    inbox = os.path.realpath(inbox) if inbox else None
    real = os.path.realpath(os.path.dirname(path)) + os.sep
    return bool(inbox) and real.startswith(inbox + os.sep)


def patch_paths(tool_input):
    """Внешний аудит 03.10.2026: общий разбор путей для замка и реестра, включая перенос."""
    raw = command_of(tool_input) or (tool_input.get("input", "")
                                     if isinstance(tool_input, dict) else "")
    return [(op or "Move", rel.strip()) for op, rel in PATCH_PATH.findall(str(raw))]


def touched_roots(event):
    """KB-проекты, которых касается инструмент: путь правимого файла, иначе cwd."""
    tool, tool_input = event.get("tool_name") or "", event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    paths = []                               # (путь, вид записи)
    if tool in FILE_TOOLS and isinstance(tool_input, dict):
        value = tool_input.get(FILE_TOOLS[tool])
        if isinstance(value, str) and value:
            paths.append((value if os.path.isabs(value) else os.path.join(cwd, value), tool))
    if tool == "apply_patch":
        for op, rel in patch_paths(tool_input):
            paths.append((rel if os.path.isabs(rel) else os.path.join(cwd, rel), f"apply_patch:{op}"))
    roots = []
    own = find_root(cwd)
    for path, kind in paths:
        root = find_root(path)
        if root and root != own and inbox_delivery(kind, path, root):
            root = own                       # конверт в чужой инбокс: вход отправителя
        if root and root not in roots:
            roots.append(root)
    if not paths:
        root = find_root(cwd)
        if root:
            roots.append(root)
    return roots


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def deny_reason(state, all_roles):
    return (f"KB-ВХОД НЕ ПОДТВЕРЖДЁН ({os.path.basename(state['root'])}): правки, команды и "
            f"MCP-действия закрыты до входа. Прочитай файл входа до конца: {state['bundle']} "
            f"(частей: {state['parts']}; роль: {', '.join(state['roles']) or 'не выбрана'}). "
            f"Роль под задачу — {entry_command(state['root'], state.get('agent'))}. Затем: "
            f"{confirm_command(state['root'])} (для файла роли — с --bundle).\nРоли: "
            + role_lines(all_roles, 1200))


# ---------------------------------------------------------------- hook

def emit(payload):
    print(json.dumps(payload, ensure_ascii=True))


def context_payload(event_name, text, notice=None):
    payload = {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}}
    if notice:
        payload["systemMessage"] = notice
    return payload


def on_session_start(event, agent):
    sid, source = event.get("session_id"), event.get("source") or "startup"
    root = find_root(event.get("cwd"))
    if not root or not sid:
        return None
    rerun = os.environ.get("KB_ENTRY_RERUN") == "1"
    if not rerun and not claim(sid, root, f"start-{source}"):
        return None
    previous = load_state(sid, root)
    if previous and source == "resume" and previous.get("confirmed"):
        c = previous["confirmed"]
        return context_payload("SessionStart",
                               f"KB-вход в эту сессию подтверждён {c['at']} (роль "
                               f"{', '.join(c.get('roles') or []) or 'не выбрана'}): "
                               f"{c.get('receipt', '')}")
    mark_starting(sid, root)
    skill = None
    if rerun:
        skill = {"status": "INSTALLED", "line": os.environ.get("KB_ENTRY_SKILL_LINE", "")}
    elif source != "compact":
        skill = update_skill()
        if skill["status"] == "INSTALLED":
            # Вход строит уже новая редакция: тот же hook по той же ссылке на скилл.
            try:
                child = subprocess.run([sys.executable, os.path.abspath(__file__), "hook",
                                        "--agent", agent], input=json.dumps(event),
                                       capture_output=True, text=True, timeout=90,
                                       env=dict(os.environ, KB_ENTRY_RERUN="1",
                                                KB_ENTRY_SKILL_LINE=skill["line"]))
                payload = json.loads(child.stdout) if child.stdout.strip() else None
            except Exception:
                payload = None
            if payload:
                return payload
    prune_old()
    roles = None
    if previous and source in ("compact", "resume"):
        roles = (previous.get("confirmed") or {}).get("roles") or previous.get("roles") or None
    state, all_roles = start_entry(root, sid, agent, source, roles)
    if source == "compact" and previous and previous.get("turn"):
        state["turn"] = previous["turn"]      # сжатие посреди хода — тот же ход (ревью 7.6.1)
    label = {"compact": "контекст сжат — вход заново", "clear": "/clear — вход заново",
             "resume": "возобновление без подтверждённого входа"}.get(source, "новая сессия")
    due = None if source == "compact" else due_summary(root)
    service = ""
    if source != "compact":
        try:
            import kb_service
            service = kb_service.due_text(root, once_a_day=True)
        except Exception:
            service = ""
    project = project_update(root)
    skill = skill or {"status": "SKIPPED", "line": "скилл после сжатия не перепроверялся"}
    state["project_update"] = project["short"]
    save_state(state)
    text = entry_message(state, all_roles, label, due, agent,
                         update=update_section(root, skill, project) +
                         (["", "## Пора обслужить базу", service] if service else []))
    notice = (f"KB-вход {os.path.basename(root)}: файл входа собран, правки закрыты до "
              f"подтверждения ({state['parts']} частей, роль "
              f"{', '.join(state['roles']) or 'не выбрана'}); {skill['line']}; проект: "
              f"{project['short']}" + ("; пора обслужить базу" if service else "") + ".")
    return context_payload("SessionStart", text, notice)


def starting_path(sid, root):
    return os.path.join(state_root(), "sessions", f"{safe_name(sid)}--{root_key(root)}.starting")


def mark_starting(sid, root):
    try:
        os.makedirs(os.path.dirname(starting_path(sid, root)), exist_ok=True)
        open(starting_path(sid, root), "w").close()
    except OSError:
        pass


def session_state(sid, root, agent):
    """Состояние сессии; сессия старше установки hook'а получает вход сейчас.
    Параллельные hook'и строят один файл: второй ждёт первого. Пока старт сессии
    обновляет скилл, реплика и инструмент ждут его вход, а не строят свой."""
    state = load_state(sid, root)
    if state:
        return state, False
    try:
        starting = time.time() - os.path.getmtime(starting_path(sid, root)) < UPDATE_DEADLINE + 30
    except OSError:
        starting = False
    if starting:
        for _ in range(int((UPDATE_DEADLINE + 3) / 0.2)):
            time.sleep(0.2)
            state = load_state(sid, root)
            if state:
                return state, False
    if claim(sid, root, "late"):
        state, _ = start_entry(root, sid, agent, "late")
        return state, True
    for _ in range(25):
        time.sleep(0.2)
        state = load_state(sid, root)
        if state:
            return state, False
    return None, False


def begin_turn(state, root, prompt):
    """Отпечаток рабочей копии в начале хода — для итога хода в реестре. Ход без конца
    (прерван Esc или ошибкой) записывается здесь как прерванный, а не теряется.
    Уведомление о фоновой задаче или сообщение другой сессии посреди хода — тот же ход
    (7.6.1); после конца хода оно начинает новый, но решением владельца не считается.
    Ход, брошенный Esc (Stop не пришёл), уведомление не закрывает: он закроется следующим
    Stop или репликой владельца — прерванных так насчитается меньше, работа не теряется."""
    try:
        # Внешний аудит 03.10.2026: read–modify–save и дедупликация под одним замком.
        with kb_turns.git_budget(), kb_turns.file_lock(state_path(state["session"], root)):
            current = load_state(state["session"], root)
            if not current:
                return
            state.clear()
            state.update(current)
            stamp = time.time()
            identity = hashlib.sha256((str(state["session"]) + "\0" + str(prompt)).encode()).hexdigest()
            previous = state.get("prompt_event") or {}
            if previous.get("identity") == identity and 0 <= stamp - previous.get("at", 0) <= DEDUP_SECONDS:
                return
            kind = kb_turns.prompt_kind(prompt)
            state["prompt_event"] = {"identity": identity, "at": stamp}
            if state.get("turn"):
                if kind != "human":
                    save_state(state)
                    return
                _finish_turn(state, interrupted=True)
            canonical, worktree = kb_turns.project_identity(root)
            kb_turns.save_snap(state["session"], root, kb_turns.snapshot(root))
            state["turn"] = {"at": now_iso(), "decision": kb_turns.is_decision(prompt),
                             "effects": [], "calls": [], "trigger": kind,
                             "project": os.path.basename(canonical), "worktree": worktree,
                             "project_key": hashlib.sha256(canonical.encode()).hexdigest()[:12]}
            save_state(state)
    except Exception:
        pass


def on_prompt(event, agent):
    sid = event.get("session_id")
    root = find_root(event.get("cwd"))
    if not root or not sid:
        return None
    state, fresh = session_state(sid, root, agent)
    if state:
        begin_turn(state, root, event.get("prompt") or "")
    if not state or state.get("confirmed") or state.get("error"):
        return None
    if fresh:
        return context_payload("UserPromptSubmit",
                               entry_message(state, kb_entry.declared_roles(root)[0],
                                             "сессия старше hook'а", None, agent))
    if kb_turns.prompt_kind(event.get("prompt")) != "human":
        return None                           # замок остаётся; напоминание — на реплику владельца
    return context_payload("UserPromptSubmit", reminder(state))


def memory_text_after(tool, ti, path):
    """Текст файла памяти после правки: Write — новое содержимое, Edit — применённые замены."""
    if tool == "Write":
        return str(ti.get("content") or "")
    text = kb_paths.read(path) if os.path.isfile(path) else ""
    edits = ti.get("edits") if tool == "MultiEdit" else [ti]
    for e in edits if isinstance(edits, list) else []:
        if not isinstance(e, dict):
            continue
        old, new = str(e.get("old_string") or ""), str(e.get("new_string") or "")
        if old:
            text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
        else:
            text += new
    return text


def memory_pointers(text, root):
    """Пути к файлам проекта в тексте памяти: относительные, абсолютные, через «~»."""
    out = set()
    for token in re.findall(r"[^\s`'\"()<>\[\],;]{3,300}", text[:40000]):
        token = token.rstrip(".:")
        if "." not in os.path.basename(token):
            continue
        if token.startswith("~"):
            token = os.path.expanduser(token)
        if os.path.isabs(token):
            real = os.path.realpath(token)
            if not real.startswith(os.path.realpath(root) + os.sep):
                continue
            token = os.path.relpath(real, os.path.realpath(root))
        out.add(token[2:] if token.startswith("./") else token)
    return out


def memory_guard(event):
    """Факт проекта в личной памяти Claude без адреса в каноне — запрет с причиной.

    Аудит 02.10.2026: около половины 75 записей памяти — факты и решения проектов,
    которые не видит никто, кроме этого агента. Проходят: предпочтения работы
    (feedback, user), ссылки на внешние ресурсы с URL, запись со ссылкой на файл проекта,
    правка, которая только сокращает или убирает текст (уборка старой памяти)."""
    try:
        tool, ti = event.get("tool_name") or "", event.get("tool_input") or {}
        if tool not in FILE_TOOLS or not isinstance(ti, dict):
            return None
        path = ti.get(FILE_TOOLS[tool])
        if not isinstance(path, str) or not MEMORY_FILE.search(path) \
                or os.path.basename(path) == "MEMORY.md":
            return None
        root = find_root(event.get("cwd"))
        if not root:
            return None
        before = kb_paths.read(path) if os.path.isfile(path) else ""
        text = memory_text_after(tool, ti, path)
        if before and len(text) < len(before):
            return None
        kind = MEMORY_KIND.search(text)
        if not kind or (kind.group(1).lower() == "reference" and re.search(r"https?://", text)):
            return None
        tracked = kb_turns.git(root, "ls-files", "-z")
        tracked = set(tracked.decode("utf-8", "replace").split("\0")) if tracked else set()
        if memory_pointers(text, root) & tracked:
            return None
        return deny(f"Память агента — не база проекта {os.path.basename(root)}: факт проекта "
                    "сначала запиши в базу (глава, NOW или журнал проекта), а в памяти оставь "
                    "ссылку на этот файл (путь в проекте). Предпочтения работы (type: feedback/"
                    "user) и внешние ссылки с URL пишутся без ограничений.")
    except Exception:
        return None


def record_effects(event, roots, sid, agent):
    """Классы следствий разрешённого инструмента — в ход сессии каждого затронутого
    проекта. Без текста команд, хостов и адресов; для правки файла — путь в проекте."""
    tool, ti = event.get("tool_name") or "", event.get("tool_input") or {}
    for root in roots:
        try:
            effects = []
            if tool in SHELL_TOOLS:
                cmd = command_of(ti)
                effects = [[c, k] for c, k in kb_turns.shell_effects(cmd, shell_segments(cmd),
                                                                     shell_read_only)]
            elif tool.startswith("mcp__"):
                if not mcp_read_only(tool):
                    effects = [["certain", "mcp"]]
            else:
                paths = []
                if tool in FILE_TOOLS and isinstance(ti, dict) and \
                        isinstance(ti.get(FILE_TOOLS[tool]), str):
                    paths = [ti[FILE_TOOLS[tool]]]
                elif tool == "apply_patch":
                    paths = [p for _, p in patch_paths(ti)]
                cwd = event.get("cwd") or root
                for p in paths:
                    full = os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd, p))
                    if full.startswith(os.path.realpath(root) + os.sep):
                        effects.append(["certain", "file",
                                        os.path.relpath(full, os.path.realpath(root))[:200]])
            if effects:
                # Внешний аудит 03.10.2026: попытка не доказывает выполнение инструмента.
                with kb_turns.file_lock(state_path(sid, root)):
                    state = load_state(sid, root)
                    if not state or not state.get("turn"):
                        continue
                    calls = state["turn"].get("calls")
                    if calls is None:
                        # Ход начат до 7.7: прежние следствия — попытки с неизвестным исходом,
                        # иначе пересборка effects из calls стирала их (ревью 7.7.0).
                        old = state["turn"].get("effects", [])
                        calls = [{"id": "legacy", "effects": old, "outcome": "attempt"}] if old else []
                    ident = tool_event_key(event)
                    if event.get("tool_use_id") and any(c["id"] == ident for c in calls):
                        continue
                    calls = (calls + [{"id": ident, "effects": effects, "outcome": "attempt"}])[-80:]
                    state["turn"]["calls"] = calls
                    state["turn"]["effects"] = [e for c in calls for e in c["effects"]][-80:]
                    save_state(state)
        except Exception:
            continue


def tool_event_key(event):
    """Внешний аудит 03.10.2026: связать события без сохранения аргументов/секретов."""
    value = event.get("tool_use_id") or json.dumps(
        [event.get("tool_name"), event.get("tool_input")], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(str(value).encode()).hexdigest()


def on_tool_result(event, agent):
    """Внешний аудит 03.10.2026: необязательные PostToolUse/Failure; HOOK_EVENTS прежние.
    Только событие результата меняет attempt; отсутствие события не означает успех."""
    sid = event.get("session_id")
    if not sid:
        return None
    response = event.get("tool_response")
    failed = event.get("hook_event_name") == "PostToolUseFailure"
    if isinstance(response, dict):
        failed |= bool(response.get("isError") or response.get("is_error") or response.get("interrupted"))
        failed |= bool(response.get("error"))
        failed |= response.get("success") is False
        failed |= any(response.get(k) not in (None, 0) for k in ("exit_code", "exitCode", "returncode"))
    ident = tool_event_key(event)
    for root in touched_roots(event):
        try:
            with kb_turns.file_lock(state_path(sid, root)):
                state = load_state(sid, root)
                if not state or not state.get("turn"):
                    continue
                calls = state["turn"].get("calls", [])
                for call in reversed(calls):
                    if call["id"] == ident and call["outcome"] == "attempt":
                        call["outcome"] = "failed" if failed else "succeeded"
                        save_state(state)
                        break
        except Exception:
            continue
    return None


def on_tool(event, agent):
    tool = event.get("tool_name") or ""
    sid = event.get("session_id")
    if tool in READ_TOOLS or not sid:
        return None
    guarded = memory_guard(event)
    if guarded:
        return guarded
    roots = touched_roots(event)
    decision = gate(event, agent, roots)
    if decision is None:
        record_effects(event, roots, sid, agent)
    return decision


def gate(event, agent, roots):
    tool = event.get("tool_name") or ""
    sid = event.get("session_id")
    tool_input = event.get("tool_input") or {}
    cmd = command_of(tool_input) if tool in SHELL_TOOLS else ""
    for root in roots:
        state, _ = session_state(sid, root, agent)
        if not state or state.get("confirmed") or state.get("error"):
            continue
        request = parse_confirm(cmd) if cmd else None
        if request is not None:
            target = find_root(request.root) or os.path.realpath(request.root)
            if target == root:
                confirmed, why = verify(root, state, request.token, request.bundle,
                                        request.no_role)
                if not confirmed:
                    return deny(f"KB-вход не подтверждён: {why}")
                state["confirmed"] = confirmed
                save_state(state)
                continue
        if tool in SHELL_TOOLS and shell_read_only(cmd):
            continue
        if tool.startswith("mcp__") and mcp_read_only(tool):
            continue
        return deny(deny_reason(state, kb_entry.declared_roles(root)[0]))
    return None


def capture_mode():
    mode = os.environ.get("KB_CAPTURE_MODE", "").strip().lower()
    if not mode:
        try:
            with open(os.path.join(state_root(), "capture-mode"), encoding="utf-8") as f:
                mode = f.read().strip().lower()
        except OSError:
            mode = "record"
    return mode if mode in CAPTURE_MODES else "record"


def finish_turn(state, interrupted=False, stop_hook_active=False):
    """Итог хода в реестр: классы следствий, изменённые файлы, дошло ли до базы."""
    # Внешний аудит 03.10.2026: второй Stop читает уже закрытый ход, а не старую копию.
    with kb_turns.git_budget(), kb_turns.file_lock(state_path(state["session"], state["root"])):
        current = load_state(state["session"], state["root"])
        if not current:
            return
        state.clear()
        state.update(current)
        _finish_turn(state, interrupted, stop_hook_active)


def _finish_turn(state, interrupted=False, stop_hook_active=False):
    """Итог при уже удерживаемой блокировке пары сессия–проект."""
    turn, root, sid = state.get("turn"), state.get("root"), state.get("session")
    if not turn or not root or not os.path.isdir(root):
        return
    snap = kb_turns.load_snap(sid, root)
    changed = kb_turns.changed_since(root, snap)
    effects = turn.get("effects", [])
    file_paths = {e[2] for e in effects if len(e) > 2}
    know, _ = kb_turns.split_knowledge(root, changed | file_paths)
    know = set(know)
    work = {f for f in changed if f not in know}
    certain = [e for e in effects if e[0] == "certain" and not (len(e) > 2 and e[2] in know)]
    kinds = {}
    for e in effects:
        key = f"{e[0]}:{e[1]}"
        kinds[key] = kinds.get(key, 0) + 1
    outcomes = {"attempt": 0, "succeeded": 0, "failed": 0}
    succeeded = 0
    for call in turn.get("calls", []):
        outcome = call["outcome"]
        outcomes[outcome] += 1
        if outcome == "succeeded":
            succeeded += sum(1 for e in call["effects"] if e[0] == "certain"
                             and not (len(e) > 2 and e[2] in know))
    if "calls" not in turn:
        outcomes["attempt"] = len(effects)  # старый ход после обновления — исход неизвестен
    row = {"ts": now_iso(), "ts_epoch": time.time(), "session": str(sid)[:12],
           "agent": state.get("agent"), "project": turn.get("project", os.path.basename(root)), "mode": capture_mode(),
           "project_key": turn.get("project_key") or kb_turns.root_key(root),
           "worktree": bool(turn.get("worktree")), "outcomes": outcomes,
           "certain_succeeded": succeeded,
           "observation_incomplete": not snap or bool(snap.get("incomplete") or snap.get("end_incomplete")),
           "certain": len(certain), "uncertain": sum(1 for e in effects if e[0] == "uncertain"),
           "kinds": kinds, "work_files": len(work), "knowledge_files": len(know & changed),
           "decision": bool(turn.get("decision")), "interrupted": interrupted,
           "stop_hook_active": stop_hook_active, "trigger": turn.get("trigger", "human")}
    kb_turns.record(root, row)
    state["last_turn"] = {k: row[k] for k in ("ts", "certain", "uncertain", "work_files",
                                              "knowledge_files", "decision", "interrupted")}
    state["turn"] = None
    save_state(state)


def on_stop(event, agent):
    """Конец хода. 7.5 — только запись, агенту ничего не говорится: неделя замера
    точности классификации до подсказок и блокировок (решение 02.10.2026). Любая
    собственная ошибка здесь молча пропускается: замок входа ею не открывается."""
    sid = event.get("session_id")
    if not sid:
        return None
    folder = os.path.join(state_root(), "sessions")
    try:
        names = [n for n in os.listdir(folder)
                 if n.startswith(f"{safe_name(sid)}--") and n.endswith(".json")]
    except OSError:
        return None
    for name in names:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                state = json.load(f)
            finish_turn(state, stop_hook_active=bool(event.get("stop_hook_active")))
        except Exception:
            continue
    return None


def run_hook(agent):
    if os.environ.get("KB_ENTRY_HOOK", "").strip().lower() in ("off", "0", "no", "false"):
        return 0
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except ValueError:
        event = {}
    name = event.get("hook_event_name") or ""
    handlers = {"SessionStart": on_session_start, "UserPromptSubmit": on_prompt,
                "PreToolUse": on_tool, "Stop": on_stop,
                "PostToolUse": on_tool_result, "PostToolUseFailure": on_tool_result}
    handler = handlers.get(name)
    if not handler:
        return 0
    try:
        if name == "SessionStart":
            payload = handler(event, agent)  # его отдельный бюджет включает обновление и вход
        else:
            with kb_turns.git_budget():
                payload = handler(event, agent)
    except Exception as exc:  # собственная ошибка не блокирует машину — но видна
        if name == "Stop":
            return 0                                  # реестр хода — замер, не вход
        sid = event.get("session_id")
        root = find_root(event.get("cwd"))
        if sid and root:
            try:
                state = load_state(sid, root) or {"schema": 2, "session": sid, "root": root,
                                                  "armed_at": now_iso(), "confirmed": None}
                state["error"] = f"{type(exc).__name__}: {exc}"
                save_state(state)
            except Exception:
                pass
        notice = (f"KB-вход: hook упал ({type(exc).__name__}: {exc}); замок открыт. Вход — "
                  f"вручную: python3 {q(os.path.join(scripts_dir(), 'kb_entry.py'))} <корень> "
                  "--role <id>")
        payload = {"systemMessage": notice}
        if name in ("SessionStart", "UserPromptSubmit"):
            payload = context_payload(name, notice, notice)
    if payload:
        try:
            emit(payload)
        except Exception:
            pass
    return 0


# ---------------------------------------------------------------- confirm / text / status

def sessions_of(root, days=2):
    folder = os.path.join(state_root(), "sessions")
    out, limit = [], time.time() - days * 86400
    try:
        names = [n for n in os.listdir(folder) if n.endswith(f"--{root_key(root)}.json")]
    except OSError:
        return out
    for name in names:
        path = os.path.join(folder, name)
        try:
            if os.path.getmtime(path) < limit:
                continue
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            continue
        if state.get("root") == os.path.realpath(root):
            out.append(state)
    return out


def confirm(root, token, sid, bundle=None, no_role=None):
    """Проверка меток из командной строки. Замок снимает hook до запуска этой
    команды; здесь — квитанция и запись для среды без hook'а, если она возможна."""
    root = os.path.realpath(root)
    sid = sid or session_from_env()
    try:
        state = load_state(sid, root)
        others = [s for s in sessions_of(root) if s.get("session") != sid]
    except Exception:
        state, others = None, []
    done = (state or {}).get("confirmed")
    checked = None
    if done:
        checked, _ = check_marks(candidates(root, None, done.get("bundle")), fragments_of(token))
    # Внешний аудит 03.10.2026: старая квитанция тоже требует полного входа роли.
    if done and checked and not checked.get("blocking"):
        confirmed = done                      # hook уже проверил и записал эту команду
    else:
        confirmed, why = verify(root, state, token, bundle, no_role)
        if not confirmed:
            print(f"ENTRY_NOT_CONFIRMED: {why}")
            return 1
        try:
            if state:
                state["confirmed"] = confirmed
                save_state(state)
            for other in others:   # файл входа называет сессию, которой его выдал hook
                if other.get("bundle") == confirmed["bundle"] and not other.get("confirmed"):
                    other["confirmed"] = confirmed
                    save_state(other)
                    state = state or other
        except OSError as exc:
            print(f"  (состояние сессии не записано: {exc}; при hook'е замок снимает он)")
    if state and (state.get("confirmed") or {}).get("bundle") == confirmed["bundle"]:
        print(f"ENTRY_CONFIRMED: роль {', '.join(confirmed['roles']) or 'не выбрана'}"
              + (f" (без роли: {confirmed['no_role']})" if confirmed.get("no_role") else "")
              + f" · сессия {state.get('session')}")
    else:
        print("ENTRY_MARKS_OK: метки верны, но сессии с замком не найдено — без hook'а замка нет")
    print(confirmed["receipt"])
    print("SESSION_ACTION=PUT_ENTRY_RECEIPT_IN_FIRST_ANSWER")
    return 0


def text_entry(root, roles, agent):
    """Вход без hook'а: собирает и печатает, состояние сессии не трогает."""
    state, all_roles = start_entry(root, None, agent, "text", roles or None)
    print(entry_message(state, all_roles, "вход вручную", due_summary(root), agent, inline=False)
          .replace(confirm_command(root), confirm_command(root, state["bundle"])))
    return 0


def status(root, sid):
    root = os.path.realpath(root)
    sid = sid or session_from_env()
    state = load_state(sid, root)
    if state:
        c = state.get("confirmed")
        print(f"ENTRY_STATE: {'CONFIRMED ' + c['at'] if c else 'NOT_CONFIRMED'} · сессия {sid}")
        print(f"  {(c or state).get('receipt', '')}")
    else:
        print(f"ENTRY_STATE: NO_SESSION_RECORD · сессия {sid or 'не известна'}")
    for line in install_status():
        print(f"  {line}")
    return 0


# ---------------------------------------------------------------- что выпуск 7.4 просит от проекта

def foreign_entry_hooks(root):
    """Собственные hook'и старта сессии проекта (не kb_start) — вход станет двойным."""
    found = []
    for agent in ("claude", "codex"):
        path = settings_path(agent, root)
        try:
            data, _ = read_settings(path)
        except (ValueError, OSError):
            continue
        for group in (data.get("hooks") or {}).get("SessionStart", []):
            if isinstance(group, dict) and not ours(group):
                for hook in group.get("hooks", []) or []:
                    if isinstance(hook, dict) and hook.get("command"):
                        # Внешний аудит 03.10.2026: команда может содержать значение доступа.
                        digest = hashlib.sha256(str(hook["command"]).encode("utf-8")).hexdigest()[:12]
                        found.append((os.path.relpath(path, root), "SessionStart", digest))
    return found


def project_actions(root):
    """Действия выпуска 7.4 для проекта, номер которого менять не нужно.

    02.10.2026: после 7.4.0 «обновись» и kb_due отвечали «миграция не нужна», а
    продукт на Odoo оставался с пятью ролями без `entry_role` и своим hook'ом
    входа — требования выпуска лежали только в migration.md, который читают при
    поднятом номере (повтор 7.3.0 → 7.3.1). Номер проекта и действия выпуска —
    разные вещи; действия печатаются, пока не сделаны."""
    if not find_root(root):
        return []
    root = os.path.realpath(root)
    actions = []
    roles, default = kb_entry.declared_roles(root)
    if len(roles) > 1 and not default:
        actions.append(f"ролей {len(roles)}, а `entry_role` в PROJECT_ROLES.json нет: объяви роль "
                       "большинства задач — иначе каждый новый чат сначала собирает вход роли, "
                       "без неё замок входа не откроется (references/migration.md → release_actions; references/service-layer.md → entry)")
    for path, event, digest in foreign_entry_hooks(root):
        actions.append(f"свой hook старта сессии в {path} ({event}, sha256:{digest}): "
                       "если он собирает вход, "
                       "сними его, когда общий kb_start установлен на машине, иначе вход двойной; "
                       "hook другого назначения оставь (references/migration.md → release_actions)")
    entry = kb_paths.locate(root, "entry")
    if entry.path:
        size = os.path.getsize(entry.path)
        if size > NOW_LIMIT:
            actions.append(f"{os.path.relpath(entry.path, root)} — {size // 1024} КБ: "
                           "проверь, не стал ли NOW хроникой; размер сам по себе не ошибка. "
                           "Проверь содержание, назначение и потребителей; если это хроника — "
                           "карточка (где мы, что открыто, решения, чего ждём), хронику дословно "
                           "в архивный файл со ссылкой (references/service-layer.md → service_pass)")
    rules = "".join(kb_paths.read(p) for p in kb_paths.rules_files(root))
    if rules and "kb_start" not in rules:
        actions.append("правила проекта не называют исполняемый вход: шаг входа замени шаблонным "
                       "(hook kb_start; без hook — kb_entry.py --role) вместо порядка чтения прозой "
                       "(references/migration.md → release_actions; assets/templates/CLAUDE.md → Вход)")
    return actions


# ---------------------------------------------------------------- установка hook'ов

def hook_command(agent):
    first, second = ("codex", "claude") if agent == "codex" else ("claude", "codex")
    return (f"sh -c 'for d in \"$HOME/.{first}/skills/kb-architect\" "
            f"\"$HOME/.{second}/skills/kb-architect\"; do [ -f \"$d/scripts/kb_start.py\" ] && "
            f"exec python3 \"$d/scripts/kb_start.py\" hook --agent {agent}; done; exit 0'")


def ours(group):
    return isinstance(group, dict) and any(
        isinstance(h, dict) and "kb_start.py" in str(h.get("command", ""))
        and " hook " in str(h.get("command", "")) for h in group.get("hooks", []) or [])


def settings_path(agent, project):
    base = os.path.realpath(project) if project else os.path.expanduser("~")
    if agent == "codex":
        return os.path.join(base, ".codex", "hooks.json")
    return os.path.join(base, ".claude", "settings.json")


def wanted_groups(agent):
    groups = {}
    for event, claude_matcher, codex_matcher, timeout, message in HOOK_EVENTS:
        matcher = codex_matcher if agent == "codex" else claude_matcher
        hook = {"type": "command", "command": hook_command(agent), "timeout": timeout}
        if message and (agent == "codex" or event == "SessionStart"):
            hook["statusMessage"] = message
        if agent == "codex" and event in ("SessionStart", "UserPromptSubmit"):
            # Только события с контекстом для агента: на Stop Codex пишет «ignoring
            # additionalContextLimit … cannot emit additionalContext» (владелец, 03.10.2026).
            hook["additionalContextLimit"] = 0
        group = {"hooks": [hook]}
        if matcher:
            group = {"matcher": matcher, **group}
        groups[event] = group
    return groups


def read_settings(path):
    """(данные, исходный текст); ValueError — файл нельзя безопасно менять."""
    try:
        with open(path, encoding="utf-8") as f:
            original = f.read()
    except FileNotFoundError:
        return {}, None
    data = json.loads(original) if original.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("не объект JSON")
    hooks = data.get("hooks")
    if hooks is None:
        data.pop("hooks", None)
    elif not isinstance(hooks, dict) or any(not isinstance(v, list) for v in hooks.values()):
        raise ValueError("раздел hooks не в формате {событие: [группы]}")
    return data, original


def installed(path, agent):
    try:
        data, _ = read_settings(path)
    except ValueError:
        return "UNREADABLE"
    hooks = data.get("hooks") or {}
    want = wanted_groups(agent)
    found = {e: [g for g in hooks.get(e, []) if ours(g)] for e in want}
    if not any(found.values()):
        return "MISSING"
    return "INSTALLED" if all(found[e] == [want[e]] for e in want) else "DIFFERENT"


def install_status():
    """Строки «исполняемый вход <агент>: состояние» для агентов, установленных на машине."""
    lines = []
    for agent in ("claude", "codex"):
        path = settings_path(agent, None)
        if os.path.isdir(os.path.dirname(path)):
            state = installed(path, agent)
            note = " (Codex исполняет его после одобрения в «Review hooks»)" \
                if agent == "codex" and state == "INSTALLED" else ""
            lines.append(f"исполняемый вход {agent} (пользователь): {state}{note} · {path}")
    return lines


def install(agent, project, check, remove):
    path = settings_path(agent, project)
    state = installed(path, agent)
    if check:
        print(f"{state} {agent} {path}")
        return 0 if state == "INSTALLED" else 1
    if (state == "INSTALLED" and not remove) or (state == "MISSING" and remove):
        print(f"{'NOTHING_TO_REMOVE' if remove else 'UNCHANGED'} {agent} {path}")
        return 0
    try:
        data, original = read_settings(path)
    except ValueError as exc:
        print(f"BLOCKED: {path}: {exc}; не трогаю")
        return 2
    hooks = data.setdefault("hooks", {})
    want = wanted_groups(agent)
    for event in want:
        kept = [g for g in hooks.get(event, []) if not ours(g)]
        if not remove:
            kept.append(want[event])
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks", None)
    target = os.path.realpath(path)          # симлинк dotfiles остаётся симлинком
    os.makedirs(os.path.dirname(target), exist_ok=True)
    mode = stat.S_IMODE(os.stat(target).st_mode) if os.path.exists(target) else 0o600
    backup = None
    if original is not None:
        backup = f"{target}.kb-start-backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        with open(backup, "w", encoding="utf-8") as f:
            f.write(original)
        os.chmod(backup, mode)
    tmp = f"{target}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, target)
    print(f"{'REMOVED' if remove else 'INSTALLED'} {agent} {path}"
          + (f" (прежний файл: {backup})" if backup else ""))
    if not remove:
        print("Новые сессии получают вход сами; открытые — при следующей записи или реплике.")
        if agent == "codex":
            print("ДЕЙСТВИЕ ВЛАДЕЛЬЦА: Codex запускает новый hook только после одобрения — "
                  "Settings → Hooks или «Review hooks» у поля ввода (в терминале /hooks). "
                  "Одобрение держится, пока не меняется запись hook'а; обновление скилла его "
                  "не сбрасывает.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hook")
    h.add_argument("--agent", choices=("claude", "codex"), default="claude")
    c = sub.add_parser("confirm")
    c.add_argument("root")
    c.add_argument("--token", required=True)
    c.add_argument("--bundle")
    c.add_argument("--no-role")
    c.add_argument("--session")
    t = sub.add_parser("text")
    t.add_argument("root")
    t.add_argument("--role", action="append", default=[])
    t.add_argument("--agent", choices=("claude", "codex"))
    s = sub.add_parser("status")
    s.add_argument("root")
    s.add_argument("--session")
    i = sub.add_parser("install")
    i.add_argument("--agent", choices=("claude", "codex"), default="claude")
    i.add_argument("--project")
    i.add_argument("--check", action="store_true")
    i.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if args.cmd == "hook":
        return run_hook(args.agent)
    if args.cmd == "install":
        return install(args.agent, args.project, args.check, args.remove)
    root = find_root(args.root) or os.path.realpath(args.root)
    if args.cmd == "confirm":
        return confirm(root, args.token, args.session, args.bundle, args.no_role)
    if args.cmd == "text":
        return text_entry(root, args.role, args.agent)
    return status(root, args.session)


if __name__ == "__main__":
    sys.exit(main())
