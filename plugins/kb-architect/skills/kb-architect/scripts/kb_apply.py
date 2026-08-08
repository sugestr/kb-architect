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

    print(f"Вышла редакция новее вашей: проект на {proj}, установлен {inst}.")
    print(f"Между ними выпусков: {len(rows)}. Ниже — что каждый меняет и")
    print(f"есть ли в этой базе то, чего он касается.\n")

    likely = 0
    for v, text in rows:
        hits = sorted({trait for kw, trait in APPLICABLE
                       if kw in text.lower() and traits.get(trait)})
        mark = "→ КАСАЕТСЯ" if hits else "  вероятно, мимо"
        if hits:
            likely += 1
        short = re.sub(r"\*\*|`", "", text)
        short = (short[:400] + "…") if len(short) > 400 else short
        print(f"{mark}  {v}")
        if hits:
            print(f"           признаки базы: {', '.join(hits)}")
        print(f"           {short}\n")

    print("─" * 70)
    print(f"Похоже, касается выпусков: {likely} из {len(rows)}.")
    print("Признаки грубые: они отвечают «возможно», а не «да». Точный ответ")
    print("даёт прогон kb_check.py и kb_due.py после применения.\n")
    print("НИЧЕГО НЕ ПРИМЕНЕНО. Дальше — решение владельца, а не сессии:")
    print("  1. показать ему этот список;")
    print("  2. спросить, применяем ли, и что из этого он брать не хочет;")
    print("  3. применить согласованное, обновить kb_standard_version,")
    print("     записать в «Соответствие», что взято и от чего отказались;")
    print("  4. прогнать проверки и сравнить с тем, что было до.")
    print("\nОтказ от части правок — часть системы, а не отступление от неё.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
