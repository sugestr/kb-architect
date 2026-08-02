#!/usr/bin/env python3
"""
kb_check.py — целостность базы. Три проверки, которые не шумят.

    python3 kb_check.py <корень базы>

Это не линтер. Линтер пытался проверять два десятка правил, половину из них
машинно проверить нельзя, и на живом репозитории он давал сотни ложных
срабатываний — то есть выключался на второй день. Выключенный линтер хуже
отсутствующего: на нём висит всё обещание проверяемости.

Здесь три проверки. Каждая либо находит настоящую поломку, либо молчит.

  1. Ссылка на файл, которого нет.  Битая ссылка внутри базы — знание,
     которое уже потеряно, просто об этом никто не знает.

  2. Истёкший valid_until.  Файл заявил срок, за который отвечает, и срок
     прошёл. Заявленно просроченный хуже просто старого: он выглядит
     дисциплинированным.

  3. Пустой verify.  Поле заведено и не заполнено — утверждение о
     совершённом действии без доказательства, выданное за факт.

Чего здесь намеренно нет: проверок «файл зарегистрирован в карте», «размер
превышен», «паспорт неполон». Они либо шумят, либо проверяют форму вместо
содержания.

Выход: 0 — чисто, 1 — есть находки. Годится для pre-commit.
"""

import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb_dates import parse_dates, infer_order

TEXT_EXT = {".md"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             "_raw", "_work", "archive", "архив", "Archive"}

FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE = re.compile(r"`[^`]*`")
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
VALID_UNTIL = re.compile(r"^\s*valid_until\s*:\s*(\S+)", re.MULTILINE)
VERIFY = re.compile(r"^\s*verify\s*:\s*(.*)$", re.MULTILINE)
DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")

EMPTY_VERIFY = {"", "-", "—", "tbd", "TBD", "?", "null", "none", "нет"}


def collect(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def strip_code(text):
    """Код и примеры не проверяются: там живут плейсхолдеры и чужие пути."""
    text = FENCE.sub("", text)
    return INLINE.sub("", text)


def is_internal(target):
    t = target.strip()
    if not t or t.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:")):
        return False
    if t.startswith("<") or "<" in t:   # плейсхолдер шаблона
        return False
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = os.path.abspath(sys.argv[1])
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2

    today = datetime.date.today()
    broken, expired, blank = [], [], []
    files_all = collect(root)
    ORDER = infer_order(open(f, encoding="utf-8", errors="ignore").read() for f in files_all[:400])

    for path in files_all:
        rel = os.path.relpath(path, root)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
        except OSError:
            continue
        body = strip_code(raw)

        # 1. битые ссылки
        for target in LINK.findall(body):
            if not is_internal(target):
                continue
            clean = target.split("#")[0].split("?")[0].strip()
            if not clean:
                continue
            # путь может быть задан относительно файла или относительно корня
            # базы — оба написания встречаются в живых репозиториях, и считать
            # второе поломкой значит производить шум вместо находок
            near = os.path.normpath(os.path.join(os.path.dirname(path), clean))
            from_root = os.path.normpath(os.path.join(root, clean.lstrip("/")))
            if not os.path.exists(near) and not os.path.exists(from_root):
                broken.append((rel, clean))

        # 2. истёкший срок годности
        for val in VALID_UNTIL.findall(raw):
            got, _ = parse_dates(val, day_first=ORDER)
            for d in got:
                if d < today:
                    expired.append((rel, d, (today - d).days))

        # 3. пустой verify
        for val in VERIFY.findall(raw):
            if val.strip().strip("<>").lower() in EMPTY_VERIFY:
                blank.append(rel)

    # 4. Объём входа — единственный численный лимит контракта, и потому
    # единственный, который проверяется механически бесплатно.
    ENTRY_LIMIT = 8 * 1024
    oversized = None
    for name in ("NOW.md", "STATUS.md"):
        cand = os.path.join(root, name)
        if os.path.isfile(cand):
            size = os.path.getsize(cand)
            if size > ENTRY_LIMIT:
                oversized = (name, size)
            break

    found = 0

    if oversized:
        name, size = oversized
        found += 1
        print(f"ВХОД ПЕРЕРОС ПОТОЛОК — {name}: {size / 1024:.1f} КБ при потолке 8 КБ "
              f"(×{size / ENTRY_LIMIT:.1f}):")
        print("  Мера в байтах, а не в строках: в плотном markdown с таблицами строка")
        print("  не единица объёма, и лимит «по строкам» проходит там, где байтовый нет.")
        print("  Обычно причина — историческое накопление внутри входа: закрытые сюжеты,")
        print("  оставленные абзацами. Цена не в ошибке, а в счёте за каждую сессию.\n")

    if broken:
        found += len(broken)
        print(f"БИТЫЕ ССЫЛКИ — {len(broken)}:")
        for rel, target in broken[:20]:
            print(f"  {rel} → {target}")
        if len(broken) > 20:
            print(f"  … и ещё {len(broken) - 20}")
        print("  Знание по этим ссылкам уже потеряно, просто это ещё не заметили.\n")

    if expired:
        found += len(expired)
        print(f"ИСТЁК СРОК ГОДНОСТИ — {len(expired)}:")
        for rel, d, age in sorted(expired, key=lambda x: x[1])[:20]:
            print(f"  {rel} — valid_until {d}, просрочен на {age} дн.")
        if len(expired) > 20:
            print(f"  … и ещё {len(expired) - 20}")
        print("  Заявленно просроченный файл хуже просто старого: он выглядит дисциплинированным.\n")

    if blank:
        found += len(blank)
        uniq = sorted(set(blank))
        print(f"ПУСТОЙ verify — {len(uniq)} файлов:")
        for rel in uniq[:20]:
            print(f"  {rel}")
        if len(uniq) > 20:
            print(f"  … и ещё {len(uniq) - 20}")
        print("  Утверждение о совершённом действии без доказательства — это TBD, а не факт.\n")

    if not found:
        print("целостность: чисто (битых ссылок, просроченных сроков и пустых verify нет)")
        return 0

    print(f"итого находок: {found}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
