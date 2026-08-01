#!/usr/bin/env python3
"""kb_lint.py — линтер базы знаний стандарта kb-architect, версия 2.2.

Что изменилось по сравнению с v1:
  * мера объёма — килобайты, а не строки (файл на 103 строки может весить 24 КБ);
  * три профиля файлов: authored (пишем руками), derived (генерирует код),
    mirror (конспект внешней живой системы) — у каждого свои правила;
  * проверка регистрации в INDEX работает по нормализованным путям, а не
    подстрокой (раньше `09_reception_algorithm.md` «находился» внутри
    `09_reception_algorithm_v1.md`);
  * есть конфиг проекта `.kbconfig.yml`: роли, ключевые файлы, лимиты,
    профили по глобам, исключения;
  * авторская дата устаревания (`review_by` / `valid_until`) важнее
    возраста файла;
  * нумерация имён стала опциональным модулем.

Что добавилось в версии 2 (правка про КОНТУРЫ):
  главный режим отказа базы — не протухание внутри одного репозитория,
  а молчаливое расхождение двух контуров: источник на машине владельца и
  облачное зеркало, по которому отвечает сессия. Расхождение в 38 коммитов
  и 309 файлов не вызвало ни одного сообщения ни от одного файла; зеркало
  отвечало «данных нет» там, где в источнике лежали 153 записи, а аудит по
  зеркалу выдал ложную находку о противоречии в правилах. Отсюда:
  * секция конфига `contour`: role (source|mirror), manifest, budget_mb,
    sync_max_age_days, never_mirror;
  * зеркало обязано нести манифест с отметкой синхронизации
    (`synced_from` + `synced_at`) и разделом «Чего здесь нет» — иначе
    отсутствие файла читается как «данных нет»;
  * возраст отметки синхронизации: старше порога — WARN, старше 4× — ERROR;
  * оперативные представления (`never_mirror`) в зеркале — WARN: они
    протухают за дни и гарантированно врут;
  * бюджет объёма лёгкого контура (`budget_mb`);
  * реестр отмен: `status: superseded` без реестра отменённых формулировок —
    старая формулировка продолжает жить в других файлах;
  * незамкнутый цикл: неотправленные коммиты — второй контур не знает о них;
  * флаг `--contour-only` как быстрый предполётный чек.

Что добавилось в версии 2.2 (правка про ЗАПИСЬ и УТВЕРЖДЕНИЕ):
  модель не различала файл-запись и файл-утверждение. Поле `updated` — факт
  об авторе («когда я это трогал»), а читателю нужно другое: «до какого числа
  автор за это отвечает». Снапшот состояния прода с честным `updated` был
  мёртв три месяца, и линтер пропускал его — метаданные безупречны. Спека
  алгоритма без срока годности нормальна; снапшот состояния без срока годности
  дефектен по построению. Отсюда:
  * истёкший `valid_until` / `review_by` — теперь ERROR, а не WARN: просто
    старый файл может быть старым и верным, файл с истёкшим заявленным сроком
    заявленно неверен;
  * тип `snapshot`: утверждение о настоящем, `valid_until` обязателен;
  * тип `attempt` и статус `abandoned`: слой «пробовали, не пошло»;
    обязателен `stopped_at` — незаписанная причина остановки гарантирует,
    что попытку предложат снова; `superseded_by` для attempt не требуется;
  * раздел UNKNOWN в файле «где мы»: на месте пустоты сессия сочиняет;
  * `CORRECTIONS.md` как дешёвый обратный канал: без него сессия,
    обнаружившая ошибку в базе, просто продолжит задачу;
  * флаг `--claims-only` — быстрый чек «что в базе заявленно протухло».

Использование:
    python3 kb_lint.py <путь> [--config .kbconfig.yml]
                              [--profile authored|derived|mirror]
                              [--stale-days N] [--quiet] [--json] [--summary]
                              [--contour-only] [--claims-only]

Код возврата: 0 — ERROR нет, 1 — есть ERROR, 2 — ошибка запуска.
Внешних зависимостей нет: YAML разбирается упрощённым парсером.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import posixpath
import re
import sys
from dataclasses import dataclass, field

# --- значения по умолчанию --------------------------------------------------

CONFIG_NAME = ".kbconfig.yml"

DEFAULT_CONFIG = {
    "profile": "authored",
    "roles": {
        "knowledge": ["knowledge"],
        "decisions": ["decisions"],
        "sources": ["sources"],
        "documents": ["documents"],
        "output": ["output"],
        "archive": ["archive"],
        "inbox": ["_inbox"],
    },
    "entry": {
        "rules": "CLAUDE.md",
        "index": "INDEX.md",
        "status": "STATUS.md",
        "changelog": "CHANGELOG.md",
        "corrections": "CORRECTIONS.md",
    },
    "limits": {
        "rules_kb": 12,
        "index_kb": 12,
        "status_kb": 8,
        "knowledge_kb": 40,
    },
    "profiles": [],          # [{path: glob, profile: имя}]
    "exclude": [],
    "stale_days": 90,
    "mirror_stale_days": 30,
    "modules": [],           # опциональные модули: numbering
    "contour": {
        "role": "source",        # source | mirror
        "manifest": "MIRROR.md",  # файл-манифест зеркала
        "budget_mb": None,        # не задан -> бюджет не проверяется
        "sync_max_age_days": 3,
        "never_mirror": [],       # глобы оперативных представлений
    },
}

PROFILES = ("authored", "derived", "mirror")
CONTOUR_ROLES = ("source", "mirror")

# Роли, содержимое которых не индексируется и не проверяется по существу.
OPAQUE_ROLES = ("sources", "documents", "archive", "inbox")
# Роли, файлы которых обязаны быть зарегистрированы в INDEX.
INDEXED_ROLES = ("knowledge", "decisions", "output")
# Роли, файлы которых обязаны нести полноценный frontmatter (профиль authored).
FRONTMATTER_ROLES = ("knowledge", "decisions")

# Папки, в которые не заходим никогда.
HARD_SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"}

VALID_TYPE = {"reference", "explanation", "decision", "log", "source", "output", "mirror",
              "snapshot", "attempt"}
VALID_STATUS = {"active", "frozen", "superseded", "archived", "abandoned"}
VALID_CONFIDENCE = {"high", "medium", "speculative"}
VALID_SENSITIVITY = {"normal", "restricted", "secret"}

AUTHORED_REQUIRED = ("type", "status", "updated", "source")

RE_ID = re.compile(r"^\d{2}\.\d{2}$")
RE_DECISION_ID = re.compile(r"^decision-\d{4}$")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_KNOWLEDGE_NAME = re.compile(r"^\d{2}\.\d{2}-[a-z0-9][a-z0-9-]*\.md$")
RE_DECISION_NAME = re.compile(r"^\d{4}-[a-z0-9][a-z0-9-]*\.md$")
RE_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
RE_BACKTICK = re.compile(r"`([^`\n]+)`")
RE_FENCED = re.compile(r"```.*?```", re.DOTALL)
RE_INLINE_CODE = re.compile(r"`[^`\n]*`")
RE_RELATIVE_DATE = re.compile(
    r"\b(вчера|позавчера|сегодня|завтра|послезавтра|на прошлой неделе|"
    r"на этой неделе|в прошлом месяце|yesterday|tomorrow|last week|next week)\b",
    re.IGNORECASE,
)
RE_NEXT_HEADING = re.compile(
    r"^(next|próximos|proximos|что дальше|дальше)\b",
    re.IGNORECASE,
)
RE_KEYLINE = re.compile(r"^[A-Za-zА-Яа-я_][\w .\-]*:")

# Раздел манифеста зеркала о том, чего в зеркале нет.
RE_ABSENT_HEADING = re.compile(
    r"^(чего здесь нет|не зеркалится|absent|not mirrored)",
    re.IGNORECASE,
)
# Раздел-реестр отменённых формулировок.
RE_REVOKED_HEADING = re.compile(
    r"^(отменённые формулировки|отмененные формулировки|реестр отмен|revoked)",
    re.IGNORECASE,
)
RE_BOLD_LINE = re.compile(r"^\*\*(.+)\*\*$")

# Раздел «чего мы не знаем» в файле «где мы».
RE_UNKNOWN_HEADING = re.compile(
    r"^(unknown|неизвестно|не\s+знаем)",
    re.IGNORECASE,
)
# Строка-запись в CORRECTIONS: `- 2026-07-28 …`, `2026-07-28 | …`, `| 2026-07-28 | …`.
RE_CORRECTION_ENTRY = re.compile(r"^(?:[-*+]\s+|\|\s*)?(\d{4}-\d{2}-\d{2})\b")
# Маркеры закрытой записи обратного канала.
RE_CORRECTION_CLOSED = re.compile(r"(✔|✅|закрыт|closed|fixed)", re.IGNORECASE)

CORRECTIONS_STALE_DAYS = 180

LEVELS = ("ERROR", "WARN", "INFO")


# --- мелкие утилиты ---------------------------------------------------------


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение числительного: 1 строка, 3 строки, 5 строк."""
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return text.lstrip("﻿")  # BOM ломает распознавание frontmatter


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


_GLOB_CACHE: dict = {}


def glob_re(pattern: str):
    """Компилирует glob в регулярку. `*` не пересекает `/`, `**` — пересекает."""
    if pattern in _GLOB_CACHE:
        return _GLOB_CACHE[pattern]
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if ch == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(ch))
        i += 1
    rx = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[pattern] = rx
    return rx


def path_matches(pattern: str, rel_path: str) -> bool:
    """Глоб без `/` сравнивается с именем файла, с `/` — с путём от корня."""
    pattern = pattern.strip().strip("'\"")
    if not pattern:
        return False
    if "/" not in pattern:
        return bool(glob_re(pattern).match(posixpath.basename(rel_path)))
    return bool(glob_re(pattern).match(rel_path))


def has_glob(s: str) -> bool:
    return any(c in s for c in "*?[")


# --- упрощённый парсер YAML -------------------------------------------------


def _strip_comment(line: str) -> str:
    """Убирает `# комментарий`, не трогая решётку внутри кавычек."""
    out = []
    quote = None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(raw: str):
    """Скаляр или inline-список `[a, b]`."""
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    s = s.strip("'\"")
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return ""
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


def _tokenize(text: str):
    lines = []
    for raw in text.splitlines():
        body = _strip_comment(raw)
        if not body.strip():
            continue
        indent = len(body) - len(body.lstrip(" "))
        lines.append((indent, body.strip()))
    return lines


def _parse_block(lines, i: int, indent: int):
    if i >= len(lines):
        return "", i
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_list(lines, i: int, indent: int):
    items = []
    while i < len(lines) and lines[i][0] == indent and (
        lines[i][1].startswith("- ") or lines[i][1] == "-"
    ):
        head = lines[i][1][1:].strip()
        i += 1
        block = []
        if head:
            block.append((indent + 2, head))
        while i < len(lines) and lines[i][0] > indent:
            block.append(lines[i])
            i += 1
        if block and (len(block) > 1 or RE_KEYLINE.match(block[0][1])) and not block[0][1].startswith("- "):
            base = min(ind for ind, _ in block)
            value, _ = _parse_block(block, 0, base)
            items.append(value)
        elif block:
            items.append(_scalar(block[0][1]))
    return items, i


def _parse_map(lines, i: int, indent: int):
    data = {}
    while i < len(lines) and lines[i][0] == indent:
        content = lines[i][1]
        if content.startswith("- "):
            break
        if ":" not in content:
            i += 1
            continue
        key, _, rest = content.partition(":")
        key = key.strip().strip("'\"")
        rest = rest.strip()
        i += 1
        if rest:
            data[key] = _scalar(rest)
            continue
        # значение — вложенный блок на следующих строках
        if i < len(lines) and (
            lines[i][0] > indent
            or (lines[i][0] == indent and lines[i][1].startswith("- "))
        ):
            child_indent = lines[i][0]
            data[key], i = _parse_block(lines, i, child_indent)
        else:
            data[key] = ""
    return data, i


def parse_yaml(text: str) -> dict:
    """Разбирает подмножество YAML: карты, вложенные карты, списки, inline-списки."""
    lines = _tokenize(text)
    if not lines:
        return {}
    value, _ = _parse_block(lines, 0, lines[0][0])
    return value if isinstance(value, dict) else {}


# --- frontmatter ------------------------------------------------------------


def parse_frontmatter(text: str):
    """Возвращает (dict | None, тело). Плоский YAML + блочные списки."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    raw = text[3:end].strip("\n")
    body = text[end + 4 :]
    data = {}
    last_key = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and last_key is not None:
            item = _scalar(stripped[2:])
            if not isinstance(data.get(last_key), list):
                data[last_key] = []
            data[last_key].append(item)
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        data[key] = _scalar(value) if value else ""
        last_key = key
    return data, body


def is_true(value) -> bool:
    return str(value).strip().lower() in ("true", "yes", "1")


def as_date(value):
    """Строка YYYY-MM-DD -> date, иначе None."""
    s = str(value).strip()
    if not RE_DATE.match(s):
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def as_iso_date(value):
    """ISO-дата или ISO-момент времени -> date. `2026-07-25T10:00:00Z` тоже годится."""
    s = str(value).strip().strip("'\"")
    if not s:
        return None
    head = re.split(r"[T ]", s, 1)[0]
    return as_date(head)


def headings(body: str):
    """Заголовки markdown-тела: `## Что-то` и строки вида `**Что-то**`."""
    out = []
    for line in RE_FENCED.sub("", body).splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            out.append(s.lstrip("#").strip().strip("*_").strip())
            continue
        m = RE_BOLD_LINE.match(s)
        if m:
            out.append(m.group(1).strip().strip("*_").strip())
    return out


# --- модель отчёта ----------------------------------------------------------


@dataclass
class Finding:
    level: str
    path: str
    kind: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass
class Report:
    findings: list = field(default_factory=list)

    def add(self, level: str, path: str, kind: str, message: str) -> None:
        self.findings.append(Finding(level, path, kind, message))

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)


@dataclass
class FileInfo:
    rel: str
    abs: str
    role: str          # knowledge / decisions / ... либо "" (вне ролей)
    profile: str
    fm: dict           # None, если frontmatter нет
    body: str
    text: str
    kb: float
    lines: int


@dataclass
class Context:
    root: str
    cfg: dict
    rep: Report
    today: dt.date
    files: list = field(default_factory=list)     # FileInfo, только .md
    index_paths: set = field(default_factory=set)  # точные цели из INDEX
    index_globs: list = field(default_factory=list)
    ids: dict = field(default_factory=dict)
    skipped: int = 0
    profile_counts: dict = field(default_factory=dict)
    contour_only: bool = False
    contour_bits: list = field(default_factory=list)  # куски строки о контуре для сводки
    contour_facts: dict = field(default_factory=dict)  # то же машиночитаемо, для --json
    all_files: list = None  # кэш обхода всех файлов, не только .md
    claims_only: bool = False
    claims_facts: dict = field(default_factory=dict)  # счётчики про заявления, для сводки и --json

    def claim(self, key: str, n: int = 1) -> None:
        self.claims_facts[key] = self.claims_facts.get(key, 0) + n


# --- конфиг -----------------------------------------------------------------


def load_config(root: str, explicit: str, rep: Report) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # глубокая копия
    path = explicit or os.path.join(root, CONFIG_NAME)
    if not os.path.exists(path):
        if explicit:
            raise FileNotFoundError(path)
        rep.add(
            "INFO", ".", "нет конфига",
            f"конфиг не найден, работаю на дефолтах; создай {CONFIG_NAME}",
        )
        return cfg
    try:
        raw = parse_yaml(read_text(path))
    except Exception as exc:  # парсер простой, лучше не падать целиком
        rep.add("WARN", os.path.basename(path), "конфиг не разобран",
                f"не удалось разобрать конфиг ({exc}); работаю на дефолтах")
        return cfg
    if not isinstance(raw, dict):
        rep.add("WARN", os.path.basename(path), "конфиг не разобран",
                "конфиг не похож на карту ключ-значение; работаю на дефолтах")
        return cfg

    for key in ("profile", "stale_days", "mirror_stale_days"):
        if raw.get(key) not in (None, ""):
            cfg[key] = raw[key]
    for key in ("roles", "entry", "limits"):
        section = raw.get(key)
        if isinstance(section, dict):
            for k, v in section.items():
                if v in (None, ""):
                    continue
                cfg[key][k] = v
    for key in ("exclude", "modules"):
        v = raw.get(key)
        if isinstance(v, list):
            cfg[key] = v
        elif isinstance(v, str) and v:
            cfg[key] = [v]
    if isinstance(raw.get("profiles"), list):
        rules = []
        for item in raw["profiles"]:
            if isinstance(item, dict) and item.get("path") and item.get("profile"):
                rules.append({"path": str(item["path"]), "profile": str(item["profile"])})
        cfg["profiles"] = rules

    load_contour_config(cfg, raw, os.path.basename(path), rep)

    # роли всегда список путей
    for role, value in list(cfg["roles"].items()):
        if isinstance(value, str):
            cfg["roles"][role] = [value] if value else []
        elif not isinstance(value, list):
            cfg["roles"][role] = []
    if cfg.get("profile") not in PROFILES:
        rep.add("WARN", os.path.basename(path), "плохой профиль",
                f"profile: {cfg.get('profile')!r} — неизвестный профиль, беру authored")
        cfg["profile"] = "authored"
    return cfg


def load_contour_config(cfg: dict, raw: dict, cfg_name: str, rep: Report) -> None:
    """Секция `contour`. Все ключи опциональны, дефолт — одиночный контур-источник."""
    section = raw.get("contour")
    if not isinstance(section, dict):
        if section not in (None, ""):
            rep.add("WARN", cfg_name, "плохая секция contour",
                    "contour должен быть картой ключ-значение; беру умолчания "
                    "(role: source)")
        return
    dst = cfg["contour"]

    role = str(section.get("role", "")).strip().lower()
    if role:
        if role in CONTOUR_ROLES:
            dst["role"] = role
        else:
            rep.add("WARN", cfg_name, "плохая роль контура",
                    f"contour.role: {role!r} — неизвестная роль, беру source; "
                    f"допустимо: {', '.join(CONTOUR_ROLES)}")

    manifest = str(section.get("manifest", "")).strip()
    if manifest:
        dst["manifest"] = manifest

    if section.get("sync_max_age_days") not in (None, ""):
        try:
            dst["sync_max_age_days"] = max(0, int(section["sync_max_age_days"]))
        except (TypeError, ValueError):
            rep.add("WARN", cfg_name, "плохой sync_max_age_days",
                    f"contour.sync_max_age_days: {section['sync_max_age_days']!r} — "
                    "не число, беру 3")

    if section.get("budget_mb") not in (None, ""):
        try:
            value = float(str(section["budget_mb"]).replace(",", "."))
            if value <= 0:
                raise ValueError(value)
            dst["budget_mb"] = value
        except (TypeError, ValueError):
            rep.add("WARN", cfg_name, "плохой budget_mb",
                    f"contour.budget_mb: {section['budget_mb']!r} — не положительное "
                    "число, бюджет не проверяю")

    never = section.get("never_mirror")
    if isinstance(never, list):
        dst["never_mirror"] = [str(p).strip() for p in never if str(p).strip()]
    elif isinstance(never, str) and never.strip():
        dst["never_mirror"] = [never.strip()]


def contour_cfg(cfg: dict) -> dict:
    """Секция contour с подстановкой умолчаний: конфиг мог прийти из json-копии."""
    base = {
        "role": "source",
        "manifest": "MIRROR.md",
        "budget_mb": None,
        "sync_max_age_days": 3,
        "never_mirror": [],
    }
    section = cfg.get("contour")
    if isinstance(section, dict):
        for k, v in section.items():
            if k in base and v not in (None, ""):
                base[k] = v
            elif k in base and k == "never_mirror":
                base[k] = v if isinstance(v, list) else []
    if str(base["role"]).lower() not in CONTOUR_ROLES:
        base["role"] = "source"
    if not str(base["manifest"]).strip():
        base["manifest"] = "MIRROR.md"
    return base


def role_of(cfg: dict, rel_path: str) -> str:
    """Роль файла по префиксу пути. Самое длинное совпадение выигрывает."""
    best, best_len = "", -1
    for role, paths in cfg["roles"].items():
        for p in paths:
            p = str(p).strip("/")
            if not p:
                continue
            if rel_path == p or rel_path.startswith(p + "/"):
                if len(p) > best_len:
                    best, best_len = role, len(p)
    return best


def profile_of(cfg: dict, rel_path: str, fm, cli_profile: str):
    """Профиль файла и признак «назначен явно».

    Приоритет: поле profile во frontmatter -> правило по глобу из конфига ->
    флаг --profile -> вывод из полей самого файла -> профиль по умолчанию.
    Явным считается назначение, привязанное к конкретному файлу: по нему
    служебные файлы каркаса не получают поблажки.
    """
    if fm and str(fm.get("profile", "")).strip() in PROFILES:
        return str(fm["profile"]).strip(), True
    for rule in cfg.get("profiles", []):
        if path_matches(rule["path"], rel_path) and rule["profile"] in PROFILES:
            return rule["profile"], True
    if cli_profile:
        return cli_profile, False
    if fm:
        if is_true(fm.get("generated")):
            return "derived", True
        if fm.get("verified_against") or fm.get("verified_at"):
            return "mirror", True
    return cfg.get("profile", "authored"), False


# --- обход ------------------------------------------------------------------


def collect_files(ctx: Context, cli_profile: str) -> None:
    cfg = ctx.cfg
    excludes = [str(p) for p in cfg.get("exclude", [])]
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = [d for d in dirnames if d not in HARD_SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            abs_path = os.path.join(dirpath, name)
            rel_path = os.path.relpath(abs_path, ctx.root).replace(os.sep, "/")
            if any(path_matches(p, rel_path) for p in excludes):
                ctx.skipped += 1
                continue
            if not name.lower().endswith(".md"):
                continue
            text = read_text(abs_path)
            fm, body = parse_frontmatter(text)
            role = role_of(cfg, rel_path)
            profile, explicit = profile_of(cfg, rel_path, fm, cli_profile)
            # Файлы каркаса и индексы не производные и не зеркала «по умолчанию»:
            # такой профиль на них должен быть назначен явно.
            if profile != "authored" and not explicit and is_skeleton_name(cfg, rel_path):
                profile = "authored"
            kb = len(text.encode("utf-8")) / 1024
            ctx.files.append(
                FileInfo(rel_path, abs_path, role, profile, fm, body, text, kb,
                         count_lines(text))
            )
            ctx.profile_counts[profile] = ctx.profile_counts.get(profile, 0) + 1


def is_entry(ctx: Context, rel_path: str) -> bool:
    if "/" in rel_path:
        return False
    return rel_path in {str(v) for v in ctx.cfg["entry"].values()}


def is_skeleton_name(cfg: dict, rel_path: str) -> bool:
    """Файл каркаса в корне либо INDEX.md любой роли."""
    names = {str(v).lower() for v in cfg["entry"].values() if v}
    base = posixpath.basename(rel_path).lower()
    if "/" not in rel_path:
        return base in names
    return base == str(cfg["entry"].get("index", "INDEX.md")).lower()


# --- сбор целей из INDEX ----------------------------------------------------


def collect_index_targets(ctx: Context) -> None:
    index_name = str(ctx.cfg["entry"].get("index", "INDEX.md"))
    candidates = [index_name]
    for paths in ctx.cfg["roles"].values():
        for p in paths:
            candidates.append(posixpath.join(str(p).strip("/"), index_name))

    for rel_index in candidates:
        abs_index = os.path.join(ctx.root, rel_index.replace("/", os.sep))
        if not os.path.exists(abs_index):
            continue
        base = posixpath.dirname(rel_index)
        text = read_text(abs_index)
        raw_targets = list(RE_MD_LINK.findall(text))
        for chunk in RE_BACKTICK.findall(text):
            chunk = chunk.strip()
            if " " in chunk:
                continue
            if "/" in chunk or chunk.lower().endswith(".md") or has_glob(chunk):
                raw_targets.append(chunk)
        for target in raw_targets:
            for norm in normalize_targets(base, target):
                if has_glob(norm):
                    ctx.index_globs.append(norm)
                else:
                    ctx.index_paths.add(norm)


def normalize_targets(base: str, target: str):
    """Путь из INDEX -> варианты нормализованного пути от корня проекта."""
    t = target.split("#")[0].split("?")[0].strip().strip("<>").strip()
    t = t.replace("\\", "/")
    if not t or re.match(r"^[a-z][a-z0-9+.-]*:", t) or t.startswith("//"):
        return []
    t = t.lstrip("/")
    while t.startswith("./"):
        t = t[2:]
    if not t:
        return []
    out = {posixpath.normpath(t)}
    if base:
        out.add(posixpath.normpath(posixpath.join(base, t)))
    return {p for p in out if p and not p.startswith("..")}


def registered(ctx: Context, fi: FileInfo) -> bool:
    if fi.rel in ctx.index_paths:
        return True
    if fi.profile == "derived":
        # для производных достаточно, чтобы в INDEX был объявлен класс файлов
        return any(glob_re(g).match(fi.rel) for g in ctx.index_globs)
    return False


# --- проверки: каркас и проектный уровень -----------------------------------


def check_skeleton(ctx: Context) -> None:
    entry = ctx.cfg["entry"]
    for key, level in (("rules", "ERROR"), ("index", "ERROR"), ("status", "ERROR"),
                       ("changelog", "INFO")):
        name = str(entry.get(key, "")).strip()
        if not name:
            continue
        if not os.path.exists(os.path.join(ctx.root, name)):
            ctx.rep.add(level, name, "нет файла каркаса",
                        "обязательный файл каркаса отсутствует" if level == "ERROR"
                        else "файла нет — история изменений не ведётся")
    knowledge_dirs = [str(p) for p in ctx.cfg["roles"].get("knowledge", [])]
    if knowledge_dirs and not any(
        os.path.isdir(os.path.join(ctx.root, p.replace("/", os.sep))) for p in knowledge_dirs
    ):
        ctx.rep.add("WARN", knowledge_dirs[0] + "/", "нет папки знаний",
                    "нет папки знаний — где источник правды?")


def check_entry_limits(ctx: Context) -> None:
    entry, limits = ctx.cfg["entry"], ctx.cfg["limits"]
    pairs = [
        (str(entry.get("rules", "")), limits.get("rules_kb")),
        (str(entry.get("index", "")), limits.get("index_kb")),
        (str(entry.get("status", "")), limits.get("status_kb")),
    ]
    index_name = str(entry.get("index", "INDEX.md"))
    for paths in ctx.cfg["roles"].values():
        for p in paths:
            role_index = posixpath.join(str(p).strip("/"), index_name)
            pairs.append((role_index, limits.get("index_kb")))

    seen = set()
    for rel_path, limit in pairs:
        if not rel_path or not limit or rel_path in seen:
            continue
        seen.add(rel_path)
        abs_path = os.path.join(ctx.root, rel_path.replace("/", os.sep))
        if not os.path.exists(abs_path):
            continue
        text = read_text(abs_path)
        kb = len(text.encode("utf-8")) / 1024
        n = count_lines(text)
        if kb > float(limit):
            ctx.rep.add(
                "WARN", rel_path, "превышен лимит размера",
                f"{kb:.1f} КБ при лимите {limit} КБ "
                f"({n} {plural(n, 'строка', 'строки', 'строк')}) — пора вытеснять содержимое",
            )


def check_inbox(ctx: Context) -> None:
    for p in ctx.cfg["roles"].get("inbox", []):
        inbox = os.path.join(ctx.root, str(p).replace("/", os.sep))
        if not os.path.isdir(inbox):
            continue
        junk = [f for f in os.listdir(inbox) if f not in (".gitkeep", ".DS_Store")]
        if junk:
            ctx.rep.add("WARN", str(p) + "/", "инбокс не пуст",
                        f"не пуст ({len(junk)} шт.) — разобрать и очистить: {', '.join(junk[:5])}")


def check_competing_next(ctx: Context) -> None:
    """В STATUS не должно быть двух списков «что дальше»."""
    status_name = str(ctx.cfg["entry"].get("status", "STATUS.md"))
    abs_path = os.path.join(ctx.root, status_name.replace("/", os.sep))
    if not os.path.exists(abs_path):
        return
    text = RE_FENCED.sub("", read_text(abs_path))
    hits = []
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip().lstrip("#").strip().strip("*_").strip()
        if not s:
            continue
        if RE_NEXT_HEADING.match(s):
            hits.append((i, s[:40]))
    if len(hits) > 1:
        where = ", ".join(f"строка {i} («{t}»)" for i, t in hits[:4])
        ctx.rep.add("WARN", status_name, "два списка «что дальше»",
                    f"в STATUS больше одного списка «что дальше» ({where}); "
                    "сессия выберет произвольно")


def check_unknown_section(ctx: Context) -> None:
    """В файле «где мы» должен быть раздел про то, чего мы не знаем."""
    status_name = str(ctx.cfg["entry"].get("status", "STATUS.md")).strip()
    if not status_name:
        return
    abs_path = os.path.join(ctx.root, status_name.replace("/", os.sep))
    if not os.path.exists(abs_path):
        return  # отсутствие самого STATUS ловит check_skeleton
    _fm, body = parse_frontmatter(read_text(abs_path))
    if any(RE_UNKNOWN_HEADING.match(h) for h in headings(body)):
        ctx.claims_facts["unknown_section"] = True
        return
    ctx.claims_facts["unknown_section"] = False
    ctx.rep.add(
        "INFO", status_name, "нет раздела UNKNOWN",
        "в STATUS нет раздела UNKNOWN — незаписанное незнание опаснее плохо "
        "помеченного знания: на месте пустоты сессия сочинит правдоподобное",
    )


def check_corrections(ctx: Context) -> None:
    """Обратный канал: чем сессия сообщает, что нашла ошибку в базе.

    Без такого канала у сессии, обнаружившей ошибку, нет дешёвого действия,
    и побеждает «продолжить задачу» — ошибка остаётся в базе навсегда.
    """
    name = str(ctx.cfg["entry"].get("corrections", "CORRECTIONS.md")).strip()
    if not name:
        return
    abs_path = os.path.join(ctx.root, name.replace("/", os.sep))
    if not os.path.exists(abs_path):
        ctx.claims_facts["corrections"] = False
        ctx.rep.add(
            "INFO", name, "нет CORRECTIONS",
            f"нет {name} — у сессии, обнаружившей ошибку в базе, нет дешёвого "
            "способа о ней сообщить, и побеждает «продолжить задачу»",
        )
        return
    ctx.claims_facts["corrections"] = True

    try:
        text = read_text(abs_path)
    except OSError as exc:
        ctx.rep.add("WARN", name, "CORRECTIONS не читается",
                    f"{name} не читается ({exc}) — обратного канала фактически нет")
        return
    _fm, body = parse_frontmatter(text)
    body = RE_FENCED.sub("", body)

    dates, open_entries = [], 0
    for line in body.splitlines():
        s = line.strip()
        m = RE_CORRECTION_ENTRY.match(s)
        if not m:
            continue
        d = as_date(m.group(1))
        if d is None:
            continue
        dates.append(d)
        if not RE_CORRECTION_CLOSED.search(s):
            open_entries += 1

    ctx.claims_facts["corrections_entries"] = len(dates)
    ctx.claims_facts["corrections_open"] = open_entries

    if dates and body.strip():
        age = (ctx.today - max(dates)).days
        if age > CORRECTIONS_STALE_DAYS:
            ctx.rep.add(
                "INFO", name, "обратный канал молчит",
                f"последняя запись {age} дн. назад — либо база безупречна, либо "
                "канал не используется",
            )

    if open_entries:
        ctx.rep.add(
            "INFO", name, "незакрытые записи в CORRECTIONS",
            f"{open_entries} "
            f"{plural(open_entries, 'незакрытая запись', 'незакрытые записи', 'незакрытых записей')} "
            f"в CORRECTIONS — {plural(open_entries, 'дренируется', 'дренируются', 'дренируются')} "
            "на аудите",
        )


def check_duplicate_entries(ctx: Context) -> None:
    """Два CHANGELOG или два корневых INDEX всегда расходятся."""
    entry = ctx.cfg["entry"]
    changelog = str(entry.get("changelog", "CHANGELOG.md"))
    index_name = str(entry.get("index", "INDEX.md"))

    chlogs = [
        fi.rel for fi in ctx.files
        if posixpath.basename(fi.rel).lower() == changelog.lower() and fi.role != "archive"
    ]
    if len(chlogs) > 1:
        ctx.rep.add("WARN", chlogs[0], "два CHANGELOG",
                    f"файлов {changelog}: {len(chlogs)} ({', '.join(sorted(chlogs))}) — "
                    "два таких файла всегда расходятся; пометьте один superseded")

    indexes = [
        fi.rel for fi in ctx.files
        if posixpath.basename(fi.rel).lower() == index_name.lower()
        and not fi.role and fi.role != "archive"
    ]
    if len(indexes) > 1:
        ctx.rep.add("WARN", indexes[0], "два INDEX",
                    f"индексных файлов вне ролей: {len(indexes)} ({', '.join(sorted(indexes))}) — "
                    "два таких файла всегда расходятся; пометьте один superseded")


def check_links(ctx: Context) -> None:
    for fi in ctx.files:
        if fi.role == "archive":
            continue
        text = RE_INLINE_CODE.sub("", RE_FENCED.sub("", fi.text))
        base = os.path.dirname(fi.abs)
        for target in RE_MD_LINK.findall(text):
            t = target.split("#")[0].split("?")[0].strip().strip("<>")
            if not t or re.match(r"^[a-z][a-z0-9+.-]*:", t) or t.startswith("//"):
                continue
            if has_glob(t):
                continue  # это объявление класса файлов, а не ссылка
            resolved = os.path.normpath(os.path.join(base, t.replace("/", os.sep)))
            if not os.path.exists(resolved):
                ctx.rep.add("ERROR", fi.rel, "битая ссылка", f"битая ссылка: {target}")


def check_index_registration(ctx: Context) -> None:
    index_name = str(ctx.cfg["entry"].get("index", "INDEX.md")).lower()
    orphans_outside_roles = 0
    for fi in ctx.files:
        if is_entry(ctx, fi.rel):
            continue
        if posixpath.basename(fi.rel).lower() == index_name:
            continue
        if fi.role in OPAQUE_ROLES:
            continue
        must = fi.role in INDEXED_ROLES or fi.profile in ("derived", "mirror")
        if registered(ctx, fi):
            continue
        if must:
            hint = (" (для производных достаточно строки с глобом, "
                    "например `people/*/HEALTH_*.md`)") if fi.profile == "derived" else ""
            ctx.rep.add("WARN", fi.rel, "не зарегистрирован в INDEX",
                        f"не зарегистрирован в INDEX — такой файл никто не найдёт{hint}")
        elif not fi.role:
            orphans_outside_roles += 1
    if orphans_outside_roles:
        ctx.rep.add(
            "INFO", ".", "файлы вне ролей",
            f"{orphans_outside_roles} md-{plural(orphans_outside_roles, 'файл', 'файла', 'файлов')} "
            f"вне ролей и вне INDEX — если это знание, объявите роль в {CONFIG_NAME}",
        )


def check_superseded_targets(ctx: Context) -> None:
    for fi in ctx.files:
        if not fi.fm:
            continue
        target = fi.fm.get("superseded_by")
        if not target:
            continue
        target = str(target).strip()
        if target in ctx.ids:
            continue
        candidate = os.path.join(ctx.root, target.replace("/", os.sep))
        sibling = os.path.join(os.path.dirname(fi.abs), target.replace("/", os.sep))
        if os.path.exists(candidate) or os.path.exists(sibling):
            continue
        ctx.rep.add("ERROR", fi.rel, "superseded_by в никуда",
                    f"superseded_by '{target}' указывает в никуда")


# --- проверки: контуры ------------------------------------------------------
#
# Один репозиторий не отказывает молча. Молча отказывает ПАРА контуров:
# источник на машине владельца и зеркало, по которому отвечает сессия.
# Всё, что ниже, проверяет не содержимое базы, а её отношение ко второму
# контуру: знает ли зеркало, что оно зеркало, откуда и когда снято, чего
# в нём нет, и не ушёл ли источник вперёд.


def walk_all_files(ctx: Context):
    """Все файлы репозитория (любых расширений) как (rel, abs, размер, исключён).

    В отличие от collect_files смотрит не только .md: бюджет яруса и запрет
    оперативных представлений считаются по физическому содержимому папки.
    """
    if ctx.all_files is not None:
        return ctx.all_files
    excludes = [str(p) for p in ctx.cfg.get("exclude", [])]
    out = []
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = [d for d in dirnames if d not in HARD_SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, ctx.root).replace(os.sep, "/")
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                continue
            excluded = any(path_matches(p, rel) for p in excludes)
            out.append((rel, abs_path, size, excluded))
    ctx.all_files = out
    return out


def check_contour(ctx: Context) -> None:
    """Проверки роли контура: зеркало обязано объявлять себя зеркалом."""
    cc = contour_cfg(ctx.cfg)
    role = str(cc["role"])
    manifest = str(cc["manifest"])
    ctx.contour_facts["role"] = role
    ctx.contour_facts["manifest"] = manifest
    abs_manifest = os.path.join(ctx.root, manifest.replace("/", os.sep))

    if role == "source":
        ctx.contour_bits.append("source")
        if os.path.exists(abs_manifest):
            ctx.contour_facts["manifest_in_source"] = True
            ctx.contour_bits.append(f"в корне лежит {manifest}")
            ctx.rep.add(
                "INFO", manifest, "манифест зеркала в источнике",
                f"манифест зеркала лежит в источнике; убедись, что роль контура "
                f"задана верно (contour.role: {role})",
            )
        return

    ctx.contour_bits.append("mirror")
    check_mirror_manifest(ctx, cc, manifest, abs_manifest)
    check_never_mirror(ctx, cc)
    check_tier_budget(ctx, cc)


def check_mirror_manifest(ctx: Context, cc: dict, manifest: str, abs_manifest: str) -> None:
    rep = ctx.rep
    if not os.path.exists(abs_manifest):
        ctx.contour_facts["manifest_present"] = False
        ctx.contour_bits.append("манифеста нет")
        rep.add("ERROR", manifest, "нет манифеста зеркала",
                "зеркало без манифеста: сессия не отличит «данных нет» от "
                "«данные в источнике»")
        return
    ctx.contour_facts["manifest_present"] = True

    try:
        text = read_text(abs_manifest)
    except OSError as exc:
        rep.add("ERROR", manifest, "манифест не читается",
                f"манифест зеркала не читается ({exc}) — считай, что его нет")
        return
    fm, body = parse_frontmatter(text)
    fm = fm or {}

    synced_from = str(fm.get("synced_from", "")).strip()
    if not synced_from:
        rep.add("ERROR", manifest, "нет synced_from",
                "в манифесте нет synced_from — неизвестно, с какого коммита источника "
                "снято зеркало; расхождение станет невидимым")
    else:
        ctx.contour_facts["synced_from"] = synced_from

    raw = str(fm.get("synced_at", "")).strip()
    if not raw:
        rep.add("ERROR", manifest, "нет synced_at",
                "в манифесте нет synced_at — неизвестно, когда зеркало снимали; "
                "расхождение станет невидимым")
    else:
        check_sync_age(ctx, cc, manifest, raw)

    if not any(RE_ABSENT_HEADING.match(h) for h in headings(body)):
        ctx.contour_facts["absent_section"] = False
        rep.add("ERROR", manifest, "нет раздела об отсутствующем",
                "в манифесте нет списка того, чего в зеркале нет — отсутствие файла "
                "будет прочитано как «данных нет»")
    else:
        ctx.contour_facts["absent_section"] = True


def check_sync_age(ctx: Context, cc: dict, manifest: str, raw: str) -> None:
    rep = ctx.rep
    limit = int(cc["sync_max_age_days"])
    d = as_iso_date(raw)
    if d is None:
        rep.add("ERROR", manifest, "плохая дата synced_at",
                f"synced_at '{raw}' не ISO-дата (YYYY-MM-DD) — возраст отметки "
                "синхронизации нечем измерить")
        return
    age = (ctx.today - d).days
    ctx.contour_facts["synced_at"] = str(d)
    ctx.contour_facts["sync_age_days"] = age
    ctx.contour_bits.append(
        f"отметка {d} (в будущем)" if age < 0
        else f"отметка {d} ({age} {plural(age, 'день', 'дня', 'дней')})"
    )
    if age < 0:
        rep.add("WARN", manifest, "synced_at в будущем",
                f"synced_at '{raw}' в будущем — отметке синхронизации нельзя верить")
        return
    if age > limit * 4:
        rep.add(
            "ERROR", manifest, "отметка синхронизации протухла",
            f"отметка синхронизации от {d}, {age} дн. назад — это больше {limit * 4} дн. "
            f"(4× порога {limit}); зеркало почти наверняка разошлось с источником, "
            "отвечать по нему без сверки нельзя",
        )
    elif age > limit:
        rep.add(
            "WARN", manifest, "старая отметка синхронизации",
            f"отметка синхронизации от {d}, {age} дн. назад — при таком возрасте "
            "расхождение вероятно; сверься с источником, прежде чем отвечать "
            "по этой базе",
        )


def check_never_mirror(ctx: Context, cc: dict) -> None:
    """Оперативные представления в зеркале врут не «иногда», а всегда."""
    patterns = [str(p) for p in cc.get("never_mirror", []) if str(p).strip()]
    if not patterns:
        return
    hits = []
    for rel, _abs, _size, _excluded in walk_all_files(ctx):
        if any(path_matches(p, rel) for p in patterns):
            hits.append(rel)
    ctx.contour_facts["never_mirror_hits"] = hits
    if hits:
        ctx.contour_bits.append(
            f"оперативных представлений: {len(hits)}"
        )
    for rel in hits:
        ctx.rep.add(
            "WARN", rel, "оперативное представление в зеркале",
            "оперативное представление в зеркале протухает за дни и гарантированно "
            "врёт; такие файлы не копируются, а не «обновляются»",
        )


def check_tier_budget(ctx: Context, cc: dict) -> None:
    """Бюджет объёма яруса 1: лёгкий контур должен оставаться лёгким."""
    budget = cc.get("budget_mb")
    if not budget:
        return
    budget = float(budget)
    total = sum(size for _rel, _abs, size, excluded in walk_all_files(ctx) if not excluded)
    mb = total / (1024 * 1024)
    ctx.contour_facts["tier_mb"] = round(mb, 3)
    ctx.contour_facts["budget_mb"] = budget
    ctx.contour_bits.append(f"ярус 1 {mb:.2f} из {budget:g} МБ")
    if mb > budget:
        ctx.rep.add(
            "WARN", ".", "превышен бюджет яруса",
            f"ярус 1 весит {mb:.2f} МБ при бюджете {budget:g} МБ — лёгкий контур "
            "перестал быть лёгким: часть файлов не доедет до сессии, а какие "
            "именно — никто не заметит",
        )
    elif mb > budget * 0.9:
        ctx.rep.add(
            "INFO", ".", "бюджет яруса на исходе",
            f"ярус 1 весит {mb:.2f} МБ — {mb / budget * 100:.0f}% бюджета "
            f"{budget:g} МБ; запас кончается, решай что не зеркалить, пока есть выбор",
        )


def check_revocation_registry(ctx: Context) -> None:
    """Одного `status: superseded` мало: старая формулировка живёт в других файлах."""
    superseded = [
        fi.rel for fi in ctx.files
        if fi.fm and str(fi.fm.get("status", "")).strip() == "superseded"
    ]
    if not superseded:
        return
    for fi in ctx.files:
        if any(RE_REVOKED_HEADING.match(h) for h in headings(fi.body)):
            ctx.contour_facts["revocation_registry"] = fi.rel
            return
    n = len(superseded)
    ctx.contour_facts["revocation_registry"] = None
    ctx.rep.add(
        "INFO", ".", "нет реестра отмен",
        f"есть вытесненные файлы ({n}), но нет реестра отмен: старые формулировки "
        "могут лежать в других файлах и читаться как конкурирующий источник",
    )


def check_unpushed_commits(ctx: Context) -> None:
    """Незамкнутый цикл: коммит есть, а второй контур о нём не знает."""
    if not os.path.isdir(os.path.join(ctx.root, ".git")):
        return
    import subprocess  # лениво: без .git модуль не нужен

    try:
        proc = subprocess.run(
            ["git", "-C", ctx.root, "rev-list", "--count", "@{u}..HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return  # git недоступен, репозиторий странный — это не повод падать
    if proc.returncode != 0:
        return  # апстрима нет: сравнивать не с чем, и это нормально
    try:
        n = int(proc.stdout.strip())
    except (TypeError, ValueError):
        return
    ctx.contour_facts["unpushed"] = n
    if n > 0:
        ctx.contour_bits.append(f"не отправлено {n}")
        ctx.rep.add(
            "WARN", ".", "неотправленные коммиты",
            f"{n} {plural(n, 'коммит', 'коммита', 'коммитов')} не отправлено — "
            "второй контур работает по старой картине и не знает об этом",
        )


# --- проверки: пофайловые ---------------------------------------------------


def check_relative_dates(ctx: Context, fi: FileInfo) -> None:
    body = RE_FENCED.sub("", fi.body)
    hits = RE_RELATIVE_DATE.findall(body)
    if not hits:
        return
    first = None
    for i, line in enumerate(body.splitlines(), start=1):
        m = RE_RELATIVE_DATE.search(line)
        if m:
            first = (i, m.group(0))
            break
    n = len(hits)
    where = f"первая — «{first[1]}», строка {first[0]}" if first else ""
    ctx.rep.add("INFO", fi.rel, "относительные даты",
                f"относительных дат: {n} ({where}) — заменить на абсолютные")


def check_common_frontmatter(ctx: Context, fi: FileInfo) -> None:
    """Проверки, общие для всех профилей. Вызываются только если frontmatter есть."""
    fm, r, rep = fi.fm, fi.rel, ctx.rep

    sens = str(fm.get("sensitivity", "")).strip().lower()
    if sens:
        if sens == "secret":
            rep.add("ERROR", r, "secret в репозитории",
                    "файлы уровня secret не хранятся в репозитории")
        elif sens not in VALID_SENSITIVITY:
            rep.add("WARN", r, "плохой sensitivity",
                    f"sensitivity '{sens}' не из списка: {', '.join(sorted(VALID_SENSITIVITY))}")

    t = str(fm.get("type", "")).strip()
    if t and t not in VALID_TYPE:
        rep.add("ERROR", r, "плохой type", f"type '{t}' не из списка: {', '.join(sorted(VALID_TYPE))}")

    st = str(fm.get("status", "")).strip()
    if st and st not in VALID_STATUS:
        rep.add("ERROR", r, "плохой status",
                f"status '{st}' не из списка: {', '.join(sorted(VALID_STATUS))}")

    conf = str(fm.get("confidence", "")).strip()
    if conf and conf not in VALID_CONFIDENCE:
        rep.add("ERROR", r, "плохой confidence",
                f"confidence '{conf}' не из списка: {', '.join(sorted(VALID_CONFIDENCE))}")

    # У attempt замены может не быть вовсе: попытку не «заменяют», её бросают,
    # и требовать superseded_by — значит толкать автора выдумать преемника.
    if st == "superseded" and not fm.get("superseded_by") and t != "attempt":
        rep.add("ERROR", r, "superseded без замены", "status: superseded, но нет superseded_by")
    if fm.get("superseded_by") and st and st != "superseded":
        rep.add("WARN", r, "superseded_by при другом статусе",
                "есть superseded_by, но status не superseded")

    fid = str(fm.get("id", "")).strip()
    if fid:
        ok = RE_ID.match(fid) if fi.role == "knowledge" else (RE_DECISION_ID.match(fid) or RE_ID.match(fid))
        if not ok:
            rep.add("WARN", r, "плохой id", f"id '{fid}' не по формату")
        elif fid in ctx.ids:
            rep.add("ERROR", r, "дубль id", f"id '{fid}' уже занят файлом {ctx.ids[fid]}")
        else:
            ctx.ids[fid] = r


def check_review_deadline(ctx: Context, fi: FileInfo) -> bool:
    """Авторский срок годности. Возвращает True, если он задан (тогда возраст не меряем).

    Истечение — ERROR, а не WARN. Просто старый файл может быть старым и верным:
    возраст — свойство записи. Истёкший заявленный срок — свойство утверждения:
    автор сам сказал, до какого числа за это отвечает, и это число прошло.
    """
    fm = fi.fm or {}
    declared = False
    for key in ("review_by", "valid_until"):
        raw = str(fm.get(key, "")).strip()
        if not raw:
            continue
        d = as_date(raw)
        if d is None:
            ctx.rep.add("ERROR", fi.rel, "плохая дата пересмотра",
                        f"{key} '{raw}' не в формате YYYY-MM-DD")
            continue
        declared = True
        overdue = (ctx.today - d).days
        if overdue > 0:
            ctx.claim("expired")
            ctx.rep.add(
                "ERROR", fi.rel, "срок годности истёк",
                f"срок годности истёк {overdue} дн. назад ({key}: {raw}) — файл "
                "утверждает про настоящее, но за это настоящее уже никто не отвечает",
            )
    return declared


def check_claims(ctx: Context, fi: FileInfo) -> None:
    """Файл-утверждение против файла-записи: снапшоты и попытки.

    `updated` отвечает на вопрос «когда автор это трогал». Читателю нужен другой
    ответ — «до какого числа автор за это отвечает». Спека алгоритма без срока
    годности нормальна; снапшот состояния без срока годности дефектен по
    построению, потому что утверждает про настоящее, которое уже кончилось.
    """
    fm = fi.fm
    if not fm:
        return
    rep, r = ctx.rep, fi.rel
    t = str(fm.get("type", "")).strip().lower()
    st = str(fm.get("status", "")).strip().lower()

    if t == "snapshot" and not str(fm.get("valid_until", "")).strip():
        ctx.claim("snapshot_no_valid_until")
        rep.add(
            "ERROR", r, "snapshot без valid_until",
            "snapshot без valid_until: файл утверждает про настоящее, но не "
            "говорит, до какого числа это утверждение действует",
        )

    if t == "attempt" and not str(fm.get("stopped_at", "")).strip():
        ctx.claim("attempt_no_stopped_at")
        rep.add(
            "ERROR", r, "attempt без stopped_at",
            "attempt без stopped_at: незаписанная причина остановки гарантирует, "
            "что попытку предложат снова",
        )

    if st == "abandoned" and t != "attempt":
        ctx.claim("abandoned_not_attempt")
        rep.add(
            "WARN", r, "abandoned не attempt",
            f"status: abandoned при type: {t or '<не указан>'} — брошенное живёт в "
            "слое attempt; иначе оно читается как действующее знание",
        )


def check_authored(ctx: Context, fi: FileInfo, stale_days: int) -> None:
    rep, r, fm = ctx.rep, fi.rel, fi.fm
    index_name = str(ctx.cfg["entry"].get("index", "INDEX.md")).lower()
    needs_fm = (
        fi.role in FRONTMATTER_ROLES
        and posixpath.basename(r).lower() != index_name
    )
    if not needs_fm:
        if fm:
            check_common_frontmatter(ctx, fi)
            check_review_deadline(ctx, fi)
        return

    if fm is None:
        rep.add("ERROR", r, "нет frontmatter", "нет frontmatter")
        return

    for key in AUTHORED_REQUIRED:
        if key not in fm or not str(fm[key]).strip():
            rep.add("ERROR", r, "нет обязательного поля",
                    f"нет обязательного поля frontmatter: {key}")

    check_common_frontmatter(ctx, fi)
    has_deadline = check_review_deadline(ctx, fi)

    upd_raw = str(fm.get("updated", "")).strip()
    if upd_raw:
        d = as_date(upd_raw)
        if d is None:
            rep.add("ERROR", r, "плохая дата updated", f"updated '{upd_raw}' не в формате YYYY-MM-DD")
        else:
            age = (ctx.today - d).days
            if age < 0:
                rep.add("WARN", r, "дата в будущем", "updated в будущем")
            elif not has_deadline and age > stale_days and str(fm.get("status", "")) == "active":
                rep.add("WARN", r, "протухло по возрасту",
                        f"status: active, но не обновлялся {age} дн. — актуален ли?")


def check_derived(ctx: Context, fi: FileInfo) -> None:
    """Файл генерируется кодом: правки руками бессмысленны, возраст не важен."""
    rep, r, fm = ctx.rep, fi.rel, fi.fm
    if fm is None:
        rep.add("ERROR", r, "производный без объявления",
                "производный файл без frontmatter: нужны generated: true и generated_from")
        return
    if not is_true(fm.get("generated")):
        rep.add("ERROR", r, "производный без generated",
                "нет generated: true — производный файл должен объявлять, что он производный")
        rep.add("WARN", r, "ручная правка производного",
                "похоже, файл правили руками; правка производного файла исчезнет "
                "при следующей генерации")
    if not str(fm.get("generated_from", "")).strip():
        rep.add("ERROR", r, "нет generated_from",
                "нет generated_from — неизвестно, что перегенерирует этот файл")
    # для производных валидируем только то, что не связано с ручным авторством
    sens = str(fm.get("sensitivity", "")).strip().lower()
    if sens == "secret":
        rep.add("ERROR", r, "secret в репозитории",
                "файлы уровня secret не хранятся в репозитории")
    check_review_deadline(ctx, fi)


def check_mirror(ctx: Context, fi: FileInfo, mirror_stale_days: int) -> None:
    """Конспект внешней живой системы: протухает от чужих действий, а не от наших."""
    rep, r, fm = ctx.rep, fi.rel, fi.fm
    if fm is None:
        rep.add("ERROR", r, "зеркало без объявления",
                "конспект внешней системы без frontmatter: нужны verified_against и verified_at")
        return
    check_common_frontmatter(ctx, fi)
    check_review_deadline(ctx, fi)

    system = str(fm.get("verified_against", "")).strip()
    if not system:
        rep.add("ERROR", r, "нет verified_against",
                "нет verified_against — неизвестно, с какой внешней системой сверялись")
    raw = str(fm.get("verified_at", "")).strip()
    if not raw:
        rep.add("ERROR", r, "нет verified_at",
                "нет verified_at — неизвестно, когда сверялись с внешней системой")
        return
    d = as_date(raw)
    if d is None:
        rep.add("ERROR", r, "плохая дата verified_at",
                f"verified_at '{raw}' не в формате YYYY-MM-DD")
        return
    age = (ctx.today - d).days
    if age < 0:
        rep.add("WARN", r, "дата в будущем", "verified_at в будущем")
        return
    if age > mirror_stale_days:
        rep.add("WARN", r, "зеркало не сверялось",
                f"сверялось {age} дн. назад с {system or '<система не указана>'} — "
                "внешняя система могла измениться без нашего участия")


def check_numbering(ctx: Context, fi: FileInfo) -> None:
    """Опциональный модуль: нумерация имён файлов."""
    name = posixpath.basename(fi.rel)
    index_name = str(ctx.cfg["entry"].get("index", "INDEX.md")).lower()
    if name.lower() == index_name:
        return
    if fi.role == "knowledge" and not RE_KNOWLEDGE_NAME.match(name):
        ctx.rep.add("WARN", fi.rel, "имя не по шаблону", "имя не по шаблону NN.NN-slug.md")
    if fi.role == "decisions" and not RE_DECISION_NAME.match(name):
        ctx.rep.add("WARN", fi.rel, "имя не по шаблону", "имя не по шаблону NNNN-slug.md")


def check_size(ctx: Context, fi: FileInfo) -> None:
    if fi.profile == "derived":
        return  # производный файл такой, каким его сделал код
    if fi.role != "knowledge":
        return
    limit = ctx.cfg["limits"].get("knowledge_kb")
    if not limit:
        return
    if fi.kb > float(limit):
        ctx.rep.add(
            "WARN", fi.rel, "превышен лимит размера",
            f"{fi.kb:.1f} КБ при лимите {limit} КБ "
            f"({fi.lines} {plural(fi.lines, 'строка', 'строки', 'строк')}) — "
            "вероятно, слиплись две темы, стоит разделить",
        )


def check_file(ctx: Context, fi: FileInfo, stale_days: int, mirror_stale_days: int) -> None:
    if fi.role in OPAQUE_ROLES:
        return  # чужое, сырое и отложенное по существу не проверяем
    check_relative_dates(ctx, fi)
    if fi.profile == "derived":
        check_derived(ctx, fi)
    elif fi.profile == "mirror":
        check_mirror(ctx, fi, mirror_stale_days)
    else:
        check_authored(ctx, fi, stale_days)
    check_claims(ctx, fi)
    check_size(ctx, fi)
    if "numbering" in [str(m) for m in ctx.cfg.get("modules", [])]:
        check_numbering(ctx, fi)


# --- вывод ------------------------------------------------------------------


def summary_line(ctx: Context) -> str:
    rep = ctx.rep
    head = (
        f"Итого: {rep.count('ERROR')} ERROR, {rep.count('WARN')} WARN, "
        f"{rep.count('INFO')} INFO"
    )
    contour = " · контур: " + ", ".join(ctx.contour_bits) if ctx.contour_bits else ""
    if ctx.contour_only:
        return head + (contour or " · контур: не задан") + " · режим: только контур"
    claims = claims_segment(ctx)
    if ctx.claims_only:
        return head + claims + " · режим: только заявления"
    profiles = ", ".join(
        f"{p}={ctx.profile_counts[p]}" for p in PROFILES if ctx.profile_counts.get(p)
    ) or "нет файлов"
    return (
        head
        + f" · профилей: {profiles}"
        + f" · пропущено по exclude: {ctx.skipped}"
        + claims
        + contour
    )


def claims_segment(ctx: Context) -> str:
    """Хвост сводки про заявления: что в базе заявленно протухло и чем это подпёрто."""
    f = ctx.claims_facts
    out = f" · заявленно протухло: {f.get('expired', 0)}"
    without = f.get("snapshot_no_valid_until", 0) + f.get("attempt_no_stopped_at", 0)
    if without:
        out += f" · заявлений без опоры: {without}"
    if f.get("corrections_open"):
        out += f" · незакрытых правок: {f['corrections_open']}"
    return out


def top_kinds(ctx: Context, n: int = 5):
    counts: dict = {}
    for f in ctx.rep.findings:
        counts[(f.level, f.kind)] = counts.get((f.level, f.kind), 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0][1]))[:n]


def print_report(ctx: Context, quiet: bool, summary_only: bool) -> None:
    if not summary_only:
        for level in LEVELS:
            if quiet and level != "ERROR":
                continue
            group = sorted(
                (f for f in ctx.rep.findings if f.level == level), key=lambda x: (x.path, x.kind)
            )
            if not group:
                continue
            print(f"\n=== {level} ({len(group)}) ===")
            for f in group:
                print(f"  {f}")
        print()
    print(summary_line(ctx))
    if summary_only:
        top = top_kinds(ctx)
        if top:
            print("Чаще всего:")
            for (level, kind), cnt in top:
                print(f"  {cnt:4}  {level:5} {kind}")


# --- main -------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Линтер базы знаний kb-architect (v2.2)")
    ap.add_argument("root", help="путь к проекту")
    ap.add_argument("--config", default="", help=f"путь к {CONFIG_NAME}")
    ap.add_argument("--profile", default="", choices=("", *PROFILES),
                    help="профиль по умолчанию (правила по глобам всё равно применяются)")
    ap.add_argument("--stale-days", type=int, default=None,
                    help="порог протухания для authored (перекрывает конфиг)")
    ap.add_argument("--quiet", action="store_true", help="только ERROR")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--summary", action="store_true", help="только сводка и топ-5 сообщений")
    # Быстрые режимы взаимоисключающие: «прогнать оба» — это обычный прогон.
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--contour-only", action="store_true", dest="contour_only",
                       help="только проверки контура (манифест зеркала, бюджет, "
                            "неотправленные коммиты) — быстрый предполётный чек")
    modes.add_argument("--claims-only", action="store_true", dest="claims_only",
                       help="только проверки заявлений (сроки годности, snapshot, "
                            "attempt) — быстрый чек «что в базе заявленно протухло»")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}", file=sys.stderr)
        return 2

    rep = Report()
    try:
        cfg = load_config(root, os.path.abspath(args.config) if args.config else "", rep)
    except FileNotFoundError as exc:
        print(f"нет такого конфига: {exc}", file=sys.stderr)
        return 2

    stale_days = args.stale_days if args.stale_days is not None else int(cfg.get("stale_days", 90))
    try:
        mirror_stale_days = int(cfg.get("mirror_stale_days", 30))
    except (TypeError, ValueError):
        mirror_stale_days = 30

    ctx = Context(root=root, cfg=cfg, rep=rep, today=dt.date.today(),
                  contour_only=args.contour_only, claims_only=args.claims_only)

    if args.contour_only:
        # Предполётный чек: только отношение ко второму контуру, без обхода базы.
        check_contour(ctx)
        check_unpushed_commits(ctx)
        emit(ctx, args)
        return 1 if rep.count("ERROR") else 0

    if args.claims_only:
        # Быстрый чек заявлений: что в базе объявлено про настоящее и уже протухло.
        collect_files(ctx, args.profile)
        for fi in ctx.files:
            if fi.role in OPAQUE_ROLES or not fi.fm:
                continue
            check_review_deadline(ctx, fi)
            check_claims(ctx, fi)
        emit(ctx, args)
        return 1 if rep.count("ERROR") else 0

    collect_files(ctx, args.profile)
    collect_index_targets(ctx)

    check_skeleton(ctx)
    check_entry_limits(ctx)
    check_inbox(ctx)
    check_competing_next(ctx)
    check_unknown_section(ctx)
    check_corrections(ctx)
    check_duplicate_entries(ctx)
    for fi in ctx.files:
        check_file(ctx, fi, stale_days, mirror_stale_days)
    check_links(ctx)
    check_index_registration(ctx)
    check_superseded_targets(ctx)
    check_contour(ctx)
    check_revocation_registry(ctx)
    check_unpushed_commits(ctx)

    emit(ctx, args)
    return 1 if rep.count("ERROR") else 0


def emit(ctx: Context, args) -> None:
    if args.as_json:
        payload = {
            "findings": [f.__dict__ for f in ctx.rep.findings],
            "summary": {
                "error": ctx.rep.count("ERROR"),
                "warn": ctx.rep.count("WARN"),
                "info": ctx.rep.count("INFO"),
                "profiles": ctx.profile_counts,
                "excluded": ctx.skipped,
                "contour": ctx.contour_facts,
                "claims": ctx.claims_facts,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_report(ctx, args.quiet, args.summary)


if __name__ == "__main__":
    sys.exit(main())
