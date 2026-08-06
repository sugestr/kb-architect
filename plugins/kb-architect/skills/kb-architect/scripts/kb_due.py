#!/usr/bin/env python3
"""
kb_due.py — что в базе просрочено. Запускается при входе в сессию.

    python3 kb_due.py <корень базы>

Ничего не требует сверх контракта: все даты уже лежат в файлах, которые
контракт и так велит вести. Скрипт их читает и считает — владельцу не надо
помнить ни одной из них.

Смотрит:

  вход           строка «Обновлено» — не устарел ли снимок
  ожидания       раздел «ЧЕГО ЖДЁМ» — не просрочено ли что-то
  журнал         последняя запись — давно ли разбирали
  вопросы        последний прогон — давно ли проверяли базу
  git            незакоммиченное и незапушенное — цела ли точка возврата
  объём          сколько изменилось за неделю — большой прирост требует проверки
  рост           не пора ли повторить диагностику: база могла сменить класс
  редакция       по какой версии контракта живёт проект и не отстала ли она

Где искать вход, журнал и вопросы, решает kb_paths.py: файл в корне, файл
в подпапке, раздел внутри правил проекта или объявленный там путь. Не нашли
— так и сказано в «ПОРА», а не тихо пропущено: молчание при промахе
неотличимо от порядка, и именно этим оба скрипта однажды соврали.

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
import kb_paths

STALE_ENTRY_DAYS = 7        # вход старше — снимок протух
REVIEW_DAYS = 30            # журнал и вопросы: давно не разбирали
DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


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


def head_of(text, extra=5, cap=25):
    """Шапка входа: frontmatter целиком плюс несколько строк после него.

    Раньше брались первые пять строк — и проект, у которого frontmatter
    длиннее пяти строк, получал «вход без строки „Обновлено“» при
    заполненной дате. Ложная тревога того же рода, что и остальные здесь:
    инструмент судил не о базе, а о своей мерке."""
    lines = text.splitlines()
    end = 0
    if lines and lines[0].strip() == "---":
        for i, ln in enumerate(lines[1:], start=1):
            if ln.strip() in ("---", "..."):
                end = i + 1
                break
    return "\n".join(lines[:min(end + extra, cap)] if end else lines[:extra])


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
    #
    # Поиск общий с kb_check.py (kb_paths.py) и различает четыре исхода:
    # файл, раздел внутри правил, объявленный не-файл и «не найден».
    # Раньше искались два имени в корне, и проект, ведущий вход в подпапке
    # или разделом, попадал в «в порядке» — то есть отсутствие проверки
    # печаталось как её прохождение.
    entry = kb_paths.locate(root, "entry")
    if entry.found:
        where = entry.where(root)
        head = head_of(entry.text())
        ds, head_unknown = _parse(head, past_only=True, today=today, day_first=ORDER)
        if ds:
            age = (today - max(ds)).days
            line = f"вход ({where}) обновлён {age} дн. назад"
            (due if age > STALE_ENTRY_DAYS else ok).append(
                line + (" — снимок протух, обнови" if age > STALE_ENTRY_DAYS else "")
            )
        elif head_unknown:
            ok.append(f"вход ({where}): дата есть, но формат не распознан")
        else:
            due.append(f"вход ({where}) без строки «Обновлено» — не видно, протух ли")
    elif entry.declared:
        ok.append(f"вход объявлен вычисляемым — «{entry.declared}». Контракт требует "
                  f"инвариант, а не файл, так что это не отступление; но и проверить "
                  f"его свежесть и объём отсюда нечем")
    else:
        due.append("вход не найден, и в правилах не объявлен — а значит не проверены "
                   "ни свежесть, ни потолок. " + kb_paths.how_to_declare("entry"))

    # 1а. Канал правок новее входа — вход считается устаревшим.
    #
    # Наблюдение с проекта: владение входом принадлежало одной линии,
    # вторая линия отправила внешний пакет, обновила профильный узел и
    # положила предложение в канал правок — как и велено. Вход несколько
    # часов утверждал, что ничего не отправлено. Строка «Обновлено»
    # проблему не показывала: событие и старый снимок пришлись на одну
    # календарную дату.
    #
    # Правило «прочитай ещё и канал правок» здесь не годится: оно провалит
    # тот же тест цены. Признак вычисляется из файлов, которые контракт
    # и так велит вести.
    #
    # Два захода отброшены на живых базах до выпуска. Сравнение времени
    # правки файлов загорелось во всех шести сразу: канал append-only, его
    # трогают чаще входа, это норма. Счёт всех неразобранных записей — тоже
    # шум: в одной базе их 35, тревога горела бы каждый день.
    # Значимо не любое неразобранное, а неразобранное **про сам вход** — именно так выглядел
    # случай: «предложение обновить NOW» лежало в канале, а вход утверждал
    # обратное. Правило про то, чего в файлах нет, машина выводить не должна:
    # проект без отметок о разборе получает не тревогу, а объяснение.
    CLOSED = re.compile(r"✔|закрыт|closed|решено|учтено|применено", re.IGNORECASE)
    corrections = kb_paths.locate(root, "corrections")
    if corrections.found and entry.found:
        where_c = corrections.where(root)
        lines = [ln for ln in corrections.text().splitlines()
                 if ln.lstrip().startswith(("- ", "* "))]
        marked = any(CLOSED.search(ln) for ln in lines)
        entry_name = os.path.basename(entry.path) if entry.path else ""
        about_entry = re.compile(
            (re.escape(entry_name) + r"|" if entry_name else "") + r"\bвход\b|\bNOW\b|\bSTATUS\b",
            re.IGNORECASE)
        pending = [ln for ln in lines if not CLOSED.search(ln) and about_entry.search(ln)]
        if not lines:
            ok.append(f"канал правок ({where_c}) пуст")
        elif not marked:
            ok.append(f"канал правок ({where_c}): {len(lines)} записей и ни одной отметки "
                      f"о разборе — что применено, отсюда не видно. Помечай применённое "
                      f"(«✔ закрыто <дата>»), и проверка начнёт различать")
        elif pending:
            dts = [d for ln in pending for d in dates_in(ln, past_only=True, today=today)]
            when = f", самая свежая {max(dts)}" if dts else ""
            due.append(
                f"в канале правок ({where_c}) неразобранных записей про сам вход: "
                f"{len(pending)}{when}. Вход считается устаревшим, пока они не применены: "
                f"подтверждённое событие могло дойти до канала и не дойти до входа")
        else:
            ok.append(f"канал правок ({where_c}): записей про вход, ждущих применения, нет")

    # 2. Ожидания, которые ждут слишком долго.
    #
    # Здесь была встроенная вечная ложная тревога, и нашёл её внешний
    # критик, а не эксплуатация. Колонка входа называется «с какого числа»
    # — это дата НАЧАЛА ожидания, по определению прошедшая. Скрипт считал
    # всякую прошедшую дату просрочкой, и правильно заполненный по
    # собственному шаблону вход давал «ожиданий с прошедшей датой: N»
    # с первого дня. Владельцу это сообщалось как находка о его проекте.
    #
    # Прошедшая дата начала — не событие. Событие — что ждём слишком долго.
    WAITING_DAYS = 21
    if entry.found:
        wait = section(entry.text(), "ЧЕГО ЖДЁМ", "ЖДЁМ", "WAITING")
        started = dates_in(wait, past_only=True, today=today)
        if started:
            longest = min(started)
            age = (today - longest).days
            if age > WAITING_DAYS:
                due.append(f"ожиданий: {len(started)}, самое давнее ждём с {longest} — "
                           f"{age} дн. Это не просрочка, а возраст: спроси ещё раз или "
                           f"закрой ожидание, если оно уже неактуально")
            else:
                ok.append(f"ожиданий: {len(started)}, самое давнее ждём {age} дн.")

    # 3. Журнал. Может вестись отдельным файлом или разделом внутри правил
    # проекта — справочник сам предлагает второе, а скрипт знал только первое
    # и рапортовал «журнала нет» о журнале с семью записями.
    journal = kb_paths.locate(root, "journal")
    if journal.found:
        where = journal.where(root)
        last, unknown = dates_or_unknown(journal.text(), today=today)
        ds = [last] if last else []
        if ds:
            age = (today - max(ds)).days
            line = f"журнал ({where}) — последняя запись {age} дн. назад"
            (due if age > REVIEW_DAYS else ok).append(
                line + (" — пора разбирать" if age > REVIEW_DAYS else "")
            )
        elif unknown:
            ok.append("журнал: даты есть, но формат не распознан — судить о давности не берусь")
        else:
            ok.append(f"журнал ({where}) пуст — это «не наблюдали», а не «не работает»")
    elif kb_paths.declared_absent(journal.declared):
        ok.append(f"журнала нет, и это объявленное отступление: «{journal.declared}»")
    elif journal.declared:
        ok.append(f"журнал объявлен: «{journal.declared}» — но по этому адресу его нет")
    else:
        due.append("журнала эксплуатации нет — разбирать будет нечего, и повтор "
                   "проблемы никто не заметит. " + kb_paths.how_to_declare("journal"))

    # 4. Контрольные вопросы
    questions = kb_paths.locate(root, "questions")
    if questions.found:
        where = questions.where(root)
        last, unknown = dates_or_unknown(questions.text(), today=today)
        ds = [last] if last else []
        if ds:
            age = (today - max(ds)).days
            line = f"контрольные вопросы ({where}) — последний прогон {age} дн. назад"
            (due if age > REVIEW_DAYS else ok).append(
                line + (" — пора прогнать с чистого контекста" if age > REVIEW_DAYS else "")
            )
        elif unknown:
            ok.append("контрольные вопросы: даты есть, но формат не распознан — "
                      "о давности прогона не сужу")
        else:
            due.append("контрольные вопросы ни разу не прогонялись — база не проверена ни разу")
    elif kb_paths.declared_absent(questions.declared):
        ok.append(f"контрольных вопросов нет, и это объявленное отступление: "
                  f"«{questions.declared}». Приёмочной проверки у базы при этом нет")
    else:
        due.append("контрольных вопросов нет — приёмочной проверки у базы нет. "
                   + kb_paths.how_to_declare("questions"))

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
    else:
        due.append("git-репозитория нет — восстановить базу после потери будет нечем, "
                   "и историю правок никто не увидит")

    # 6. Рост базы против базовой линии диагностики
    rules = kb_paths.rules_path(root)
    total = len(collect_all(root))
    if rules:
        rtext = read(rules)
        m = re.search(r"диагностика проведена\s*:\s*(\S+)[^\n]*?файлов\s*:\s*(\d+)", rtext, re.I)
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
        due.append("файла правил проекта нет (CLAUDE.md / AGENTS.md) — сессии неоткуда "
                   "узнать соглашения, и объявить отступления тоже негде")

    # 7. По какой редакции контракта живёт проект.
    #
    # Поле kb_standard_version было объявлено способностью — «сравню версию
    # проекта с установленной» — и не имело шага, на котором данные
    # появляются: шаблон предлагал строку, но ничто не говорило её заполнить,
    # и никто не замечал незаполненную. Способность без входных данных не
    # выполняется никогда и сигнала об этом не подаёт. Проверка ниже и есть
    # тот сигнал: незаполненное поле теперь видно.
    skill_version_now = kb_paths.skill_version()
    if rules:
        proj_v, proj_raw = kb_paths.project_version(root)
        skill_v = skill_version_now
        if not proj_raw:
            due.append(f"редакция контракта не записана — сессия не знает, по какой версии "
                       f"живёт проект, а стандарт меняется. Впиши в «Соответствие» строку "
                       f"«kb_standard_version: {skill_v or '<версия из шапки SKILL.md>'}»")
        elif not proj_v:
            due.append(f"редакция контракта записана словами: «{proj_raw}» — сравнить не с чем. "
                       f"Поставь номер: «kb_standard_version: {skill_v or '<номер>'}», "
                       f"описание можно оставить рядом")
        elif skill_v and proj_v != skill_v:
            due.append(f"проект записан на редакцию {proj_v}, установлен скилл {skill_v} — "
                       f"посмотри «Выпуски скилла» в references/rationale.md, что менялось "
                       f"между ними, применимое примени и обнови строку")
        elif skill_v:
            ok.append(f"редакция контракта: {proj_v} — совпадает с установленным скиллом")
    if skill_version_now:
        # Печатается всегда, даже когда всё сходится: скилл меняется под
        # сессией молча, и «я читал этот код час назад» — не то же самое,
        # что «этот код сейчас такой». Строка в отчёте, который сессия
        # и так читает первым, стоит одно чтение файла.
        ok.append(f"установлен скилл: {skill_version_now} (сверяй с ним, а не с памятью "
                  f"о прочитанном коде — он обновляется молча)")
        # Редакций три, и они расходятся независимо: загруженная в сессию,
        # установленная на диске, исходная в репозитории скилла. Отсюда
        # видно две; про третью честнее сказать, что её не видно, чем
        # умолчать — умолчание читается как совпадение.
        skill_dir = os.path.dirname(os.path.dirname(
            os.path.realpath(kb_paths.__file__)))
        src = ""
        try:
            src = subprocess.run(["git", "-C", skill_dir, "status", "--porcelain", "."],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception:
            pass
        if src:
            due.append(f"исходник скилла правится прямо сейчас: несохранённых файлов "
                       f"{len([l for l in src.splitlines() if l.strip()])}. Установленная копия "
                       f"({skill_version_now}) и репозиторий разошлись — выводы о поведении "
                       f"скриптов делай по установленной")
        ok.append("загруженная в сессию редакция отсюда не видна: инструкции не "
                  "перечитываются на лету. Разошлась с установленной — узнать об этом "
                  "нельзя, поэтому опровергая собственное недавнее наблюдение, сначала "
                  "проверь версию")

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
