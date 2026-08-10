#!/usr/bin/env python3
"""
kb_apply.py — что новая редакция значит для ЭТОЙ базы.

    python3 kb_apply.py <корень базы>

Скрипт **ничего не применяет**. Он собирает разбор и заканчивается вопросом
владельцу. Установить новый код и привести базу в соответствие — разные
действия; второе меняет соглашения проекта, а это правило 4: показать, что
меняется, получить «да», потом делать.

Зачем отдельная команда. `kb_due.py` умеет сказать «проект записан на 4.0,
установлен 4.5 — посмотри таблицу выпусков». Это верно и бесполезно:
таблица выпусков — семьдесят килобайт, и владелец не должен её читать,
чтобы узнать, касается ли его хоть одна строка. Здесь строки между двумя
редакциями достаются сами, и рядом с каждой — признак: есть ли в этой
базе то, чего она касается.

Признаки грубые и помечены как грубые. Они отвечают «возможно, касается»,
а не «касается»; ошибка в сторону лишнего внимания здесь дешевле, чем
пропуск. Точный ответ даёт прогон проверок после применения.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_paths

ROW = re.compile(r"^\|\s*(\d+\.\d+)\s*\|\s*(.+?)\s*\|\s*[^|]*\|\s*$", re.MULTILINE)
# Метка «что обязан сделать проект». Ставится только у выпусков, менявших
# обязанности проекта.
ACT = re.compile(r"⟦Д:\s*(.+?)⟧", re.DOTALL)
# Метка новой опциональной возможности. Она не становится обязанностью оттого,
# что приехала со скиллом, но должна быть видна владельцу: 4.19 добавил работу
# Claude + Codex, а старый kb_apply.py напечатал «дел нет», поэтому ни один
# проект не узнал о способности. Молчание смешало «действий нет» и «решение не
# принято» — тот же fail-open, ради которого существует весь скрипт.
CHOICE = re.compile(r"⟦В:\s*(.+?)⟧", re.DOTALL)


def ver_key(v):
    return tuple(int(x) for x in v.split("."))


def releases_between(low, high):
    """Строки таблицы выпусков в (low, high] — по возрастанию."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     os.pardir, "references", "releases.md")
    rows = []
    for v, text in ROW.findall(kb_paths.read(p)):
        try:
            if ver_key(low) < ver_key(v) <= ver_key(high):
                rows.append((v, text))
        except ValueError:
            continue
    return sorted(rows, key=lambda r: ver_key(r[0]))


def base_traits(root):
    """Грубые признаки базы: что в ней есть такого, чего касаются правки."""
    t = {}
    entry = kb_paths.locate(root, "entry")
    journal = kb_paths.locate(root, "journal")
    corr = kb_paths.locate(root, "corrections")
    quest = kb_paths.locate(root, "questions")

    t["вход"] = entry.found or bool(entry.declared)
    t["вход не в корне"] = bool(entry.path) and os.path.dirname(
        os.path.abspath(entry.path)) != os.path.abspath(root)
    t["журнал разделом"] = journal.found and journal.path is None
    t["журнал"] = journal.found
    t["канал правок"] = corr.found
    t["многострочные записи канала"] = corr.found and any(
        not ln.lstrip().startswith(("- ", "* ", "#")) and ln.strip()
        for ln in corr.text().splitlines())
    t["контрольные вопросы"] = quest.found
    t["журнал прогонов"] = quest.found and kb_paths.section(
        quest.text(), ("ЖУРНАЛ ПРОГОНОВ", "ПРОГОНЫ")) is not None
    t["git"] = os.path.isdir(os.path.join(root, ".git"))
    rules = kb_paths.rules_path(root)
    rtext = kb_paths.read(rules) if rules else ""
    t["несколько пишущих"] = bool(re.search(r"владени|несколько пишущих|две линии|"
                                            r"два агента|codex", rtext, re.IGNORECASE))
    t["зеркала"] = bool(re.search(r"зеркал|mirror", rtext, re.IGNORECASE))
    return t


# Ключевое слово в строке выпуска → признак базы, который делает её применимой.
APPLICABLE = [
    ("вход", "вход"),
    ("подпапк", "вход не в корне"),
    ("журнал", "журнал"),
    ("колонк", "журнал"),
    ("канал правок", "канал правок"),
    ("многострочн", "многострочные записи канала"),
    ("контрольны", "контрольные вопросы"),
    ("прогон", "журнал прогонов"),
    ("git", "git"),
    ("коммит", "git"),
    ("пишущ", "несколько пишущих"),
    ("зеркал", "зеркала"),
]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = os.path.abspath(sys.argv[1])
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2

    proj, raw = kb_paths.project_version(root)
    inst = kb_paths.skill_version()

    if not inst:
        print("не вижу установленной редакции — читать нечего")
        return 2
    if not proj:
        print(f"Редакция проекта не записана числом{f' (записано: «{raw}»)' if raw else ''}.")
        print(f"Установлен скилл {inst}. Впиши в «Соответствие» строку")
        print(f"«kb_standard_version: {inst}» — без неё сравнивать не с чем.")
        return 1
    if ver_key(proj) >= ver_key(inst):
        print(f"проект на {proj}, установлен {inst} — применять нечего")
        return 0

    rows = releases_between(proj, inst)
    traits = base_traits(root)

    dela = []
    vozmozhnosti = []
    for v, text in rows:
        for m in ACT.findall(text):
            dela.append((v, " ".join(m.split())))
        for m in CHOICE.findall(text):
            vozmozhnosti.append((v, " ".join(m.split())))

    print(f"Проект на {proj}, установлен скилл {inst}. Между ними выпусков: {len(rows)}.\n")

    if not dela:
        print("ОБЯЗАТЕЛЬНЫХ ДЕЛ НЕТ. Правки инструментов и текста уже работают,")
        print("потому что скилл установлен.\n")
    else:
        print(f"ТРЕБУЮТ ДЕЙСТВИЯ: {len(dela)} из {len(rows)}. Остальные — правки инструментов")
        print("и текста, они уже работают и от базы ничего не требуют.\n")
        for k, (v, act) in enumerate(dela, 1):
            print(f"  {k}. [{v}] {act}\n")

    if vozmozhnosti:
        print(f"НОВЫЕ ВОЗМОЖНОСТИ НА РЕШЕНИЕ: {len(vozmozhnosti)}.")
        print("Они не применяются автоматически и не становятся обязанностью проекта.\n")
        for k, (v, choice) in enumerate(vozmozhnosti, 1):
            print(f"  {k}. [{v}] {choice}\n")
    else:
        print("НОВЫХ ВОЗМОЖНОСТЕЙ, ТРЕБУЮЩИХ РЕШЕНИЯ, НЕТ.\n")

    hits_all = sorted({t for t in traits if traits[t]})
    if hits_all:
        print(f"Что в этой базе вообще есть: {', '.join(hits_all)}.")
    print()
    print("─" * 70)
    print("Дальше по порядку:")
    print("  1. сделать обязательные дела выше;")
    print("  2. по каждой новой возможности записать: принято / отклонено /")
    print("     отложено. Принятое применить; если решения владельца нет — спросить;")
    print("  3. прогнать kb_check.py и kb_due.py: они написаны новее вашей")
    print("     редакции и найдут ошибки, которые база могла накопить под старой;")
    print("  4. поправить найденное, каждую правку — записью в канал с адресом;")
    print("  5. обновить kb_standard_version на " + str(inst) + " и записать")
    print("     в «Соответствие», что взято и от чего отказались.")
    print()
    print("От чего-то можно отказаться — это часть системы, а не отступление.")
    print("Но отказ записывается, иначе следующая сессия примет его за недоделку.")


if __name__ == "__main__":
    sys.exit(main())
