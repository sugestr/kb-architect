#!/usr/bin/env python3
"""
kb_due.py — что в базе просрочено. Запускается при входе в сессию.

    python3 kb_due.py <корень базы>

Ничего не требует сверх контракта: все даты уже лежат в файлах, которые
контракт и так велит вести. Скрипт их читает и считает — владельцу не надо
помнить ни одной из них.

Смотрит четыре вещи:

  вход           строка «Обновлено» в NOW.md — не устарел ли снимок
  ожидания       раздел «ЧЕГО ЖДЁМ» — не просрочено ли что-то
  журнал         последняя запись в SLOMALOS.md — давно ли разбирали
  вопросы        последний прогон в QUESTIONS.md — давно ли проверяли базу
  git            незакоммиченное и незапушенное — цела ли точка возврата
  объём          сколько изменилось за неделю — большой прирост требует проверки
  рост           не пора ли повторить диагностику: база могла сменить класс

Зачем скрипт, а не памятка владельцу. Напоминание, которое должен помнить
человек, — не механизм: оно провалит тот же тест цены, что провалило правило
о поиске перед выводом. Проверка стоит две секунды и выполняется тем, кто и
так открывает эти файлы в начале работы.
"""

import datetime
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb_dates import parse_dates as _parse, last_date as _last, infer_order

STALE_ENTRY_DAYS = 7        # вход старше — снимок протух
REVIEW_DAYS = 30            # журнал и вопросы: давно не разбирали
DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")

CANDIDATES = {
    "entry": ["NOW.md", "STATUS.md"],
    "journal": ["SLOMALOS.md"],
    "questions": ["QUESTIONS.md", "docs/QUESTIONS.md"],
}


def find(root, names):
    for n in names:
        p = os.path.join(root, n)
        if os.path.isfile(p):
            return p
    return None


ORDER = None


def dates_in(text, past_only=False, today=None):
    """Даты из текста в любом из принятых форматов (см. kb_dates.py).
    past_only отсекает будущие: в журнале и в наборе вопросов встречаются
    сроки и плановые даты, и без фильтра «последняя запись» уезжает в
    будущее — счётчик показывает отрицательные дни."""
    dates, _ = _parse(text, past_only=past_only, today=today, day_first=ORDER)
    return dates


def dates_or_unknown(text, today=None):
    """(последняя прошедшая дата, было ли нераспознанное).

    Различие несущее: «дат нет» и «даты есть, но формат не распознан» —
    разные утверждения, и второе не даёт права сказать «ни разу»."""
    return _last(text, today=today, day_first=ORDER)


def collect_all(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in
                       {"node_modules", "__pycache__", "venv", ".venv"}]
        out.extend(os.path.join(dirpath, f) for f in filenames if not f.startswith("."))
    return out


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def section(text, *titles):
    """Кусок файла от заголовка с одним из titles до следующего заголовка."""
    lines = text.splitlines()
    grab, out = False, []
    for ln in lines:
        if ln.startswith("#"):
            up = ln.upper()
            grab = any(t.upper() in up for t in titles)
            continue
        if grab:
            out.append(ln)
    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2

    today = datetime.date.today()
    due = []
    ok = []

    # конвенция дат определяется один раз по всей базе
    global ORDER
    ORDER = infer_order(read(f) for f in collect_all(root)[:400]
                        if os.path.splitext(f)[1].lower() in {".md", ".txt", ".yml", ".yaml"})

    # 1. Вход
    p = find(root, CANDIDATES["entry"])
    if p:
        head = "\n".join(read(p).splitlines()[:5])
        ds, head_unknown = _parse(head, past_only=True, today=today, day_first=ORDER)
        if ds:
            age = (today - max(ds)).days
            line = f"вход ({os.path.basename(p)}) обновлён {age} дн. назад"
            (due if age > STALE_ENTRY_DAYS else ok).append(
                line + (" — снимок протух, обнови" if age > STALE_ENTRY_DAYS else "")
            )
        elif head_unknown:
            ok.append(f"вход ({os.path.basename(p)}): дата есть, но формат не распознан")
        else:
            due.append(f"вход ({os.path.basename(p)}) без строки «Обновлено» — не видно, протух ли")
    else:
        ok.append("NOW.md/STATUS.md нет — если вход в этом проекте собирается иначе "
                  "(запрос, панель, генератор), это не отступление: контракт требует "
                  "инвариант, а не файл. Тогда опиши его в правилах проекта")

    # 2. Ожидания с прошедшей датой
    if p:
        wait = section(read(p), "ЧЕГО ЖДЁМ", "ЖДЁМ", "WAITING")
        overdue = [d for d in dates_in(wait) if d < today]
        if overdue:
            due.append(f"ожиданий с прошедшей датой: {len(overdue)}, самое старое {min(overdue)} — проверь, не сорвано ли")

    # 3. Журнал
    p = find(root, CANDIDATES["journal"])
    if p:
        last, unknown = dates_or_unknown(read(p), today=today)
        ds = [last] if last else []
        if ds:
            age = (today - max(ds)).days
            line = f"журнал ({os.path.basename(p)}) — последняя запись {age} дн. назад"
            (due if age > REVIEW_DAYS else ok).append(
                line + (" — пора разбирать" if age > REVIEW_DAYS else "")
            )
        elif unknown:
            ok.append("журнал: даты есть, но формат не распознан — судить о давности не берусь")
        else:
            ok.append("журнал пуст — это «не наблюдали», а не «не работает»")
    else:
        due.append("журнала эксплуатации нет — разбирать будет нечего, "
                   "и повтор проблемы никто не заметит")

    # 4. Контрольные вопросы
    p = find(root, CANDIDATES["questions"])
    if p:
        last, unknown = dates_or_unknown(read(p), today=today)
        ds = [last] if last else []
        if ds:
            age = (today - max(ds)).days
            line = f"контрольные вопросы — последний прогон {age} дн. назад"
            (due if age > REVIEW_DAYS else ok).append(
                line + (" — пора прогнать с чистого контекста" if age > REVIEW_DAYS else "")
            )
        elif unknown:
            ok.append("контрольные вопросы: даты есть, но формат не распознан — "
                      "о давности прогона не сужу")
        else:
            due.append("контрольные вопросы ни разу не прогонялись — база не проверена ни разу")
    else:
        due.append("файла контрольных вопросов нет — приёмочной проверки у базы нет")

    # 5. Git: незакоммиченное и незапушенное
    if os.path.isdir(os.path.join(root, ".git")):
        def git(*args):
            try:
                return subprocess.run(["git", "-C", root, *args], capture_output=True,
                                      text=True, timeout=15).stdout.strip()
            except Exception:
                return ""
        dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]
        if dirty:
            due.append(f"незакоммиченных изменений: {len(dirty)} — точка возврата не полна")
        ahead = git("rev-list", "--count", "@{u}..HEAD")
        if ahead.isdigit() and int(ahead) > 0:
            due.append(f"коммитов не запушено: {ahead} — для второй линии и для завтра этого не существует")
        elif not ahead and not dirty:
            ok.append("git: дерево чистое, удалённого репозитория не видно — проверь, есть ли он")
        if not dirty and ahead == "0":
            ok.append("git: всё закоммичено и запушено")

        # объём изменений за неделю: время не единственный повод для проверки.
        # После большой сессии база могла обрасти быстрее, чем протухнуть.
        recent = git("log", "--since=7.days", "--pretty=%H")
        n_commits = len([x for x in recent.splitlines() if x.strip()])
        changed = git("log", "--since=7.days", "--name-only", "--pretty=format:")
        n_files = len({x.strip() for x in changed.splitlines() if x.strip()})
        if n_files >= 25 or n_commits >= 15:
            due.append(f"за неделю изменено файлов: {n_files} в {n_commits} коммитах — "
                       f"объём большой, прогони проверку целостности (kb_check.py)")
        elif n_files:
            ok.append(f"за неделю изменено файлов: {n_files} в {n_commits} коммитах")

    # 6. Рост базы против базовой линии диагностики
    rules = find(root, ["CLAUDE.md", "AGENTS.md", "ПРАВИЛА.md"])
    if rules:
        rtext = read(rules)
        m = re.search(r"диагностика проведена\s*:\s*(\S+)[^\n]*?файлов\s*:\s*(\d+)", rtext, re.I)
        total = len([f for f in collect_all(root)])
        if m:
            base = int(m.group(2))
            if base and (total >= base * 2 or total - base >= 50):
                due.append(f"база выросла: было {base} файлов на момент диагностики, стало {total} — "
                           f"повтори диагностику (00-kak-chitat.md §0), могли появиться новые классы")
            else:
                ok.append(f"файлов: {total} (на момент диагностики {base})")
        else:
            ok.append(f"файлов: {total}; базовая линия не записана — после диагностики впиши "
                      f"в правила строку «диагностика проведена: <дата>, файлов: {total}»")
    else:
        ok.append("git-репозитория нет — восстановить базу после потери будет нечем")

    if due:
        print("ПОРА:")
        for x in due:
            print(f"  • {x}")
        print()
    if ok:
        print("в порядке:")
        for x in ok:
            print(f"  · {x}")
    if not due:
        print("\nничего не просрочено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
