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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_paths

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


def search_refs(root, refs, variants):
    """Совпадения в неслитых ветках: [(ветка, файл, строка или None)].

    Рабочее дерево — не весь репозиторий. Отчёт 18.08: полис лежал в ветке,
    не влитой четыре дня, поиск ответил «в базе нет», и документ выкачали и
    разобрали заново. Вывод «этого нет» обязан покрывать и то, что доставлено,
    но не слито, — иначе он говорит о рабочем дереве, а звучит про базу.
    """
    git_root = kb_paths.find_git(root)
    if not git_root:
        return []
    # Файл, который есть в рабочем дереве, из веток не показывается: канон
    # уже ответил, а вторая копия того же — шум, от которого отчёт перестают
    # читать. Показывается только то, чего в каноне нет.
    hits = []
    for ref in refs:
        for v in variants:
            v = v.strip()
            if not v:
                continue
            out, _ = kb_paths.git_out(git_root, "grep", "-I", "-i", "-n",
                                      "-e", v, ref)
            for line in (out or "").split("\n"):
                if not line:
                    continue
                # формат: <ref>:<путь>:<номер>:<строка>
                parts = line.split(":", 3)
                if len(parts) < 4:
                    continue
                hits.append((ref, parts[1], parts[3].strip()[:SNIPPET]))
            names, _ = kb_paths.git_out(git_root, "ls-tree", "-r",
                                        "--name-only", ref)
            for path in (names or "").split("\n"):
                if path and re.search(re.escape(v), path, re.IGNORECASE):
                    hits.append((ref, path, None))
    # один файл — одна строка, первая находка
    seen, out = set(), []
    for ref, path, line in hits:
        if (ref, path) in seen:
            continue
        if os.path.exists(os.path.join(root, path)):
            continue
        seen.add((ref, path))
        out.append((ref, path, line))
    return out


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
    vetki, vetki_why = kb_paths.unmerged_refs(root)
    refs = [v.name for v in vetki]
    if refs:
        gde = f"{len(files)} текстовых файлов + неслитых веток: {len(refs)}"
    elif vetki_why:
        gde = f"{len(files)} текстовых файлов; неслитые ветки не проверены — {vetki_why}"
    else:
        gde = f"{len(files)} текстовых файлов; неслитых веток нет"
    print(f"База: {root} — {gde}\n")

    found_any = False
    for topic in topics:
        variants = topic.split("|")
        hits = search(files, root, variants)
        shown = " / ".join(v.strip() for v in variants)
        vne = search_refs(root, refs, variants) if refs else []

        if not hits and not vne:
            print(f"── {shown}")
            print(f"   НЕ НАЙДЕНО. Искали: {shown} — в {gde}")
            print( "   Прежде чем писать «этого нет»: добавь переводы и обиходные")
            print( "   синонимы и прогони ещё раз. Один язык — это не поиск.\n")
            continue

        found_any = True
        if hits:
            print(f"── {shown} — найдено в {len(hits)} файлах:")
            for rel, line in hits[:MAX_FILES_SHOWN]:
                print(f"   {rel}")
                if line:
                    print(f"      … {line}")
            if len(hits) > MAX_FILES_SHOWN:
                print(f"   … и ещё {len(hits) - MAX_FILES_SHOWN}")
        else:
            print(f"── {shown} — в рабочем дереве нет.")

        if vne:
            print(f"   ЕСТЬ ВНЕ КАНОНА — {len(vne)} файлов в неслитых ветках:")
            for ref, path, line in vne[:MAX_FILES_SHOWN]:
                print(f"   {ref}: {path}")
                if line:
                    print(f"      … {line}")
            if len(vne) > MAX_FILES_SHOWN:
                print(f"   … и ещё {len(vne) - MAX_FILES_SHOWN}")
            print( "   Это доставлено, но не влито. Не переделывай работу заново")
            print( "   и не пиши «в базе нет»: сначала слияние или явный отказ.")
        print()

    if found_any:
        print("По темам с находками вывод «вопрос открыт» делать нельзя,")
        print("не прочитав найденное. Обрыв сюжета внутри источника означает")
        print("«не было в этом канале», а не «не было».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
