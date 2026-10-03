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

С 7.4.0 каждая часть файла заканчивается меткой «часть i/n · метка xxxx». Метки
случайны и видны только в файле: `kb_start.py confirm <корень> --token <метки>`
принимает их как доказательство, что файл прочитан до конца, и снимает замок
правок, который ставит hook входа. Рядом с файлом лежит `<файл>.json` с хэшами
меток (не с самими метками). Несуществующая роль не попадает в квитанцию:
01.10.2026 `--role odoo-engineer` давал «роль odoo-engineer» без роли в файле.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_index
import kb_paths
import kb_skills

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


def part_hash(fragment):
    return hashlib.sha256(f"kb-entry-part:{fragment}".encode()).hexdigest()


def role_files(root, registry, index, wanted, chosen_routes, methods=None):
    """[(rel, why)] для выбранных ролей, их прочие маршруты и ненайденное."""
    out, missing, optional = [], [], []
    roles = registry.get("roles", []) if isinstance(registry, dict) else []
    skills = {s.get("name"): s for s in registry.get("skills", [])
              if isinstance(s, dict)} if isinstance(registry, dict) else {}
    routes = {r.get("id"): r for r in (index or {}).get("routes", []) if isinstance(r, dict)}
    selected = []
    for want in wanted:
        # Сначала точное имя роли, потом имя навыка: в Adas startup роль adas-venture-steward
        # совпадала с навыком другой роли, и вход собирался не для той (03.10.2026).
        role = next((r for r in roles if isinstance(r, dict) and r.get("id") == want), None) or \
            next((r for r in roles if isinstance(r, dict) and r.get("skill") == want), None)
        if not role:
            missing.append(f"роль «{want}» не найдена в PROJECT_ROLES.json")
            continue
        selected.append(role["id"])
    # Внешний аудит 03.10.2026: ограничения предков тоже обязательны на входе.
    by_id = {r["id"]: r for r in roles if isinstance(r, dict) and r.get("id")}
    ordered, errors = kb_skills.role_closure(by_id, selected)
    missing.extend(f"наследование роли: {error}" for error in errors)
    for role_id in ordered:
        role = by_id[role_id]
        skill = skills.get(role.get("skill"))
        canonical = skill.get("canonical") if skill else None
        if canonical:
            rel = os.path.join(canonical, "SKILL.md")
            out.append((rel, f"роль {role['id']}: метод", None))
            if methods is not None:
                methods[role_id] = os.path.realpath(os.path.join(root, rel))
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


def declared_roles(root):
    """(роли реестра, роль входа по умолчанию) из PROJECT_ROLES.json.

    Роль по умолчанию — поле `entry_role` (строка или список); единственная роль
    проекта — она же. Иначе роли нет: выбор по задаче остаётся сессии."""
    registry = load_json(os.path.join(root, "PROJECT_ROLES.json")) or {}
    roles = [r for r in registry.get("roles", []) if isinstance(r, dict) and r.get("id")]
    default = registry.get("entry_role")
    if isinstance(default, str):
        default = [default]
    if not isinstance(default, list):
        default = [roles[0]["id"]] if len(roles) == 1 else []
    return roles, [d for d in default if isinstance(d, str) and d]


def build(root, roles_wanted=(), routes_wanted=(), skip=()):
    """Состав входа без записи: файлы, ненайденное, маршруты роли по поводу.

    `skip` — имена файлов правил, которые агент уже загружает сам (CLAUDE.md
    у Claude, AGENTS.md у Codex): hook входа не кладёт их второй раз. Сравнение
    по realpath: `AGENTS.md -> CLAUDE.md` — один файл, Codex его уже прочитал.
    Последняя часть файла — роли проекта и маршруты по поводу: так у любого
    входа есть хотя бы одна метка, а выбор роли лежит рядом с её подтверждением."""
    plan, missing = [], []
    skipped = {os.path.realpath(os.path.join(root, n)) for n in skip
               if os.path.exists(os.path.join(root, n))}
    for path in kb_paths.rules_files(root):
        if os.path.realpath(path) in skipped:
            continue
        plan.append((os.path.relpath(path, root), "правила проекта", None))
    entry = kb_paths.locate(root, "entry")
    if entry.path:
        plan.append((os.path.relpath(entry.path, root), "current", None))
    elif entry.section is None:
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
        if isinstance(route, dict) and (route.get("id") in routes_wanted or (
                route.get("id") != (index or {}).get("current")
                and ALWAYS.search("; ".join(route.get("load_when", []))))):
            for rel, section in route_units(route):
                plan.append((rel, f"маршрут {route['id']}"
                                  + ("" if route.get("id") in routes_wanted else " (всегда)"), section))
    optional, methods = [], {}
    if roles_wanted:
        extra, lost, optional = role_files(root, registry or {}, index, list(roles_wanted),
                                           set(routes_wanted), methods)
        plan.extend(extra)
        missing.extend(lost)
    known_routes = {r.get("id") for r in (index or {}).get("routes", []) if isinstance(r, dict)}
    missing.extend(f"маршрута «{r}» нет в индексе" for r in routes_wanted if r not in known_routes)

    seen, included, files, total = set(), set(), [], 0
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
        included.add((real, section))
        total += len(data)

    # Внешний аудит 03.10.2026: имя роли подтверждает только прочитанный метод.
    found_roles = [role_id for role_id, real in methods.items() if (real, None) in included]
    for role_id, real in methods.items():
        if (real, None) not in included:
            rel = os.path.relpath(real, root)
            reasons = [m for m in missing if m.startswith(rel)]
            missing.append(f"роль {role_id}: метод {rel} не включён во вход"
                           + (f" ({'; '.join(reasons)})" if reasons else ""))

    roles_text = ["Роли проекта (id: поводы). Роль выбирается по задаче владельца; другая —",
                  "`kb_entry.py <корень> --role <id>` и подтверждение метками её файла.", ""]
    for r in roles:
        roles_text.append(f"- {r.get('id')}: {'; '.join(r.get('load_when', []))}")
    if not roles:
        roles_text.append("- ролей в PROJECT_ROLES.json нет")
    if found_roles:
        roles_text += ["", f"В этом файле метод роли: {', '.join(found_roles)}."]
    if optional:
        roles_text += ["", "Маршруты роли по поводу (адреса, не чтение на входе):"]
        roles_text += [f"- {rid}: {when}" for rid, when in optional]
    data = ("\n".join(roles_text) + "\n").encode("utf-8")
    files.append(("роли проекта", "выбор роли", data))
    total += len(data)

    now_stamp = None
    if entry.found:
        import kb_due
        stamp = kb_due.freshness_of(entry.text())
        now_stamp = re.split(r"[.;]| -->", stamp)[0].strip()[:32] if stamp else None
    # Замок держат только пробелы ролей (метода нет, не прочитан, предок сломан): их можно
    # обойти другой ролью или «без роли». Пропавший прочий файл — предупреждение, иначе тупик:
    # починить проект нельзя, пока замок закрыт.
    blocking = [m for m in missing if m.startswith(("роль ", "наследование роли"))]
    return {"files": files, "missing": missing, "blocking": blocking, "optional": optional,
            "roles": roles, "found_roles": found_roles, "total": total, "now_stamp": now_stamp}


def default_out(root):
    """Свой файл на каждый вызов: сессии в одном checkout не затирают вход
    друг друга. Git-каталог не отслеживается; недоступен — временный каталог."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = git_dir(root)
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
    if folder:
        # hook входа собирает файл на каждом старте и сжатии: старше недели — мусор
        limit = time.time() - 7 * 86400
        for name in os.listdir(folder):
            if name.startswith("ENTRY-"):
                try:
                    if os.path.getmtime(os.path.join(folder, name)) < limit:
                        os.remove(os.path.join(folder, name))
                except OSError:
                    pass
    if not folder:
        folder = tempfile.mkdtemp(prefix="kb-entry-")
    return os.path.join(folder, f"ENTRY-{stamp}-{os.getpid()}-{secrets.token_hex(2)}.md")


def out_blocked(root, out):
    real_out = os.path.realpath(out)
    base = git_dir(root)
    inside_tree = real_out.startswith(os.path.realpath(root) + os.sep)
    return inside_tree and not (base and real_out.startswith(os.path.realpath(base) + os.sep))


def receipt_line(result, digest):
    roles = result["found_roles"]
    return (f"ENTRY_RECEIPT: kb-architect {kb_paths.skill_version() or '?'} · "
            f"current {result['now_stamp'] or 'без «Обновлено»'} · роль "
            f"{', '.join(roles) if roles else 'не выбрана'} · файлы: {len(result['files'])}, "
            f"{result['total']} B, {digest[:12]}")


def write(root, result, out, header_note=""):
    """Пишет файл входа с метками частей и спутник `<файл>.json`.

    Возвращает (digest, метки по порядку). Метки не печатаются: их видно только
    в файле, по одной в конце каждой части."""
    files = result["files"]
    digest = hashlib.sha256(b"".join(d for _, _, d in files)).hexdigest()
    fragments = [secrets.token_hex(2) for _ in files]
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Вход в проект {os.path.basename(root)} — "
                f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("Прочитай этот файл целиком. Каждый раздел — полный файл проекта; в конце "
                "каждой части — метка. Метки всех частей по порядку через «-» подтверждают "
                "вход: kb_start.py confirm.\n")
        if header_note:
            f.write(header_note.rstrip() + "\n")
        for n, (rel, why, data) in enumerate(files, 1):
            f.write(f"\n\n======== {rel} · {why} · {len(data)} B ========\n\n")
            f.write(data.decode("utf-8", errors="replace"))
            f.write(f"\n\n[kb-entry · часть {n}/{len(files)} · метка {fragments[n - 1]}]\n")
    sidecar = {"schema": 1, "root": os.path.realpath(root), "bundle": os.path.realpath(out),
               "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "roles": result["found_roles"], "parts": len(files),
               # Внешний аудит 03.10.2026: метки неполного входа не снимают замок.
               "missing": result["missing"], "blocking": result["blocking"],
               "part_sha256": [part_hash(x) for x in fragments],
               "receipt": receipt_line(result, digest)}
    try:
        with open(out + ".json", "w", encoding="utf-8") as f:
            json.dump(sidecar, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return digest, fragments


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--route", action="append", default=[],
                        help="маршрут индекса, нужный задаче: читается целиком")
    parser.add_argument("--out")
    parser.add_argument("--agent", choices=("claude", "codex"),
                        help="не класть правила, которые этот агент загружает сам")
    args = parser.parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2
    out = args.out
    if out and out_blocked(root, out):
        print(f"BLOCKED: --out внутри рабочего дерева проекта ({out}); вход в проект не пишется")
        return 2
    skip = {"claude": ("CLAUDE.md",), "codex": ("AGENTS.md",)}.get(args.agent, ())
    result = build(root, args.role, args.route, skip=skip)
    files, missing, optional, roles = (result["files"], result["missing"], result["optional"],
                                       result["roles"])
    total = result["total"]
    if not out:
        out = default_out(root)
    digest, _ = write(root, result, out)
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
    print(receipt_line(result, digest))
    start = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_start.py")
    print(f"ENTRY_CONFIRM: python3 {shlex.quote(start)} confirm {shlex.quote(root)} "
          f"--bundle {shlex.quote(out)} --token <метки {len(files)} частей по порядку через «-»>")
    print("SESSION_ACTION=READ_ENTRY_BUNDLE_WHOLE — прочитай файл целиком (большой — частями до "
          "конца, без пропусков), подтверди метками, строку ENTRY_RECEIPT — в первый ответ.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
