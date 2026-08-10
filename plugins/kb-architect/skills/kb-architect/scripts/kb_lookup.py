#!/usr/bin/env python3
"""
kb_lookup.py — что база уже знает по этим темам.

Запускается ДО того, как сессия сформулировала вывод. На вход — список тем
из нового источника, на выход — что по каждой уже лежит в базе.

    python3 kb_lookup.py <корень> "фимоз|circuncision|circumcision" "офтальмолог|oftalmolog|retina"

Каждый аргумент после корня — одна тема; варианты написания через `|`.

Зачем варианты. Архив многоязычный, и документ по теме может называться
на другом языке: поиск по русскому слову не найдёт `circuncision-fimosis.md`.
Ровно так и была пропущена операция, лежавшая в базе. Выписывая тему,
выписывай её переводы и обиходные синонимы — это часть запроса, а не
украшение.

Зачем скрипт, а не правило. Правило «прежде чем писать „вопрос открыт“ —
поищи в базе» было записано и нарушено через час: проверка стоит дороже,
чем её пропуск, и конкурирует с желанием сообщить находку. Скрипт снимает
конкуренцию — его вывод уже перед глазами к моменту, когда вывод только
формулируется.

Вывод годится для цитирования: строка «НЕ НАЙДЕНО» с перечнем того, что
именно искали, — это след выполненного запроса, а не самоотчёт о
добросовестности.
"""

import os
import re
import sys

TEXT_EXT = {".md", ".txt", ".json", ".yml", ".yaml", ".csv", ".tsv", ".py", ".org", ".rst"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".obsidian"}
MAX_FILES_SHOWN = 8
SNIPPET = 110


def collect(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def search(files, root, variants):
    """Возвращает [(путь, строка-совпадение или None если совпало только имя)]."""
    pats = [re.compile(re.escape(v.strip()), re.IGNORECASE) for v in variants if v.strip()]
    hits = []
    for path in files:
        rel = os.path.relpath(path, root)
        name_hit = any(p.search(rel) for p in pats)
        line_hit = None
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if any(p.search(line) for p in pats):
                        line_hit = line.strip()[:SNIPPET]
                        break
        except OSError:
            continue
        if name_hit or line_hit:
            hits.append((rel, line_hit))
    return hits


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    root = sys.argv[1]
    topics = sys.argv[2:]

    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2

    files = collect(root)
    print(f"База: {root} — {len(files)} текстовых файлов\n")

    found_any = False
    for topic in topics:
        variants = topic.split("|")
        hits = search(files, root, variants)
        shown = " / ".join(v.strip() for v in variants)

        if not hits:
            print(f"── {shown}")
            print(f"   НЕ НАЙДЕНО. Искали: {shown}")
            print( "   Прежде чем писать «этого нет»: добавь переводы и обиходные")
            print( "   синонимы и прогони ещё раз. Один язык — это не поиск.\n")
            continue

        found_any = True
        print(f"── {shown} — найдено в {len(hits)} файлах:")
        for rel, line in hits[:MAX_FILES_SHOWN]:
            print(f"   {rel}")
            if line:
                print(f"      … {line}")
        if len(hits) > MAX_FILES_SHOWN:
            print(f"   … и ещё {len(hits) - MAX_FILES_SHOWN}")
        print()

    if found_any:
        print("По темам с находками вывод «вопрос открыт» делать нельзя,")
        print("не прочитав найденное. Обрыв сюжета внутри источника означает")
        print("«не было в этом канале», а не «не было».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
