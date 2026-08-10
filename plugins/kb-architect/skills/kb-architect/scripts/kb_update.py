#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kb_update.py — привести все установки скилла на этой машине к источнику.

    python3 kb_update.py            посмотреть, что расходится
    python3 kb_update.py --сделать  обновить то, что можно обновить

Зачем отдельный скрипт. Автообновление, написанное в 4.5, делает `git pull`
в папке скилла — и потому работает только там, где эта папка есть репозиторий.
Замер на живой машине: из трёх установок такая одна. Копия для Codex git не
имеет и молча отстаёт; скилл уровня приложения файловой системы не имеет вовсе
и ставится только руками, файлом.

Молчание об этом было бы тем же отказом, который стандарт ловит везде: две
установки из трёх устаревают, и снаружи это неотличимо от свежих.
"""

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Где на этой машине принято держать скиллы. Список закрытый и короткий:
# угадывать чужие раскладки — значит трогать то, чего не понимаешь.
MESTA = [
    ("Claude Code", "~/.claude/skills/kb-architect"),
    ("Codex", "~/.codex/skills/kb-architect"),
]


def versiya(path):
    p = os.path.join(path, "SKILL.md")
    if not os.path.exists(p):
        return None
    m = re.search(r'^\s+version:\s*"([^"]+)"', open(p, encoding="utf-8").read(), re.M)
    return m.group(1) if m else None


def git(d, *args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True,
                           text=True, timeout=timeout)
    except Exception as e:
        return None, str(e)
    if r.returncode != 0:
        return None, (r.stderr.strip().splitlines() or [f"код {r.returncode}"])[0]
    return r.stdout.strip(), None


def istochnik():
    """Папка скилла внутри репозитория-источника."""
    d = os.path.dirname(HERE)
    top, err = git(d, "rev-parse", "--show-toplevel")
    return (d, None) if top else (None, err or "установка не из репозитория")


def main():
    delat = "--сделать" in sys.argv or "--do" in sys.argv
    src, err = istochnik()
    if not src:
        print("Источник отсюда не виден: " + err)
        print("Для обычной installed-копии без .git это штатно и не означает, что версия повреждена.")
        print("Этот скрипт запускают из установки, сделанной клоном или симлинком")
        print("на репозиторий. Адрес источника — в SKILL.md, раздел «Откуда этот скилл».")
        return 2

    # 1. Подтянуть сам источник
    print(f"Источник: {src}")
    was = versiya(src)
    _, e = git(src, "fetch", "--quiet")
    if e:
        print(f"  источник не опрошен: {e} — дальше сравниваю с тем, что скачано раньше")
    behind, e2 = git(src, "rev-list", "--count", "HEAD..@{u}")
    if behind and behind.isdigit() and int(behind) > 0:
        if delat:
            _, e3 = git(src, "pull", "--ff-only")
            print(f"  подтянуто: {was} → {versiya(src)}" if not e3 else f"  pull не прошёл: {e3}")
        else:
            print(f"  источник ушёл вперёд на {behind} — обновится при --сделать")
    else:
        print(f"  свежий: {versiya(src)}")

    ver = versiya(src)
    print()

    # 2. Установки на этой машине
    ruchnye = []
    for imya, put in MESTA:
        p = os.path.expanduser(put)
        if not os.path.exists(p):
            print(f"{imya:12} не установлен")
            continue
        if os.path.islink(p):
            print(f"{imya:12} симлинк на источник, редакция {versiya(p)} — обновляется сам")
            continue
        v = versiya(p)
        if v == ver:
            print(f"{imya:12} копия, редакция {v} — совпадает с источником")
            continue
        if delat:
            shutil.rmtree(p)
            shutil.copytree(src, p, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f"{imya:12} копия обновлена: {v} → {versiya(p)}")
        else:
            print(f"{imya:12} копия отстала: {v} против {ver} — обновится при --сделать")
            ruchnye.append(imya)

    # 3. То, что машина сделать не может
    top, _ = git(src, "rev-parse", "--show-toplevel")
    candidates = ([os.path.join(top, "kb-architect.skill"),
                   os.path.join(top, "package", "kb-architect.skill")] if top else [])
    paket = next((p for p in candidates if os.path.exists(p)), "")
    print()
    print("─" * 66)
    print("Скилл уровня приложения (Claude в браузере и Cowork) отсюда недостижим:")
    print("у него нет файловой системы, и обновляется он только загрузкой файла.")
    if os.path.exists(paket):
        pv = None
        try:
            import zipfile
            with zipfile.ZipFile(paket) as z:
                for n in z.namelist():
                    if n.endswith("SKILL.md"):
                        m = re.search(r'^\s+version:\s*"([^"]+)"',
                                      z.read(n).decode("utf-8"), re.M)
                        pv = m.group(1) if m else None
                        break
        except Exception:
            pass
        sootv = "совпадает с источником" if pv == ver else f"ВНУТРИ {pv}, а источник {ver} — пересобери"
        print(f"  собранный пакет: {paket}")
        print(f"  {sootv}")
    else:
        print("  собранного пакета нет — запусти ./build.sh в корне репозитория")
    print("  отдать его владельцу — шаг, который агент выполнить не может;")
    print("  значит он записывается с исполнителем, а не считается сделанным.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
