#!/usr/bin/env python3
"""
kb_entry.py — полный вход в проект одной командой.

    python3 kb_entry.py <корень проекта> [--role <id>]... [--out <файл>]

Вход описан в правилах проекта, в current, в реестре ролей и в индексе
знаний — в четырёх местах и без одного исполнимого списка. Сессия, получившая
при передаче работы сокращённый пересказ входа, читала начала файлов (head -60)
и пропускала инварианты и маршрут своей роли; правило владельца не применилось,
а «проверка PASS» выглядела как «вход сделан» (продукт на Odoo, 18.09 и
29.09.2026 — третий случай за месяц).

Скрипт собирает вход из данных проекта в один файл: правила, current,
объявленные обязательные файлы («обязательно при входе: a, b»), маршруты с
поводом «всегда / при входе / перед любой записью», SKILL.md каждой выбранной
роли и маршруты, названные через --route. Остальные маршруты роли — адреса по
поводу, не чтение на входе (у роли разработчика их 37 файлов, 962 КБ): они
печатаются списком с поводами. Файл читается целиком; head, limit и выборочные
строки входом не считаются. Без --role печатает роли проекта с их триггерами:
выбор роли — решение сессии по задаче, не скрипта.

Скрипт ничего не пишет в проект: файл входа ложится в git-каталог (не
отслеживается) либо во временный каталог.
"""

import argparse
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
import kb_index
import kb_paths

MANDATORY_KEYS = ("обязательно при входе", "entry reads", "mandatory entry")
FILE_CAP = 400_000     # больше — адрес, не чтение на входе
ALWAYS = re.compile(r"\b(?:always|всегда|any task start|task start|at entry|при входе|на входе|"
                    r"before any write|перед любой (?:правкой|записью))\b", re.IGNORECASE)


def git_dir(root):
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--absolute-git-dir"],
                           capture_output=True, text=True, timeout=10,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def route_units(route):
    """(путь, раздел или None) локальных целей маршрута; раздел — только он."""
    out = []
    for item in kb_index.targets(route):
        if not isinstance(item, dict) or item.get("kind") in ("project", "query"):
            continue
        if isinstance(item.get("path"), str):
            out.append((item["path"], item.get("section") if item.get("kind") == "section" else None))
    return out


def role_files(root, registry, index, wanted, chosen_routes):
    """[(rel, why)] для выбранных ролей, их прочие маршруты и ненайденное."""
    out, missing, optional = [], [], []
    roles = registry.get("roles", []) if isinstance(registry, dict) else []
    skills = {s.get("name"): s for s in registry.get("skills", [])
              if isinstance(s, dict)} if isinstance(registry, dict) else {}
    routes = {r.get("id"): r for r in (index or {}).get("routes", []) if isinstance(r, dict)}
    for want in wanted:
        role = next((r for r in roles if isinstance(r, dict)
                     and want in (r.get("id"), r.get("skill"))), None)
        if not role:
            missing.append(f"роль «{want}» не найдена в PROJECT_ROLES.json")
            continue
        skill = skills.get(role.get("skill"))
        canonical = skill.get("canonical") if skill else None
        if canonical and os.path.isfile(os.path.join(root, canonical, "SKILL.md")):
            out.append((f"{canonical.strip('/')}/SKILL.md", f"роль {role['id']}: метод", None))
        else:
            missing.append(f"роль {role['id']}: SKILL.md навыка «{role.get('skill')}» не найден")
        for route_id in role.get("knowledge_routes", []) or []:
            route = routes.get(route_id)
            if not route:
                missing.append(f"роль {role['id']}: маршрута «{route_id}» нет в индексе")
                continue
            when = "; ".join(route.get("load_when", []))
            if route_id in chosen_routes or ALWAYS.search(when):
                for rel, section in route_units(route):
                    out.append((rel, f"роль {role['id']}: маршрут {route_id}", section))
            else:
                optional.append((route_id, when))
    return out, missing, optional


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--route", action="append", default=[],
                        help="маршрут индекса, нужный задаче: читается целиком")
    parser.add_argument("--out")
    args = parser.parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2

    plan, missing = [], []
    for path in kb_paths.rules_files(root):
        plan.append((os.path.relpath(path, root), "правила проекта", None))
    entry = kb_paths.locate(root, "entry")
    if entry.path:
        plan.append((os.path.relpath(entry.path, root), "current", None))
    else:
        missing.append("current (NOW.md) не найден")
    raw, _ = kb_paths.declared_value(root, MANDATORY_KEYS)
    for item in re.split(r"[,;]", raw or ""):
        rel = item.strip().strip("`\"'«» ")
        if rel:
            plan.append((rel, "обязательно при входе (правила проекта)", None))

    registry = load_json(os.path.join(root, "PROJECT_ROLES.json"))
    index = load_json(os.path.join(root, kb_index.DEFAULT_INDEX))
    roles = [r for r in (registry or {}).get("roles", []) if isinstance(r, dict)]
    for route in (index or {}).get("routes", []):
        if isinstance(route, dict) and (route.get("id") in args.route or (
                route.get("id") != (index or {}).get("current")
                and ALWAYS.search("; ".join(route.get("load_when", []))))):
            for rel, section in route_units(route):
                plan.append((rel, f"маршрут {route['id']}"
                                  + ("" if route.get("id") in args.route else " (всегда)"), section))
    optional = []
    if args.role:
        extra, lost, optional = role_files(root, registry or {}, index, args.role, set(args.route))
        plan.extend(extra)
        missing.extend(lost)
    known_routes = {r.get("id") for r in (index or {}).get("routes", []) if isinstance(r, dict)}
    missing.extend(f"маршрута «{r}» нет в индексе" for r in args.route if r not in known_routes)

    seen, files, total = set(), [], 0
    for rel, why, section in plan:
        real = os.path.realpath(os.path.join(root, rel))
        if (real, section) in seen:
            continue
        seen.add((real, section))
        if not os.path.isfile(real):
            missing.append(f"{rel} ({why}) — файла нет")
            continue
        try:
            if section:
                start, end = kb_index.section_span(Path(real), section)
                with open(real, "rb") as f:
                    f.seek(start)
                    data = f.read(end - start)
                rel = f"{rel} § {section}"
            else:
                if os.path.getsize(real) > FILE_CAP:
                    missing.append(f"{rel} ({why}) — {os.path.getsize(real)} B больше предела "
                                   f"{FILE_CAP}: открой нужный раздел по адресу")
                    continue
                with open(real, "rb") as f:
                    data = f.read()
        except (OSError, ValueError) as exc:
            missing.append(f"{rel} ({why}) — не прочитан: {exc}")
            continue
        if b"\0" in data[:8192]:
            missing.append(f"{rel} ({why}) — двоичный файл, не текст входа")
            continue
        files.append((rel, why, data))
        total += len(data)

    out = args.out
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = git_dir(root)
    if out:
        real_out = os.path.realpath(out)
        inside_tree = real_out.startswith(os.path.realpath(root) + os.sep)
        if inside_tree and not (base and real_out.startswith(os.path.realpath(base) + os.sep)):
            print(f"BLOCKED: --out внутри рабочего дерева проекта ({out}); вход в проект не пишется")
            return 2
    else:
        # Свой файл на каждый вызов: сессии в одном checkout не затирают вход
        # друг друга. Git-каталог не отслеживается; недоступен — временный каталог.
        folder = None
        if base:
            try:
                folder = os.path.join(base, "kb-entry")
                os.makedirs(folder, exist_ok=True)
                probe = os.path.join(folder, f".probe-{os.getpid()}")
                open(probe, "w").close()
                os.remove(probe)
            except OSError:
                folder = None
        if not folder:
            folder = tempfile.mkdtemp(prefix="kb-entry-")
        out = os.path.join(folder, f"ENTRY-{stamp}-{os.getpid()}.md")
    digest = hashlib.sha256(b"".join(d for _, _, d in files)).hexdigest()
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Вход в проект {os.path.basename(root)} — "
                f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("Прочитай этот файл целиком. Каждый раздел — полный файл проекта.\n")
        for rel, why, data in files:
            f.write(f"\n\n======== {rel} · {why} · {len(data)} B ========\n\n")
            f.write(data.decode("utf-8", errors="replace"))

    now_stamp = None
    if entry.path:
        import kb_due
        stamp = kb_due.freshness_of(entry.text())
        now_stamp = re.split(r"[.;]| -->", stamp)[0].strip()[:32] if stamp else None
    print(f"ENTRY_BUNDLE={out}")
    print(f"  файлов: {len(files)}, байт: {total}")
    for rel, why, data in files:
        print(f"  · {rel} — {why}, {len(data)} B")
    for line in missing:
        print(f"  ! {line}")
    if optional:
        print("  Маршруты роли по поводу (открывай нужные задаче или добавь --route <id>):")
        for route_id, when in optional:
            print(f"    - {route_id}: {when[:110]}")
    if not args.role:
        print("  РОЛЬ НЕ ВЫБРАНА. Роли проекта (выбери по задаче и повтори с --role <id>):")
        for r in roles:
            print(f"    - {r.get('id')}: {'; '.join(r.get('load_when', [])[:2])}")
    print(f"ENTRY_RECEIPT: kb-architect {kb_paths.skill_version() or '?'} · "
          f"current {now_stamp or 'без «Обновлено»'} · роль "
          f"{', '.join(args.role) if args.role else 'не выбрана'} · файлы: {len(files)}, "
          f"{total} B, {digest[:12]}")
    print("SESSION_ACTION=READ_ENTRY_BUNDLE_WHOLE — прочитай файл целиком одним чтением "
          "(без head/limit), затем строку ENTRY_RECEIPT — в первый ответ.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
