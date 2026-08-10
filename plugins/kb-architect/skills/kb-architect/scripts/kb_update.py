#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kb_update.py — привести файловые установки скилла к доверенному источнику.

    python3 kb_update.py
    python3 kb_update.py --public
    python3 kb_update.py --public --сделать
    python3 kb_update.py --source <checkout-или-каталог-скилла>
    python3 kb_update.py --source <путь> --сделать

Без `--сделать` только показывает. Рабочие проекты используют `--public`:
стабильная редакция всегда берётся из PUBLIC GitHub. `--source` оставлен для
теста и maintainer-workflow; development-checkout не является каналом доставки.

Обновляется файл на диске, не prompt уже идущей сессии. Среда без файловой
установки (браузер, Cowork) получает точный ручной шаг и не считается обновлённой.
"""

import argparse
from datetime import datetime, timezone
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC_REPOSITORY = "https://github.com/sugestr/kb-architect.git"

# Закрытый список известных файловых установок этой машины. Другие места
# обновляются только явным отдельным механизмом, а не угадываются обходом диска.
MESTA = [
    ("Claude Code", "~/.claude/skills/kb-architect"),
    ("Codex", "~/.codex/skills/kb-architect"),
]


def versiya(path):
    p = os.path.join(path, "SKILL.md")
    if not os.path.exists(p):
        return None
    m = re.search(r'^\s+version:\s*"([^"]+)"',
                  open(p, encoding="utf-8").read(), re.M)
    return m.group(1) if m else None


def git(d, *args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True,
                           text=True, timeout=timeout)
    except Exception as exc:
        return None, str(exc)
    if r.returncode != 0:
        return None, (r.stderr.strip().splitlines() or
                      [f"код {r.returncode}"])[0]
    return r.stdout.strip(), None


def resolve_source(raw):
    """Принять skill dir, public checkout или private-lab checkout."""
    base = os.path.abspath(os.path.expanduser(raw))
    candidates = [
        base,
        os.path.join(base, "plugins", "kb-architect", "skills", "kb-architect"),
        os.path.join(base, "package", "plugins", "kb-architect", "skills",
                     "kb-architect"),
    ]
    for candidate in candidates:
        if versiya(candidate):
            return candidate
    return None


def istochnik(explicit=None):
    if explicit:
        d = resolve_source(explicit)
        return (d, None) if d else (None, f"в source не найден SKILL.md: {explicit}")
    d = os.path.dirname(HERE)
    top, err = git(d, "rev-parse", "--show-toplevel")
    return (d, None) if top else (None, err or "установка не из репозитория")


def public_source():
    """Чистый временный checkout стабильной публичной витрины."""
    temp_root = tempfile.mkdtemp(prefix="kb-architect-public-source-")
    checkout = os.path.join(temp_root, "kb-architect")
    try:
        r = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--branch", "main",
             PUBLIC_REPOSITORY, checkout],
            capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            why = (r.stderr.strip().splitlines() or [f"код {r.returncode}"])[0]
            return None, temp_root, "GitHub public не скачан: " + why
        source = resolve_source(checkout)
        if not source:
            return None, temp_root, "в GitHub public не найден каталог скилла"
        return source, temp_root, None
    except Exception as exc:
        return None, temp_root, str(exc)


def test_skill(path):
    test = os.path.join(path, "scripts", "test_kb.py")
    if not os.path.isfile(test):
        return False, "в источнике нет scripts/test_kb.py"
    try:
        r = subprocess.run([sys.executable, test], capture_output=True, text=True,
                           timeout=180)
    except Exception as exc:
        return False, str(exc)
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
        return False, "тесты не прошли: " + " | ".join(tail)
    return True, ""


def safe_replace(source, destination, old_version):
    """Staging + тест + recoverable rename вместо rmtree рабочей копии."""
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    stage_root = tempfile.mkdtemp(prefix=".kb-architect-stage-", dir=parent)
    staged = os.path.join(stage_root, "kb-architect")
    backup = None
    try:
        shutil.copytree(source, staged,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        ok, why = test_skill(staged)
        if not ok:
            return None, None, why

        backup_root = os.path.join(parent, ".backups")
        os.makedirs(backup_root, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = os.path.join(
            backup_root, f"kb-architect-{old_version or 'unknown'}-{stamp}")
        suffix = 1
        base_backup = backup
        while os.path.lexists(backup):
            backup = f"{base_backup}-{suffix}"
            suffix += 1
        os.rename(destination, backup)
        try:
            os.rename(staged, destination)
        except Exception:
            os.rename(backup, destination)
            raise

        ok, why = test_skill(destination)
        if not ok:
            failed = backup + ".failed-new"
            os.rename(destination, failed)
            os.rename(backup, destination)
            return None, failed, "после установки тесты не прошли, восстановлен backup: " + why
        return versiya(destination), backup, ""
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def prepare_source(src, do_update):
    """Подтянуть Git-source только вперёд; dirty source не распространять."""
    top, top_error = git(src, "rev-parse", "--show-toplevel")
    if not top:
        return True, "источник без Git: upstream не проверен", None

    dirty, dirty_error = git(top, "status", "--porcelain")
    if dirty_error:
        return False, "не удалось проверить чистоту source: " + dirty_error, top
    if dirty:
        if do_update:
            return False, "source содержит незакоммиченные изменения", top
        return True, "source содержит незакоммиченные изменения; --сделать будет заблокирован", top

    _, fetch_error = git(top, "fetch", "--quiet")
    if fetch_error:
        return True, "источник не опрошен: " + fetch_error, top
    behind, behind_error = git(top, "rev-list", "--count", "HEAD..@{u}")
    if behind_error:
        return True, "у source нет проверяемого upstream: " + behind_error, top
    if behind and behind.isdigit() and int(behind) > 0:
        if not do_update:
            return True, f"source отстаёт на {behind}; подтянется при --сделать", top
        _, pull_error = git(top, "pull", "--ff-only")
        if pull_error:
            return False, "pull source не прошёл: " + pull_error, top
        return True, f"source подтянут на {behind} коммит(ов)", top
    return True, "source свежий", top


def update_from_source(src, args, source_label):
    before = versiya(src)
    prepared, source_state, _top = prepare_source(src, args.do_update)
    print(f"Источник: {source_label}")
    print(f"  checkout: {src}")
    print("  " + source_state)
    if not prepared:
        print("  ОБНОВЛЕНИЕ ЗАБЛОКИРОВАНО")
        return 2
    after = versiya(src)
    if before != after:
        print(f"  редакция source: {before} → {after}")
    else:
        print(f"  редакция source: {after}")

    ok, why = test_skill(src)
    if not ok:
        print("  ОБНОВЛЕНИЕ ЗАБЛОКИРОВАНО: " + why)
        return 2
    print("  приёмочные тесты source: прошли")
    print()

    source_version = versiya(src)
    for name, raw_path in MESTA:
        path = os.path.expanduser(raw_path)
        if not os.path.lexists(path):
            print(f"{name:12} не установлен")
            continue
        if os.path.islink(path) and not args.do_update:
            target = os.path.realpath(path)
            print(f"{name:12} симлинк → {target}, редакция {versiya(path)} — "
                  "при --сделать станет управляемой копией GitHub public")
            continue
        current = versiya(path)
        if current == source_version:
            print(f"{name:12} копия, редакция {current} — совпадает с source")
            continue
        if not args.do_update:
            print(f"{name:12} копия отстала: {current} против {source_version} — "
                  "обновится при --сделать")
            continue
        new_version, backup, replace_error = safe_replace(src, path, current)
        if replace_error:
            print(f"{name:12} НЕ ОБНОВЛЁН: {replace_error}")
            return 2
        print(f"{name:12} копия обновлена: {current} → {new_version}")
        print(f"{'':12} backup: {backup}")

    print()
    print("─" * 66)
    print("Скилл уровня приложения (Claude в браузере и Cowork) отсюда недостижим:")
    print("у него нет файловой системы, и обновляется он только загрузкой файла.")
    candidates = []
    top, _ = git(src, "rev-parse", "--show-toplevel")
    if top:
        candidates.extend([os.path.join(top, "kb-architect.skill"),
                           os.path.join(top, "package", "kb-architect.skill")])
    package = next((p for p in candidates if os.path.exists(p)), "")
    if package:
        print(f"  пакет для загрузки: {package}")
    else:
        print("  собранный пакет рядом с source не найден")
    print("  загруженная текущей сессией редакция не перечитывается на лету;")
    print("  применение обновления к проекту выполняет kb_apply.py отдельно.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source", help="явный checkout для теста или maintainer-workflow")
    group.add_argument("--public", action="store_true",
                       help="всегда брать стабильный снимок из GitHub public")
    parser.add_argument("--сделать", "--do", action="store_true", dest="do_update")
    args = parser.parse_args()

    temp_root = None
    try:
        if args.public:
            src, temp_root, err = public_source()
            label = PUBLIC_REPOSITORY
        elif args.source:
            src, err = istochnik(args.source)
            label = args.source
        else:
            # Maintainer checkout может проверять собственный source. Обычная
            # installed-копия Git не имеет — тогда источник всегда GitHub public.
            src, err = istochnik()
            if src:
                label = src
            else:
                src, temp_root, err = public_source()
                label = PUBLIC_REPOSITORY
        if not src:
            print("Источник не получен: " + str(err))
            return 2
        return update_from_source(src, args, label)
    finally:
        if temp_root:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
