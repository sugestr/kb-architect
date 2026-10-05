#!/usr/bin/env python3
"""«Закрой сессию»: что эта сессия сделала и узнала — из её журнала, для сверки с каноном.

    python3 kb_session.py <корень> [--transcript PATH] [--session ID] [--out DIR] [--tz ZONE]
    python3 kb_session.py <корень> --done [--note "что осталось"]

Читает журнал сессии целиком, включая часть до сжатия контекста и журналы её субагентов:
Claude Code — ~/.claude/projects/<проект>/<сессия>.jsonl (и <сессия>/subagents/*.jsonl),
Codex — ~/.codex/sessions/**/rollout-*-<поток>.jsonl (сессию берёт из CLAUDE_CODE_SESSION_ID
или CODEX_THREAD_ID). Кладёт в --out кандидатов:

  owner.md      все слова владельца: реплики, ответы цитатой, сообщения посреди хода;
  actions.md    действия вне репозитория: внешние системы, серверы, HTTP, выкладка, push и
                коммиты не своего проекта, конверты в чужие инбоксы, сообщения сессиям,
                публикации, планировщик, делегаты, память агента, отправки форм в браузере;
  writes.md     файлы проекта, записанные в сессии, — в корнях знания и вне их;
  questions.md  вопросы агента владельцу — проверить, получен ли ответ;
  current.md    строки, снятые с current коммитами этой сессии;
  parts/        хронология слов владельца и агента частями.

Значения, похожие на пароли, токены и ключи, маскируются до записи на диск, но не все:
части — для самой сессии; другому агенту — только после просмотра. Результаты инструментов
в части не попадают. Время — местное (часовой пояс машины или --tz). Скрипт ничего не
решает: адрес в каноне у каждого пункта находит агент по references/capture.md → close.
--done отмечает выполненную команду для hook'а.
Код 0 — сводка сформирована; 2 — журнал или проект не найдены.
"""

from __future__ import annotations

import datetime
import glob
import json
import math
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kb_paths      # noqa: E402
import kb_start      # noqa: E402
import kb_turns      # noqa: E402

PART_BYTES = 100_000
DEDUP_SECONDS = 15 * 60
CREDENTIAL_WINDOW = 10 * 60
SERVICE_TAGS = ("system-reminder", "local-command-caveat", "local-command-stdout",
                "local-command-stderr", "command-name", "command-message", "command-args",
                "bash-input", "bash-stdout", "bash-stderr", "user-prompt-submit-hook",
                "ide_selection", "ide_opened_file")
TAG_BLOCK = re.compile(r"<(%s)\b[^>]*>.*?</\1>" % "|".join(SERVICE_TAGS), re.S)
IMAGE = re.compile(r"\[Image(?: #\d+)?:[^\]]*\]|<image\b[^>]*>(?:.*?</image>)?", re.S)
SERVICE_START = ("This session is being continued", "Caveat: The messages below",
                 "Base directory for this skill:", "[Request interrupted", "[Cross-session",
                 "Your response above was", "Tool loaded.")
NOTICE_START = ("[Cross-session delivery notice]", "[Cross-session idle notice]")
CODEX_CONTEXT = ("<environment_context", "<user_instructions", "<permissions", "# AGENTS.md",
                 "<INSTRUCTIONS", "<turn_aborted", "# Files mentioned by the user", "<image",
                 "<external_codex_apps", "<codex_", "<user_shell_command")
TEMP = re.compile(r"(?:^|/)(?:tmp|private/tmp|var/folders)/|scratchpad|tool-results")
MEMORY = re.compile(r"/\.claude/projects/[^/]+/memory/|/\.codex/memories/")
# Безопасные опции ssh не делают чтение «действием на сервере»; ProxyCommand и прочие — делают.
SSH_SAFE = re.compile(r"\s-o\s*(?:BatchMode|ConnectTimeout|ServerAliveInterval|ServerAliveCountMax|"
                      r"StrictHostKeyChecking|LogLevel|ConnectionAttempts)=\S+")
GH_WRITE = re.compile(r"\bgh\s+(?:issue|pr|release|repo|api)\s+(?:create|edit|close|comment|"
                      r"upload|delete|merge|reopen|-X\s*(?:POST|PATCH|PUT|DELETE))")
HEREDOC = re.compile(r"(<<-?\s*(['\"]?)(\w+)\2[^\n]*)\n.*?\n[ \t]*\3[ \t]*(?=\n|$)", re.S)
PIECE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
PLANNER = {"CronCreate", "CronDelete", "ScheduleWakeup", "RemoteTrigger"}
SESSION_SEND = {"SendMessage", "mcp__ccd_session_mgmt__send_message", "send_message"}
DELEGATE_TOOLS = {"Agent", "Task", "spawn_agent", "followup_task"}
BROWSER = re.compile(r"^mcp__(?:Claude_Browser|claude-in-chrome|playwright|Control_Chrome|computer-use)__")
BROWSER_WRITE = re.compile(r"(?i)send|submit|publish|post|confirm|delete|remove|pay|order|save|"
                           r"отправ|опубликов|подтверд|удал|оплат|заказ|сохран|подпис|принять|accept")
CODE_CALL = re.compile(r"\btools\.([A-Za-z_]\w*)\s*\(")

# Секреты: маскируются до записи на диск (05.10.2026: самопроверка отдала Codex два пароля,
# которые агент повторил в своём ответе). Маска — помощь, не гарантия; владелец 05.10: «не
# заморачиваться на пароли так сильно» — скрывается только то, что само похоже на значение.
KW = (r"(?:(?:password|passwd|passphrase|pwd|PIN|token|secret|api[_ -]?key|apikey|credentials?|"
      r"client_secret)(?![A-Za-z])|пароль|парол[яеюь]|heslo|hesla|пин-?код|токен|секрет\w*)")
LEFT = r"(?<![A-Za-zА-Яа-яЁё])"
SECRET_RX = [
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
]
SECRET_KV = re.compile(r"(?i)(" + LEFT + KW + r"[^\n:=—]{0,24}?\s*(?:[:=—]|\s-\s|\bis\b|\bэто\b)\s*)"
                       r"([\"'«`]?)([^\s\"'»`,;]{4,})")
SECRET_QUOTED = re.compile(r"(?i)(" + LEFT + KW + r"[^\n]{0,40}?)([\"'«`])([^\"'»`\n]{4,64})([\"'»`])")
SECRET_NEAR = re.compile(r"(?i)(" + LEFT + KW + r"(?:[ \t]+[^\s]{1,20}){0,3}?[ \t]+)([^\s\"'«»`,;]{6,64})")
USERINFO = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)")
CLI_PASS = re.compile(r"(\bsshpass\s+-p\s*|\b(?:mysql|mysqldump|mariadb)\b[^\n]*?\s-p(?=\S)|"
                      r"\bredis-cli\b[^\n]*?\s-a\s+|(?:^|\s)(?:-u|--user)\s+[^\s:]+:)(['\"]?)([^\s'\"]+)")
TOKEN = re.compile(r"(?<![\w/.-])[A-Za-z0-9_=+-]{24,}(?![\w/.-])")
ID_PREFIX = re.compile(r"^(?:toolu|srvtoolu|call|req|msg|local|task|file|resp|run|wf|sess)_")


def entropy(s):
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def looks_secret(token):
    if re.fullmatch(r"[0-9a-f-]+", token, re.I) or ID_PREFIX.match(token):   # хеши, uuid, id среды
        return False
    classes = sum(bool(re.search(rx, token)) for rx in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes == 3 and entropy(token) >= 3.6


def secretish(value):
    """Похоже на значение, а не на слово: латиница с цифрой, особым символом или смешанным регистром."""
    value = value.strip("«»\"'`.,;:)(")
    if re.match(r"(?i)^(?:https?://|/|~|\.\.?/)", value) or re.fullmatch(r"[\d.,:/-]+", value):
        return False
    if not re.search(r"[A-Za-z]", value) or re.search(r"[А-Яа-яЁё]", value):
        return False
    signs = [bool(re.search(r"\d", value)), bool(re.search(r"[^\w\s./-]", value)),
             bool(re.search(r"[a-z]", value)) and bool(re.search(r"[A-Z]", value))]
    return len(value) >= 6 and any(signs)


def mask(text):
    """(маскированный текст, сколько значений скрыто)."""
    hidden = [0]

    def cut(_m=None):
        hidden[0] += 1
        return "‹скрыто›"
    for rx in SECRET_RX:
        text = rx.sub(cut, text)
    text = USERINFO.sub(lambda m: m.group(1) + cut() + m.group(3), text)
    text = CLI_PASS.sub(lambda m: m.group(1) + m.group(2) + cut(), text)
    text = SECRET_KV.sub(lambda m: m.group(1) + m.group(2) + (cut() if secretish(m.group(3)) else m.group(3)), text)
    text = SECRET_QUOTED.sub(lambda m: m.group(1) + m.group(2) + (cut() if secretish(m.group(3)) else m.group(3))
                             + m.group(4), text)
    text = SECRET_NEAR.sub(lambda m: m.group(1) + (cut() if secretish(m.group(2)) else m.group(2)), text)
    text = TOKEN.sub(lambda m: cut() if looks_secret(m.group(0)) else m.group(0), text)
    return text, hidden[0]


# ---------------------------------------------------------------- журнал

def find_transcript(session, agent_hint=None):
    """(путь, агент) журнала сессии или (None, None)."""
    home = os.path.expanduser("~")
    sid = session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid and agent_hint != "codex":
        found = glob.glob(os.path.join(home, ".claude", "projects", "*", f"{sid}.jsonl"))
        if found:
            return max(found, key=os.path.getmtime), "claude"
    thread = session or os.environ.get("CODEX_THREAD_ID")
    if thread:
        found = glob.glob(os.path.join(os.environ.get("CODEX_HOME") or os.path.join(home, ".codex"),
                                       "sessions", "**", f"rollout-*{thread}.jsonl"), recursive=True)
        if found:
            return max(found, key=os.path.getmtime), "codex"
    return None, None


def records(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            try:
                yield n, json.loads(line)
            except ValueError:
                continue


def epoch(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def owner_kind(text):
    """human | image | peer | notification | notice | service — и очищенный текст."""
    text = str(text or "")
    kind = kb_turns.prompt_kind(text)
    if kind != "human":
        return kind, text.strip()
    stripped = TAG_BLOCK.sub("", text).strip()
    if stripped.startswith(NOTICE_START):
        return "notice", stripped
    if not stripped or stripped.startswith(SERVICE_START):
        return "service", ""
    words = IMAGE.sub("", stripped).strip()
    if not words:
        return "image", ""
    return "human", words


def text_of(content):
    if isinstance(content, str):
        return [content]
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"):
            out.append(str(b.get("text") or ""))
    return out


def js_string(s, i):
    """Строковый литерал JS с позиции кавычки: (значение, конец) или (None, i)."""
    quote = s[i]
    out, j = [], i + 1
    while j < len(s):
        c = s[j]
        if c == "\\" and j + 1 < len(s):
            out.append({"n": "\n", "t": "\t"}.get(s[j + 1], s[j + 1]))
            j += 2
            continue
        if c == quote:
            return "".join(out), j + 1
        out.append(c)
        j += 1
    return None, i


def js_args(s, start):
    """Текст аргументов вызова от «(» до парной «)» с учётом строк."""
    depth, j = 0, start
    while j < len(s):
        c = s[j]
        if c in "'\"`":
            _, j = js_string(s, j)
            if _ is None:
                return s[start:]
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return s[start:j + 1]
        j += 1
    return s[start:]


def code_calls(code):
    """Вызовы инструментов внутри code-mode `exec` Codex: [(имя, вход)]."""
    out = []
    for m in CODE_CALL.finditer(code):
        args = js_args(code, m.end() - 1)
        fields, strings = {}, []
        for f in re.finditer(r"(?:^|[,{\s])([A-Za-z_]\w*)\s*:\s*(['\"`])", args):
            value, _ = js_string(args, f.end() - 1)
            if value is not None:
                fields.setdefault(f.group(1), value)
        for q in re.finditer(r"['\"`]", args):
            value, _ = js_string(args, q.start())
            if value is not None:
                strings.append(value)
                break
        inp = dict(fields)
        if "cmd" not in inp and "command" not in inp and m.group(1) in kb_start.SHELL_TOOLS and strings:
            inp["cmd"] = strings[0]
        if m.group(1) == "apply_patch" and "input" not in inp and strings:
            inp["input"] = strings[0]
        out.append((m.group(1), inp))
    return out


class Session:
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.owner, self.peers, self.notices, self.agent = [], [], [], []
        self.actions, self.writes = [], {}
        self.calls = {}
        self.compactions = self.images = self.browser = 0
        self.first = self.last = None
        self._seen = {}

    def inside(self, path):
        path = os.path.realpath(path)
        return path == self.root or path.startswith(self.root + os.sep)

    def stamp(self, ts):
        if ts:
            self.first = min(self.first or ts, ts)
            self.last = max(self.last or ts, ts)

    def add_owner(self, ts, n, source, raw):
        kind, text = owner_kind(raw)
        if kind == "human":
            key = re.sub(r"\s+", " ", text)[:300]
            seen = self._seen.get(("owner", key))
            # Одна реплика приходит записью очереди и записью пользователя; «Да» через час — новая.
            if seen and abs(epoch(ts) - epoch(seen["t"])) <= DEDUP_SECONDS:
                seen["sources"].add(source)
                return
            item = {"t": ts, "line": n, "sources": {source}, "text": text,
                    "decision": kb_turns.is_decision(text)}
            self._seen[("owner", key)] = item
            self.owner.append(item)
        elif kind == "image":
            self.images += 1
        elif kind in ("peer", "notice"):
            key = (kind, re.sub(r"\s+", " ", text)[:300])
            if key in self._seen:
                return
            self._seen[key] = True
            (self.peers if kind == "peer" else self.notices).append(
                {"t": ts, "line": n, "kind": kind, "text": text})
        elif raw and str(raw).startswith("This session is being continued"):
            self.compactions += 1

    def add_call(self, ts, n, name, inp, ident=None, cwd=None, via=""):
        if name == "exec" and isinstance(inp, dict) and isinstance(inp.get("cmd") or inp.get("code"), str) \
                and CODE_CALL.search(inp.get("cmd") or inp.get("code")):
            for inner, inner_inp in code_calls(inp.get("cmd") or inp.get("code")):
                self.add_call(ts, n, inner, inner_inp, ident, cwd, via)
            return
        for kind, label in classify(name, inp, self, cwd):
            item = {"t": ts, "line": n, "kind": kind + via, "label": label, "result": ""}
            self.actions.append(item)
            if ident:
                self.calls.setdefault(ident, []).append(item)

    def add_result(self, ident, text):
        for item in self.calls.get(ident, []):
            item["result"] = " ".join(str(text or "").split())[:240]

    def write(self, path, cwd=None):
        path = os.path.expanduser(str(path).strip("\"'"))
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd or self.root, path))
        if self.inside(full):
            rel = os.path.relpath(full, self.root)
            self.writes[rel] = self.writes.get(rel, 0) + 1
            return None
        if MEMORY.search(full):
            return ("память агента", full)
        other = kb_start.find_root(os.path.dirname(full))
        if other and os.path.realpath(other) != self.root:
            rel = os.path.relpath(full, other)
            inbox = re.search(r"(?:^|/)_?inbox/", rel)
            return ("конверт в другой проект" if inbox else "файл другого проекта",
                    f"{os.path.basename(other)}/{rel}")
        if TEMP.search(full) or full.startswith("/dev/"):
            return None
        return ("файл вне проекта", full.replace(os.path.expanduser("~"), "~", 1))


def short(text, limit=160):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def remote_kind(cmd):
    """«сервер» — изменение на удалённой машине; «сервер (проверить)» — не распознано; чтение — None."""
    segments = kb_start.shell_segments(cmd)
    if segments is None:
        segments = kb_turns.partial_segments(cmd)
    found = None
    for words in segments:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if not words or os.path.basename(words[0]) not in kb_turns.REMOTE:
            continue
        effects = kb_turns.remote_effects(words, kb_start.shell_read_only, 0)
        if any(c == "certain" for c, _ in effects):
            return "сервер"
        if effects:
            found = "сервер (проверить)"
    return found


def words_of(piece):
    try:
        return shlex.split(piece, posix=True)
    except ValueError:
        return piece.split()


def shell_steps(cmd, session, cwd=None):
    """Проход по командам по порядку с текущим каталогом: git и записи файлов вне проекта.

    Ревью 8.1.0: `cd addons && … && cd .. && git push` — свой проект; `cd ../other && git commit`,
    heredoc в чужой `_inbox/` и `>> …/memory/…` — действия вне проекта."""
    out, here = [], os.path.realpath(cwd or session.root)
    flat = HEREDOC.sub(lambda m: m.group(1), cmd)
    for line in flat.splitlines():
        for piece in PIECE.split(line):
            words = words_of(piece)
            while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
                words = words[1:]
            if not words:
                continue
            name = os.path.basename(words[0])
            if name == "cd":
                target = os.path.expanduser(words[1]) if len(words) > 1 else os.path.expanduser("~")
                here = os.path.realpath(target if os.path.isabs(target) else os.path.join(here, target))
                continue
            if name == "git":
                where, args, i = here, words[1:], 0
                while i < len(args) and args[i].startswith("-"):
                    if args[i] == "-C" and i + 1 < len(args):
                        where = os.path.realpath(os.path.join(here, os.path.expanduser(args[i + 1])))
                        i += 2
                    elif args[i] == "-c":
                        i += 2
                    else:
                        i += 1
                sub = args[i] if i < len(args) else ""
                if sub in kb_turns.GIT_WRITE and not session.inside(where):
                    out.append(("push не своего проекта" if sub == "push" else "чужой репозиторий",
                                short(piece)))
            targets = []
            for i, w in enumerate(words):
                if w in (">", ">>") and i + 1 < len(words):
                    targets.append(words[i + 1])
                elif re.match(r"^\d?>>?[^&>]", w):
                    targets.append(re.sub(r"^\d?>>?", "", w))
            if name == "tee":
                targets += [w for w in words[1:] if not w.startswith("-")]
            if name in ("cp", "mv", "rsync") and len([w for w in words[1:] if not w.startswith("-")]) >= 2 \
                    and not re.match(r"^[^/]+:", words[-1]):
                targets.append(words[-1])
            for t in targets:
                if t and not t.startswith(("&", "/dev/")):
                    got = session.write(t, here)
                    if got:
                        out.append(got)
    return out


def classify(name, inp, session, cwd=None):
    """[(вид, подпись)] действия вне репозитория; чтение и правка своего проекта — пусто."""
    inp = inp if isinstance(inp, dict) else {}
    out = []
    if name in kb_start.SHELL_TOOLS:
        cmd = kb_start.command_of(inp)
        if not cmd:
            return out
        plain = SSH_SAFE.sub("", cmd)
        line = short(cmd.splitlines()[0] if cmd.strip() else cmd)
        for words in (kb_start.shell_segments(plain) or kb_turns.partial_segments(plain)):
            head = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
            base = [os.path.basename(w) for w in head[:3]]
            if ("codex" in base and "exec" in head) or ("claude" in base and ("-p" in head or "--print" in head)):
                out.append(("делегат", line))
                break
        remote = remote_kind(plain)
        if remote:
            out.append((remote, line))
        effects = kb_turns.shell_effects(plain, kb_start.shell_segments(plain), kb_start.shell_read_only)
        if any(k == "deploy" for _, k in effects):
            out.append(("выкладка", line))
        if ("certain", "http") in effects:
            out.append(("HTTP-запись", line))
        if GH_WRITE.search(cmd):
            out.append(("GitHub", line))
        if "kb_report" in cmd and ("--do" in cmd or "--сделать" in cmd):
            out.append(("отчёт о скилле", line))
        out += shell_steps(cmd, session, inp.get("workdir") or cwd)
        return out
    if name in SESSION_SEND:
        to = inp.get("to") or inp.get("session_id") or inp.get("target") or "?"
        body = inp.get("message") or inp.get("text") or ""
        out.append(("сообщение сессии", f"→ {to}: {short(body.splitlines()[0] if body else '', 120)}"))
        return out
    if name == "Artifact":
        action = inp.get("action") or "publish"
        if action in ("publish", "delete", "pin", "unpin"):
            out.append(("публикация страницы", f"{action}: {inp.get('url') or inp.get('file_path') or ''}"))
        return out
    if name in PLANNER or name.startswith("mcp__scheduled-tasks__") and not kb_start.mcp_read_only(name):
        out.append(("планировщик", f"{name}: {short(inp.get('prompt') or inp.get('reason') or inp, 120)}"))
        return out
    if name in DELEGATE_TOOLS:
        out.append(("делегат", f"{inp.get('description') or name}: "
                               f"{short(inp.get('prompt') or inp.get('message') or inp.get('task'), 120)}"))
        return out
    if name == "mcp__ccd_session__spawn_task":
        out.append(("делегат", f"задача-сессия: {inp.get('title') or ''} ({inp.get('cwd') or ''})"))
        return out
    if BROWSER.match(name) or name.endswith("browser_batch"):
        steps = inp.get("actions") if isinstance(inp.get("actions"), list) else [{"input": inp}]
        for step in steps:
            si = step.get("input") if isinstance(step, dict) and isinstance(step.get("input"), dict) else {}
            summary = str(si.get("action_summary") or si.get("action") or "")
            if (name.endswith("form_input") or si.get("action") in (
                    "left_click", "double_click", "triple_click", "type", "key")) and BROWSER_WRITE.search(summary):
                out.append(("браузер: отправка", short(summary, 120)))
            else:
                session.browser += 1
        return out
    if name.startswith("mcp__"):
        parts = name.split("__")
        server = parts[1] if len(parts) > 2 else name
        if server.startswith("ccd_") or kb_start.mcp_read_only(name):
            return out
        brief = {k: v for k, v in inp.items() if isinstance(v, (str, int, float))
                 and k in ("to", "chat_id", "group", "alias", "title", "name", "model", "subject",
                           "message_thread_id", "idempotency_key", "id", "path")}
        out.append(("внешняя система", f"{server}.{parts[-1]} {short(json.dumps(brief, ensure_ascii=False), 120)}"))
        return out
    paths = []
    if name in kb_start.FILE_TOOLS and isinstance(inp.get(kb_start.FILE_TOOLS[name]), str):
        paths = [inp[kb_start.FILE_TOOLS[name]]]
    elif name == "apply_patch":
        paths = [p for _, p in kb_start.patch_paths(inp)]
    for p in paths:
        got = session.write(p, cwd)
        if got:
            out.append(got)
    return out


def parse_claude(path, s, subagent=False):
    via = " (субагент)" if subagent else ""
    for n, r in records(path):
        t, ts = r.get("type"), r.get("timestamp") or ""
        if not subagent:
            s.stamp(ts)
        if t == "user" and not subagent:
            if r.get("isCompactSummary"):
                s.compactions += 1
                continue
            content = (r.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        s.add_result(b.get("tool_use_id"), " ".join(text_of(b.get("content"))))
            for text in text_of(content):
                s.add_owner(ts, n, "реплика", text)
        elif t == "queue-operation" and r.get("operation") == "enqueue" and r.get("content") and not subagent:
            s.add_owner(ts, n, "посреди хода", r["content"])
        elif t == "attachment" and (r.get("attachment") or {}).get("type") == "queued_command" and not subagent:
            a = r["attachment"]
            raw = a.get("prompt") if a.get("prompt") is not None else a.get("content")
            for text in text_of(raw):
                s.add_owner(ts, n, "посреди хода", text)
        elif t == "assistant":
            for b in (r.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and str(b.get("text") or "").strip() and not subagent:
                    s.agent.append({"t": ts, "line": n, "text": b["text"]})
                elif b.get("type") == "tool_use":
                    s.add_call(ts, n, b.get("name") or "", b.get("input"), b.get("id"), r.get("cwd"), via)


def parse_codex(path, s):
    cwd = None
    for n, r in records(path):
        ts, p = r.get("timestamp") or "", r.get("payload") or {}
        s.stamp(ts)
        if r.get("type") == "session_meta":
            cwd = p.get("cwd") or cwd
        if r.get("type") == "turn_context":
            cwd = p.get("cwd") or cwd
        if r.get("type") != "response_item":
            if r.get("type") == "compacted":
                s.compactions += 1
            continue
        kind = p.get("type")
        if kind == "message":
            for text in text_of(p.get("content")):
                if p.get("role") == "user" and not text.lstrip().startswith(CODEX_CONTEXT):
                    s.add_owner(ts, n, "реплика", text)
                elif p.get("role") == "assistant" and text.strip():
                    s.agent.append({"t": ts, "line": n, "text": text})
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            name = p.get("name") or ("shell" if kind == "local_shell_call" else "")
            raw = p.get("arguments") if kind == "function_call" else p.get("input")
            inp = raw
            if isinstance(raw, str) and raw.strip().startswith("{"):
                try:
                    inp = json.loads(raw)
                except ValueError:
                    inp = raw
            if kind == "local_shell_call":
                inp = p.get("action") or {}
            if name == "apply_patch" and isinstance(inp, str):
                inp = {"input": inp}
            if not isinstance(inp, dict):
                inp = {"cmd": str(inp or "")}
            s.add_call(ts, n, name, inp, p.get("call_id"), cwd)
        elif kind in ("function_call_output", "custom_tool_call_output"):
            out = p.get("output")
            s.add_result(p.get("call_id"), out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))


# ---------------------------------------------------------------- вывод

def local(ts, tz):
    try:
        moment = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)[:16]
    return moment.astimezone(tz).strftime("%d.%m %H:%M")


def mask_owner_values(s):
    """Владелец прислал значение отдельной репликой («Я нашёл пароли», затем одно слово): такая
    реплика рядом с упоминанием доступа скрывается целиком (ревью 8.1.0, журнал проекта владельца)."""
    mentions = sorted(epoch(x["t"]) for x in s.owner + s.agent
                      if re.search(r"(?i)" + LEFT + KW, x["text"]))
    hidden = 0
    for o in s.owner:
        value = o["text"].strip()
        if " " in value or len(value) < 4 or len(value) > 80 or re.match(r"(?i)^(?:https?://|/|~)", value):
            continue
        near = any(0 <= epoch(o["t"]) - m <= CREDENTIAL_WINDOW for m in mentions)
        if near or (secretish(value) and len(value) >= 8):
            o["text"] = "‹скрыто: значение отдельной репликой›"
            hidden += 1
    return hidden


def questions(s):
    """Вопросы агента, которые владелец видел: последний текст перед его репликой и в конце."""
    owner_times = sorted(o["t"] for o in s.owner)
    out = []
    agent = sorted(s.agent, key=lambda a: a["t"])
    for i, a in enumerate(agent):
        nxt = agent[i + 1]["t"] if i + 1 < len(agent) else None
        shown = nxt is None or any(a["t"] <= t <= nxt for t in owner_times)
        if not shown:
            continue
        body = re.sub(r"```.*?```", "", a["text"], flags=re.S)
        for line in body.splitlines():
            if "?" in line and len(line.strip()) > 12 and not line.strip().startswith(("|", ">")):
                out.append((a["t"], a["line"], line.strip()))
    return out


def current_removed(root, since):
    entry = kb_paths.locate(root, "entry")
    if not entry.path or not since:
        return None, []
    rel = os.path.relpath(entry.path, root)
    try:
        log = subprocess.run(["git", "-C", root, "log", f"--since={since}", "-p", "--format=@@COMMIT %h",
                              "--", rel], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return rel, []
    removed, commit = [], ""
    for line in log.splitlines():
        if line.startswith("@@COMMIT "):
            commit = line.split()[1]
        elif line.startswith("-") and not line.startswith("---") and line[1:].strip():
            removed.append((commit, line[1:].rstrip()))
    return rel, removed


def knowledge_split(root, rels):
    try:
        import kb_index
        from pathlib import Path
        roots, _ = kb_index.knowledge_roots(Path(root))
    except Exception:
        roots = []
    inside = [r for r in rels if roots and any(r == k.rstrip("/") or r.startswith(k.rstrip("/") + "/")
                                               for k in roots)]
    return roots, inside, [r for r in rels if r not in inside]


def action_lines(s, tz):
    """Уверенные действия — все; «проверить» — первые 10 и счёт, чтобы шум не прятал отправки."""
    lines, unsure = [], []
    for a in sorted(s.actions, key=lambda x: x["t"]):
        text = (f"- {local(a['t'], tz)} · {a['kind']} · {a['label']}"
                + (f"\n  → {a['result']}" if a["result"] else "") + f"  (L{a['line']})")
        (unsure if "(проверить)" in a["kind"] else lines).append(text)
    if unsure:
        lines += ["", f"## Не распознано — {len(unsure)}: чаще чтение; проверь, нет ли среди них изменений", ""]
        lines += unsure[:10] + ([f"- … и ещё {len(unsure) - 10}"] if len(unsure) > 10 else [])
    if s.browser:
        lines += ["", f"Браузер: {s.browser} действий без признаков отправки (просмотр, переходы, снимки)."]
    return lines


def write_out(s, out, tz):
    os.makedirs(os.path.join(out, "parts"), mode=0o700, exist_ok=True)
    total = [0]

    def save(name, lines):
        text, hidden = mask("\n".join(lines).rstrip() + "\n")
        total[0] += hidden
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(os.path.join(out, name), 0o600)

    owner = [f"# Слова владельца — {len(s.owner)}", "",
             "✱ — похоже на решение. Источник «посреди хода» — сообщение, пришедшее во время работы."
             + (f" Изображений без слов: {s.images}." if s.images else ""), ""]
    for o in sorted(s.owner, key=lambda x: x["t"]):
        owner += [f"## {local(o['t'], tz)} · {', '.join(sorted(o['sources']))} · L{o['line']}"
                  + (" ✱" if o["decision"] else ""), o["text"], ""]
    if s.peers or s.notices:
        owner += [f"# Сообщения других сессий и квитанции доставки — {len(s.peers) + len(s.notices)}", "",
                  "Факт или решение из сообщения сессии вносится с адресом источника (сессия, дата).", ""]
        for p in sorted(s.peers + s.notices, key=lambda x: x["t"]):
            owner.append(f"- {local(p['t'], tz)} · L{p['line']} · {short(p['text'], 300)}")
    save("owner.md", owner)

    save("actions.md", [f"# Действия вне репозитория — {len(s.actions)}", "",
                        "У каждого — адрес в каноне (глава, current, журнал, реестр исходящих) или запись сейчас.",
                        ""] + action_lines(s, tz))

    roots, inside, other = knowledge_split(s.root, sorted(s.writes))
    writes = [f"# Файлы проекта, записанные в сессии — {len(s.writes)}", ""]
    if roots:
        writes += [f"Корни знания: {', '.join(roots)}.", "", "## В корнях знания",
                   *[f"- {r}" for r in inside], "",
                   "## Вне корней знания — рабочие заметки, данные, код: решения и факты отсюда — в канон",
                   *[f"- {r}" for r in other]]
    else:
        writes += ["Корни знания не объявлены (`KNOWLEDGE_INDEX.json`): раздели сам — рабочая заметка "
                   "и папка данных адресом не считаются.", "", *[f"- {r}" for r in other]]
    save("writes.md", writes)

    qs = questions(s)
    save("questions.md", [f"# Вопросы агента владельцу — {len(qs)}", "",
                          "Для каждого: ответ с датой и словами, «спрошено, ответа нет» в current "
                          "или «решено, но остановлено».", ""]
         + [f"- {local(t, tz)} · L{n} · {short(q, 300)}" for t, n, q in qs])

    rel, removed = current_removed(s.root, s.first)
    save("current.md", [f"# Снято с current ({rel or 'current не найден'}) в этой сессии — {len(removed)} строк",
                        "", "Каждое действующее правило и открытый вопрос — в главе или в current; "
                        "архив и хроника адресом действующего не считаются.", ""]
         + [f"- {c} · {short(line, 300)}" for c, line in removed[:200]])

    timeline = [(o["t"], f"### ВЛАДЕЛЕЦ {local(o['t'], tz)} · L{o['line']}\n{o['text']}") for o in s.owner]
    timeline += [(a["t"], f"### АГЕНТ {local(a['t'], tz)} · L{a['line']}\n{a['text']}") for a in s.agent]
    timeline += [(a["t"], f"- действие {local(a['t'], tz)} · {a['kind']} · {a['label']}") for a in s.actions
                 if "(проверить)" not in a["kind"]]
    timeline.sort(key=lambda x: x[0])
    chunk, size, part = [], 0, 1
    for _, block in timeline + [("", None)]:
        if block is None or size + len(block.encode()) > PART_BYTES and chunk:
            if chunk:
                save(os.path.join("parts", f"part-{part:02d}.md"), chunk)
                part += 1
            chunk, size = [], 0
        if block is not None:
            chunk.append(block)
            size += len(block.encode()) + 1
    return part - 1, total[0]


def closed_path(sid, root):
    return os.path.join(kb_start.state_root(), "sessions",
                        f"{kb_start.safe_name(sid)}--{kb_start.root_key(root)}.closed")


def mark_done(root, session, note):
    sid = session or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")
    if not sid:
        print("Сессия не определена: укажи --session <id>.")
        return 2
    root = kb_start.find_root(root) or root          # отметка — по корню проекта, как у hook'а
    head = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    line = f"CLOSE_DONE {os.path.basename(root)} · {head or 'без коммита'}" + (f" · {note}" if note else "")
    try:
        path = closed_path(sid, root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"at": kb_start.now_iso(), "head": head, "note": note or ""}, f, ensure_ascii=False)
    except OSError as exc:
        # Живое сравнение 05.10: в песочнице агент перенёс служебное состояние в проект, чтобы
        # записать отметку. Её место — вне проекта; нет доступа — так и сказать.
        print(f"{line} · отметка hook'а не записана ({type(exc).__name__}); скажи это в итоге, "
              "состояние в проект не переносится")
        return 0
    print(line)
    return 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--transcript")
    ap.add_argument("--session")
    ap.add_argument("--agent", choices=("claude", "codex"))
    ap.add_argument("--out")
    ap.add_argument("--tz", help="часовой пояс, например Europe/Madrid; по умолчанию — машины")
    ap.add_argument("--done", action="store_true", help="отметить выполненную команду для hook'а")
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)
    root = os.path.realpath(args.root)
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2
    if args.done:
        return mark_done(root, args.session, args.note)
    transcript, agent = (args.transcript, args.agent) if args.transcript else find_transcript(args.session, args.agent)
    if not transcript or not os.path.isfile(transcript):
        print("Журнал сессии не найден: укажи --transcript <путь> (Claude: ~/.claude/projects/<проект>/"
              "<сессия>.jsonl; Codex: ~/.codex/sessions/…/rollout-…-<поток>.jsonl).")
        return 2
    if not agent:
        with open(transcript, encoding="utf-8", errors="replace") as f:
            agent = "codex" if '"session_meta"' in f.readline() else "claude"
    tz = None
    if args.tz:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(args.tz)
    s = Session(root)
    if agent == "codex":
        parse_codex(transcript, s)
    else:
        parse_claude(transcript, s)
        for sub in sorted(glob.glob(os.path.join(os.path.splitext(transcript)[0], "subagents", "*.jsonl"))):
            parse_claude(sub, s, subagent=True)
    hidden_values = mask_owner_values(s)
    sid = os.path.splitext(os.path.basename(transcript))[0]
    out = args.out or os.path.join(kb_start.state_root(), "close", kb_start.safe_name(sid))
    parts, hidden = write_out(s, out, tz)
    kinds = {}
    for a in s.actions:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    queued = sum(1 for o in s.owner if o["sources"] == {"посреди хода"})
    undelivered = [n for n in s.notices if re.search(r"not approved before|refused|rejected|could not be "
                                                     r"delivered", n["text"], re.I)]
    print(f"ЗАКРЫТИЕ СЕССИИ — {os.path.basename(root)} ({agent}, журнал {os.path.getsize(transcript) // 1024} КБ, "
          f"{local(s.first, tz)}–{local(s.last, tz)}, сжатий {s.compactions})")
    print(f"  слова владельца: {len(s.owner)} (только посреди хода {queued}; похоже на решение "
          f"{sum(1 for o in s.owner if o['decision'])})")
    print(f"  действия вне репозитория: {len(s.actions)}"
          + (" — " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) if kinds else ""))
    if undelivered:
        print(f"  сообщения сессиям без доставки: {len(undelivered)}")
    print(f"  файлов проекта записано: {len(s.writes)}; вопросов агента: {len(questions(s))}; "
          f"скрыто значений, похожих на секреты: {hidden + hidden_values} (маска ловит не все)")
    print(f"  кандидаты: {out} (owner.md, actions.md, writes.md, questions.md, current.md, parts/ — {parts})")
    print("Дальше по references/capture.md → close: у каждого пункта адрес в каноне или запись сейчас;"
          " commit и push; затем kb_session.py <корень> --done. Журнал и эти файлы в репозиторий не"
          " копируются: источник в каноне — «журнал сессии, дата».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
