#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kb_update.py — привести файловые установки скилла к доверенному источнику.

    python3 kb_update.py
    python3 kb_update.py --public
    python3 kb_update.py --public --сделать
    python3 kb_update.py --public --fast --сделать --project <корень-проекта>
    python3 kb_update.py --source <checkout-или-каталог-скилла>
    python3 kb_update.py --source <путь> --сделать

Без `--сделать` только показывает. Рабочие инструкции читает уже установленная
локальная копия; `--public` использует PUBLIC GitHub только для проверки и доставки
stable. `--source` оставлен для теста и maintainer-workflow; development-checkout
не является каналом доставки.

Обновляется файл на диске, не prompt уже идущей сессии. Среда без файловой
установки (браузер, Cowork) получает точный ручной шаг и не считается обновлённой.
`--project` тем же циклом запускает разбор project delta; с `--сделать` код 1
печатает action-first continuation и не может молча выглядеть завершённым update.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC_REPOSITORY = "https://github.com/sugestr/kb-architect.git"
DEFAULT_TTL_HOURS = 24  # legacy CLI compatibility; never suppresses remote proof

# Закрытый список известных файловых установок этой машины. Другие места
# обновляются только явным отдельным механизмом, а не угадываются обходом диска.
MESTA = [
    ("Claude Code", "~/.claude/skills/kb-architect"),
    ("Codex", "~/.codex/skills/kb-architect"),
]


def cache_path():
    override = os.environ.get("KB_ARCHITECT_UPDATE_CACHE")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    root = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    return os.path.join(root, "kb-architect", "update-state.json")


def load_cache():
    try:
        with open(cache_path(), encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save_cache(data):
    """Atomic local receipt. Failure is reported, never promoted to PASS."""
    target = cache_path()
    parent = os.path.dirname(target)
    try:
        os.makedirs(parent, exist_ok=True)
        fd, staged = tempfile.mkstemp(prefix=".update-state-", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
            os.replace(staged, target)
        except Exception:
            try:
                os.unlink(staged)
            except OSError:
                pass
            raise
        return None
    except Exception as exc:
        return str(exc)


def managed_installs_match(receipt):
    expected_version = receipt.get("version")
    expected_fingerprint = receipt.get("fingerprint")
    if not expected_version or not expected_fingerprint:
        return False
    found = 0
    for _name, raw_path in MESTA:
        path = os.path.expanduser(raw_path)
        if not os.path.lexists(path):
            continue
        found += 1
        if (os.path.islink(path) or versiya(path) != expected_version
                or fingerprint(path) != expected_fingerprint):
            return False
    return found > 0


def public_head():
    try:
        result = subprocess.run(
            ["git", "ls-remote", PUBLIC_REPOSITORY, "refs/heads/main"],
            capture_output=True, text=True, timeout=30)
    except Exception as exc:
        return None, str(exc)
    if result.returncode != 0:
        why = (result.stderr.strip().splitlines() or
               [f"код {result.returncode}"])[0]
        return None, why
    row = result.stdout.strip().split()
    return (row[0], None) if row else (None, "public main не найден")


def fast_public_check(ttl_hours):
    """Probe public HEAD once; a matching receipt may skip clone, never the probe."""
    # `--ttl-hours` existed in 6.0/6.0.1. Keep accepting it so old project
    # commands do not break, but do not let elapsed time stand in for remote
    # freshness. A cold task owes one cheap HEAD probe regardless of receipt age.
    del ttl_hours
    receipt = load_cache()
    now = time.time()
    if receipt and managed_installs_match(receipt):
        head, error = public_head()
        if error:
            print("Быстрая проверка: UNKNOWN — GitHub public не опрошен: " + error)
            print("  прежняя установленная копия не объявляется свежей")
            print("UPDATE_STATUS=UNKNOWN")
            return 2
        if head == receipt.get("remote_head"):
            receipt["checked_at_epoch"] = now
            receipt["checked_at"] = datetime.now(timezone.utc).isoformat()
            cache_error = save_cache(receipt)
            if cache_error:
                print("Быстрая проверка: public HEAD не изменился, но квитанция не записана")
                print("  UNKNOWN: " + cache_error)
                print("UPDATE_STATUS=UNKNOWN")
                return 2
            print("Быстрая проверка: public HEAD не изменился; clone и тесты не нужны")
            print(f"  редакция: {receipt.get('version')}")
            print(f"  public HEAD: {head}")
            print("UPDATE_STATUS=CURRENT")
            return 0
        print("Быстрая проверка: public HEAD изменился; запускается полный gate")
        print(f"  прежний HEAD: {receipt.get('remote_head') or 'UNKNOWN'}")
        print(f"  текущий HEAD: {head}")
        return None

    print("Быстрая проверка: квитанции или parity недостаточно; запускается полный gate")
    return None


def record_public_receipt(src):
    top, _ = git(src, "rev-parse", "--show-toplevel")
    head, _ = git(top or src, "rev-parse", "HEAD")
    receipt = {
        "schema": 1,
        "repository": PUBLIC_REPOSITORY,
        "remote_head": head,
        "version": versiya(src),
        "fingerprint": fingerprint(src),
        "checked_at_epoch": time.time(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return save_cache(receipt)


def versiya(path):
    p = os.path.join(path, "SKILL.md")
    if not os.path.exists(p):
        return None
    m = re.search(r'^\s+version:\s*"([^"]+)"',
                  open(p, encoding="utf-8").read(), re.M)
    return m.group(1) if m else None


def fingerprint(path):
    """Hash управляемого дерева: номер версии сам по себе не доказывает parity."""
    rows = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__"})
        for name in sorted(files):
            if name == ".DS_Store" or name.endswith(".pyc"):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            if os.path.islink(full):
                data = ("symlink:" + os.readlink(full)).encode()
            else:
                with open(full, "rb") as stream:
                    data = stream.read()
            rows.append(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return hashlib.sha256(b"\n".join(rows)).hexdigest()


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


def apply_project(skill, project, action_mode=False):
    """Вторая половина update cycle: обнаружить незакрытую project delta."""
    root = os.path.abspath(os.path.expanduser(project))
    script = os.path.join(skill, "scripts", "kb_apply.py")
    if not os.path.isdir(root):
        print(f"Применение не запущено: нет каталога проекта {root}")
        return 2
    if not os.path.isfile(script):
        print(f"Применение не запущено: в source нет {script}")
        return 2
    print()
    print("═" * 66)
    print(f"ПРИМЕНЕНИЕ К ПРОЕКТУ: {root}")
    try:
        result = subprocess.run([sys.executable, script, root], timeout=180)
    except Exception as exc:
        print("Применение не запущено: " + str(exc))
        return 2
    if result.returncode == 1:
        if action_mode:
            print("SESSION_ACTION=APPLY_PROJECT_DELTA_NOW")
            print("  Команда обновления — не report-only: продолжи обратимые "
                  "project-local изменения по references/migration.md.")
            print("  Остановись перед post-results acceptance, secret/private "
                  "runtime, push или иным отдельным owner gate.")
        else:
            print("SESSION_STATE=PROJECT_DELTA_OPEN")
    return result.returncode


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


def update_from_source(src, args, source_label, record_receipt=False):
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
    installed = False
    pending = False
    managed_count = 0
    for name, raw_path in MESTA:
        path = os.path.expanduser(raw_path)
        if not os.path.lexists(path):
            print(f"{name:12} не установлен")
            continue
        managed_count += 1
        was_link = os.path.islink(path)
        if was_link and not args.do_update:
            target = os.path.realpath(path)
            print(f"{name:12} симлинк → {target}, редакция {versiya(path)} — "
                  "при --сделать станет управляемой копией GitHub public")
            pending = True
            continue
        current = versiya(path)
        same_content = (not was_link and fingerprint(path) == fingerprint(src))
        if current == source_version and same_content:
            print(f"{name:12} копия, редакция {current} — совпадает с source")
            continue
        if not args.do_update:
            if current == source_version:
                print(f"{name:12} редакция {current}, но содержимое отличается — "
                      "обновится при --сделать")
            else:
                print(f"{name:12} копия отстала: {current} против {source_version} — "
                      "обновится при --сделать")
            pending = True
            continue
        new_version, backup, replace_error = safe_replace(src, path, current)
        if replace_error:
            print(f"{name:12} НЕ ОБНОВЛЁН: {replace_error}")
            return 2
        action = "симлинк заменён управляемой копией" if was_link else "копия обновлена"
        print(f"{name:12} {action}: {current} → {new_version}")
        print(f"{'':12} backup: {backup}")
        installed = True

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
    if installed:
        status = "INSTALLED"
        result = 0
    elif pending:
        status = "UPDATE_AVAILABLE"
        result = 1
    elif managed_count == 0:
        status = "UPDATE_AVAILABLE"
        result = 1
    else:
        status = "CURRENT"
        result = 0

    # Public freshness is a two-part claim: source validation plus a durable
    # receipt that binds the installed bytes to that public HEAD. Never print a
    # successful machine status before the second part has actually succeeded.
    if result == 0 and record_receipt:
        cache_error = record_public_receipt(src)
        if cache_error:
            print("Квитанция быстрого режима не записана: UNKNOWN — " + cache_error)
            print("UPDATE_STATUS=UNKNOWN")
            return 2

    if status == "INSTALLED":
        print("UPDATE_STATUS=INSTALLED")
        print("SESSION_ACTION=REREAD_INSTALLED_ENTRY_AND_CURRENT_ROUTE")
    elif status == "UPDATE_AVAILABLE":
        print("UPDATE_STATUS=UPDATE_AVAILABLE")
        print("SESSION_ACTION=RERUN_WITH_DO")
    else:
        print("UPDATE_STATUS=CURRENT")
    print("  старый prompt не исчезает: новая task читает установленный entry до работы;")
    print("  длинная task перечитывает entry/изменившийся route на безопасной границе.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source", help="явный checkout для теста или maintainer-workflow")
    group.add_argument("--public", action="store_true",
                       help="всегда брать стабильный снимок из GitHub public")
    parser.add_argument("--fast", action="store_true",
                        help="ls-remote всегда; clone только при изменении/parity gap")
    parser.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS,
                        help="устаревшая совместимая опция; remote-check не отключает")
    parser.add_argument("--project",
                        help="после доставки сразу проверить дельту этого проекта")
    parser.add_argument("--сделать", "--do", action="store_true", dest="do_update")
    args = parser.parse_args()

    if args.fast and not args.public:
        parser.error("--fast применяется только вместе с --public")
    if args.ttl_hours < 0:
        parser.error("--ttl-hours не может быть отрицательным")

    if args.public and args.fast:
        fast_result = fast_public_check(args.ttl_hours)
        if fast_result is not None:
            if fast_result == 0 and args.project:
                return apply_project(os.path.dirname(HERE), args.project,
                                     action_mode=args.do_update)
            return fast_result

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
        result = update_from_source(src, args, label, record_receipt=args.public)
        if result == 0 and args.project:
            result = apply_project(src, args.project, action_mode=args.do_update)
        return result
    finally:
        if temp_root:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
