#!/usr/bin/env python3
"""
kb_check.py — целостность базы. Семь проверок, которые не шумят.

    python3 kb_check.py <корень базы>

Это не линтер. Линтер пытался проверять два десятка правил, половину из них
машинно проверить нельзя, и на живом репозитории он давал сотни ложных
срабатываний — то есть выключался на второй день. Выключенный линтер хуже
отсутствующего: на нём висит всё обещание проверяемости.

Здесь семь проверок. Каждая либо находит настоящую поломку, либо молчит.
Молчит — но не за счёт того, что не выполнилась: отчёт всегда печатает,
что именно проверено, и промах поиска входа сам становится находкой.

  1. Ссылка на файл, которого нет.  Битая ссылка внутри базы — знание,
     которое уже потеряно, просто об этом никто не знает.

  2. Истёкший valid_until.  Файл заявил срок, за который отвечает, и срок
     прошёл. Заявленно просроченный хуже просто старого: он выглядит
     дисциплинированным.

  3. Пустой verify.  Поле заведено и не заполнено — утверждение о
     совершённом действии без доказательства, выданное за факт.

  4. Runtime rules boot и current измеряются раздельно, symlink двух agent-имён
     считается один раз, inline current не считается второй раз. Сам размер не
     доказывает поломку. Красный исход появляется только против явно принятого
     проектом `project_boot_budget_bytes`. Не нашли current — отдельная находка.

  5. Неслитая ветка с содержимым вне канона.  Работа, доставленная в
     ветку и не влитая, — второй контур: рабочее дерево чисто, а знания
     в базе нет. Проверка называет ветки, их возраст и файлы, которых
     в HEAD нет ни под каким именем.

  6. Исходящее в собственном инбоксе.  Сообщение другому проекту,
     лежащее у отправителя, не доставлено, что бы ни писал его
     delivery_state: адресат сюда не смотрит.

  7. Адрес инбокса отчётов.  Принятый сервисный контур обязан назвать
     существующий каталог напрямую. Ссылка на файл, где путь якобы должен
     находиться, не является маршрутом доставки.

Чего здесь намеренно нет: проверок «файл зарегистрирован в карте», «паспорт
неполон», «размер файла знания». Они либо шумят, либо проверяют форму вместо
содержания.

Выход: 0 — чисто, 1 — есть находки. Годится для pre-commit.
"""

import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb_dates import parse_dates, infer_order
import kb_paths

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

# Проверка заявляла «пустые verify» и этим создавала впечатление, что поле
# проверено вообще. Отрицательный тест с проекта: заменить `verify` на
# `verified` — и отчёт печатает «чисто». Поле, названное почти правильно,
# не существует для проверки, но выглядит выполненным обязательством.
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
HAS_VERIFY = re.compile(r"^\s*verify\s*:", re.MULTILINE)
LOOKALIKE = re.compile(
    r"^\s*(verified|verify_at|подтверждено|proof)\s*:",
    re.MULTILINE | re.IGNORECASE)
# `verified_at` из списка изъят: справочник сам предписывает это поле
# паттерну зеркал (`authority.md` §7, «состояние сверено с внешней системой
# в момент X»). Проверка наказывала за выполнение собственной рекомендации —
# нашёл внешний критик, не эксплуатация.
STATUS = re.compile(r"^\s*status\s*:\s*([^\s#]+)", re.MULTILINE | re.IGNORECASE)

# Наследие: профиль зеркал изъят в 4.16, но файлы с `type: mirror` могли
# остаться в старых базах. Их словарь распознаётся по-прежнему — снятая
# способность не должна превращаться в поток ложных находок у тех, кто
# ею успел воспользоваться. Здесь `verified_against` и `verified_at` значат
# сверяли с внешней системой», а не «чем доказано совершённое действие». Своя
# же проверка нашла это в собственном шаблоне — признак, что список похожих
# имён надо ограничивать чужим словарём, а не расширять догадками.
MIRROR = re.compile(r"^\s*(type\s*:\s*mirror|verified_against\s*:)",
                    re.MULTILINE | re.IGNORECASE)

# Статусы совершённого действия: контракт требует verify именно здесь.
# Список короткий и закрытый — расширять его догадками значит производить шум.
ACTION_STATUS = {
    "sent", "submitted", "paid", "signed", "filed", "delivered", "executed",
    "отправлено", "подано", "оплачено", "подписано", "сдано", "исполнено",
}


MSG_FIELD = {
    "type": re.compile(r"^\s*type\s*:\s*(\S+)", re.MULTILINE | re.IGNORECASE),
    "from": re.compile(r"^\s*from_project\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "to": re.compile(r"^\s*to_project\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "state": re.compile(r"^\s*delivery_state\s*:\s*(\S+)", re.MULTILINE | re.IGNORECASE),
}


def imena_proekta(root):
    """Как этот проект называет сам себя: каталог и slug удалённого репозитория."""
    imena = {os.path.basename(os.path.abspath(root)).lower()}
    git_root = kb_paths.find_git(root)
    if git_root:
        url, _ = kb_paths.git_out(git_root, "remote", "get-url", "origin", timeout=10)
        if url:
            hvost = url.strip().rstrip("/").rsplit("/", 1)[-1]
            imena.add(hvost[:-4].lower() if hvost.endswith(".git") else hvost.lower())
    return {i for i in imena if i}


def nash(znachenie, imena):
    z = (znachenie or "").strip().strip("`*_\"' ").lower()
    return any(i and i in z for i in imena)


def inbox_dir(root):
    """Каталог входящих: объявленный строкой либо по известным именам."""
    dec, _ = kb_paths.declared_value(root, ("инбокс входящих", "inbox входящих",
                                            "incoming inbox"))
    if dec:
        path = os.path.join(root, dec.strip().strip("`*_\"' ").lstrip("/"))
        if os.path.isdir(path):
            return path
    for name in ("_inbox", "inbox", "входящие"):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            return path
    return None


def report_inbox_state(root):
    """Проверяемый адрес отчётов: прямой существующий каталог или находка.

    Косвенный указатель намеренно не разыменовывается. Иначе декларация
    становится обещанием, что в другом файле когда-нибудь найдётся ещё одна
    декларация, а отправитель всё равно не получает точного target.
    """
    keys = ("инбокс отчётов", "report inbox", "defect report inbox")
    raw, source = kb_paths.declared_value(root, keys)
    route, route_source = kb_paths.declared_value(
        root, ("маршрут отчётов", "report route", "defect report route"))
    service, _ = kb_paths.declared_value(
        root, ("сервисный контур kb-architect", "kb-architect service layer"))
    accepted = bool(service and service.strip().lower() in
                    {"принят", "accepted", "enabled", "включён", "включен"})

    normalized_route = route.strip().lower() if route else None
    if normalized_route in {"github", "github-issue", "remote",
                            "удалённый", "удаленный"}:
        return None, None, "GitHub issue (remote)"
    if normalized_route and normalized_route not in {
            "local", "local-inbox", "локальный", "локальный инбокс"}:
        where = os.path.relpath(route_source, root) if route_source else "правила проекта"
        return None, (f"{where}: неизвестный маршрут отчётов «{route}»; "
                      "нужен local-inbox или github-issue"), None

    if not raw:
        if accepted:
            return None, ("сервисный контур принят, но маршрут отчётов не закрыт: "
                          "объяви `маршрут отчётов: github-issue` либо local-inbox "
                          "и прямой адрес `инбокс отчётов: …`"), None
        return None, None, "неприменимо (не объявлен)"

    value = os.path.expanduser(raw.strip().strip("`*_\"' "))
    path = value if os.path.isabs(value) else os.path.join(root, value)
    path = os.path.normpath(path)
    where = os.path.relpath(source, root) if source else "правила проекта"
    shown = path if os.path.isabs(value) else value
    if os.path.isdir(path):
        return path, None, shown
    if os.path.exists(path):
        return None, (f"{where}: «{raw}» указывает на файл, а нужен каталог "
                      "доставки"), None
    return None, (f"{where}: «{raw}» не является существующим каталогом; "
                  "укажи прямой абсолютный или repo-relative путь"), None


def skl(n, one, few, many):
    """Число со словом. Отчёт читают люди, «1 файлов» стоит доверия."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        word = one
    elif 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}"


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
    wrong_name, no_verify = [], []
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
            # ссылка, уводящая за пределы базы, внутренней не является:
            # так пишут относительные ссылки на разделы хостинга
            # (`../../releases`, `../../issues`), и файлом они не станут
            if not any(p == root or p.startswith(root + os.sep)
                       for p in (near, from_root)):
                continue
            if not os.path.exists(near) and not os.path.exists(from_root):
                broken.append((rel, clean))

        # 2. истёкший срок годности
        for val in VALID_UNTIL.findall(raw):
            got, _ = parse_dates(val, day_first=ORDER)
            for d in got:
                if d < today:
                    expired.append((rel, d, (today - d).days))

        # 3. verify: пустой, подменённый именем, отсутствующий при статусе действия
        for val in VERIFY.findall(raw):
            if val.strip().strip("<>").lower() in EMPTY_VERIFY:
                blank.append(rel)

        fm = FRONTMATTER.match(raw)
        if fm and not MIRROR.search(fm.group(1)):
            head = fm.group(1)
            has_verify = bool(HAS_VERIFY.search(head))
            look = LOOKALIKE.search(head)
            if look and not has_verify:
                wrong_name.append((rel, look.group(1)))
            st = STATUS.search(head)
            # префикс, а не точное совпадение: живой проект написал
            # `status: sent-duplicate`, и точное сравнение прошло бы мимо
            val = st.group(1).strip().strip('"\'').lower() if st else ""
            if val and any(val.split("-")[0] == a or val == a for a in ACTION_STATUS) \
                    and not has_verify and not look:
                no_verify.append((rel, val))

    # 4. Объём project bootstrap — измерение, а не универсальный приговор.
    #
    # Раньше вход искался двумя именами и только в корне. Проект, у которого
    # вход лежит в подпапке, получал пропуск проверки, неотличимый от
    # пройденной проверки: печаталось «чисто». Поиск теперь общий
    # (kb_paths.py), но чинит случай не он, а строка «CURRENT НЕ ПРОВЕРЕН»
    # ниже: она превращает промах поиска из молчания в находку.
    entry = kb_paths.locate(root, "entry")
    rules = kb_paths.rules_files(root)
    rules_sizes = []
    for path in rules:
        try:
            rules_sizes.append(
                (path, os.path.relpath(path, root), os.path.getsize(path)))
        except OSError:
            pass
    unchecked, entry_note = None, None
    size = entry.size()
    if size is None:
        if entry.broken:
            unchecked = (f"в правилах объявлен путь «{entry.broken}», которого нет. "
                         f"Опечатка в объявлении отключает проверку так же тихо, как "
                         f"её отсутствие"
                         + (f"; при этом рядом лежит {os.path.relpath(entry.others[0], root)}"
                            if entry.others else ""))
        elif entry.declared:
            entry_note = (f"байтовое измерение current не применяется: вход объявлен "
                          f"вычисляемым — «{entry.declared}»")
        else:
            unchecked = kb_paths.how_to_declare("entry")

    # Один опциональный бюджет относится к дедуплицированным статическим байтам,
    # которые новая сессия получает автоматически. Его отсутствие не является
    # отступлением: размер — proxy стоимости, а не доказательство достаточности.
    budget_raw, budget_source = kb_paths.declared_value(
        root, ("project_boot_budget_bytes",))
    budget, budget_error = None, None
    if budget_raw:
        if re.fullmatch(r"[1-9][0-9]*", budget_raw):
            budget = int(budget_raw)
        else:
            where = os.path.relpath(budget_source, root) if budget_source else "правила проекта"
            budget_error = (f"{where}: project_boot_budget_bytes должен быть целым "
                            f"положительным числом байт, получено «{budget_raw}»")

    entry_identity = None
    if entry.path:
        entry_identity = os.path.realpath(entry.path)
    elif entry.container:
        entry_identity = os.path.realpath(entry.container)

    bootstrap = None
    if rules_sizes:
        totals = []
        for path, _name, rule_size in rules_sizes:
            already_loaded = entry_identity == os.path.realpath(path)
            totals.append(rule_size + (0 if already_loaded or size is None else size))
        bootstrap = max(totals)
    elif size is not None:
        bootstrap = size

    budget_exceeded = bool(budget is not None and bootstrap is not None
                           and bootstrap > budget)

    # 5. Работа, доставленная в ветку, но не влитая в канон.
    #
    # Отчёт проекта 18.08: облачная сессия сделала коммит и push 14.08,
    # ветка осталась неслитой, и 29 файлов доказательств — включая реестр
    # требований и полис — четыре дня отсутствовали в каноне. Сессия, искавшая
    # полис, честно ответила «в базе нет» и разобрала его заново. Ни одна
    # проверка этого не видела: рабочее дерево чисто, вход не противоречит себе.
    #
    # Считается по именам файлов, а не только по путям: переезд каталога
    # выдаёт переименование за потерю всего содержимого. Первый счёт того же
    # случая назвал 27 потерянных путей, из которых потерян был один файл.
    # 6. Исходящее, лежащее в собственном инбоксе.
    #
    # Инбокс — входящий лоток. Сообщение, адресованное другому проекту и
    # оставленное здесь, доставленным не становится: адресат туда не смотрит,
    # а отправитель уже отчитался. Случай 18.08 — лаборатория написала
    # задание проекту в свой же inbox и сказала «передано»; правило
    # prepared/delivered существовало и было нарушено, потому что записать
    # себе стоит нисколько, а доставить — надо знать чужой путь.
    svoi = imena_proekta(root)
    inbox = inbox_dir(root)
    chuzhie, nedostavleno = [], []
    if inbox:
        for dirpath, dirnames, filenames in os.walk(inbox):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in sorted(filenames):
                if not fn.lower().endswith(".md"):
                    continue
                full = os.path.join(dirpath, fn)
                fm = FRONTMATTER.match(kb_paths.read(full))
                if not fm:
                    continue        # документ владельца шапки не обязан иметь
                head = fm.group(1)
                tip = MSG_FIELD["type"].search(head)
                if not tip or "agent-message" not in tip.group(1).lower():
                    continue
                rel = os.path.relpath(full, root)
                ot = MSG_FIELD["from"].search(head)
                komu = MSG_FIELD["to"].search(head)
                state = MSG_FIELD["state"].search(head)
                if ot and nash(ot.group(1), svoi):
                    nedostavleno.append((rel, (komu.group(1).strip() if komu else "не назван"),
                                         state.group(1).strip() if state else "не назван"))
                elif komu and not nash(komu.group(1), svoi):
                    chuzhie.append((rel, komu.group(1).strip()))

    vetki, vetki_why = kb_paths.unmerged_refs(root)
    poterya = [v for v in vetki if v.lost]
    lishnie = [v for v in vetki if not v.lost]
    report_inbox, report_inbox_error, report_inbox_note = report_inbox_state(root)

    found = 0

    if nedostavleno:
        found += len(nedostavleno)
        print(f"ИСХОДЯЩЕЕ В СОБСТВЕННОМ ИНБОКСЕ — {skl(len(nedostavleno), 'сообщение', 'сообщения', 'сообщений')}:")
        for rel, komu, state in nedostavleno[:10]:
            print(f"  {rel} → адресат {komu}, delivery_state: {state}")
        print("  Инбокс — входящий лоток. Своё сообщение здесь не доставлено,")
        print("  каким бы ни был delivery_state: адресат сюда не смотрит.")
        print("  Доставка — файл в инбоксе адресата, его коммит или квитанция")
        print("  с тем же message_id. До этого состояние — prepared.\n")

    if chuzhie:
        found += len(chuzhie)
        print(f"В ИНБОКСЕ СООБЩЕНИЯ НЕ ЭТОМУ ПРОЕКТУ — {skl(len(chuzhie), 'файл', 'файла', 'файлов')}:")
        for rel, komu in chuzhie[:10]:
            print(f"  {rel} → адресовано: {komu}")
        print("  Либо доставлено не туда, либо проект сменил имя. В обоих случаях")
        print("  адресат этого не видел.\n")

    if report_inbox_error:
        found += 1
        print("ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН — нет прямого каталога доставки.")
        print(f"  {report_inbox_error}.")
        print("  Указатель на inventory или runtime-конфиг не заменяет адрес:")
        print("  отправитель должен получить проверяемый target без второго поиска.\n")

    if vetki_why and vetki_why != "репозитория нет":
        found += 1
        print("НЕСЛИТЫЕ ВЕТКИ НЕ ПРОВЕРЕНЫ — git не ответил.")
        print(f"  {vetki_why}.")
        print("  Это не «веток нет»: невыполненная проверка выглядит здесь так же,")
        print("  как пройденная.\n")

    if poterya:
        found += len(poterya)
        print(f"НЕ СЛИТО В КАНОН — {skl(len(poterya), 'ветка', 'ветки', 'веток')} "
              f"с содержимым, которого нет в HEAD:")
        for v in poterya:
            hvost = (f", {skl(len(v.both_sides), 'файл изменён', 'файла изменены', 'файлов изменены')}"
                     " с обеих сторон" if v.both_sides else "")
            print(f"  {v.name} — последний коммит {v.last}, "
                  f"{skl(v.lost, 'файл', 'файла', 'файлов')} вне канона "
                  f"(по путям {len(v.outside_path)}){hvost}")
            for p in v.outside_name[:5]:
                print(f"      {p}")
            if v.lost > 5:
                print(f"      … и ещё {v.lost - 5}")
        print("  Ветка живёт слиянием или явным отказом. Пока она просто есть,")
        print("  работа доставлена во второй контур, и поиск по базе честно врёт")
        print("  «этого нет». Файлы, изменённые с обеих сторон, механически не")
        print("  сливаются: версия ветки старше и воскресит уже исправленное.\n")

    if lishnie:
        print(f"НЕ СЛИТЫ, НО СОДЕРЖИМОЕ УЖЕ В КАНОНЕ — {len(lishnie)}: "
              + ", ".join(v.name for v in lishnie[:6])
              + (" …" if len(lishnie) > 6 else ""))
        print("  Это не находка, а хвост: закрой явным отказом с записью, иначе")
        print("  следующая проверка снова потратит на них внимание.\n")

    if unchecked:
        found += 1
        print("CURRENT НЕ ПРОВЕРЕН — вход не найден по известным путям.")
        print(f"  {unchecked}.")
        print("  Это не «всё в порядке»: проверка, которая не выполнилась, дороже")
        print("  отсутствующей — отсутствующую компенсируют вниманием, а на")
        print("  выполненную полагаются.\n")

    if entry.others:
        found += len(entry.others)
        print(f"ВХОД НАЙДЕН В НЕСКОЛЬКИХ МЕСТАХ — {1 + len(entry.others)}:")
        print(f"  {entry.where(root)}")
        for p in entry.others:
            print(f"  {os.path.relpath(p, root)}")
        print("  Инвариант входа — ровно один. Два независимо обновляемых входа")
        print("  означают, что сессия выберет из них произвольно. Оставь один,")
        print("  остальные переименуй или объяви путь строкой «вход:» в правилах.\n")

    if budget_error:
        found += 1
        print("БЮДЖЕТ BOOT ПРОЕКТА НЕ ПРОВЕРЕН — объявление некорректно.")
        print(f"  {budget_error}.\n")

    if budget_exceeded:
        found += 1
        print(f"PROJECT BOOT ПРЕВЫСИЛ ПРИНЯТЫЙ БЮДЖЕТ — {bootstrap} B > {budget} B.")
        print("  Это нарушение собственного решения проекта, а не универсального лимита.")
        print("  Не сокращай данные вслепую: сначала карта блоков и мест назначения,")
        print("  затем rollback и fresh-context проверка recall/authority/stops.\n")

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

    if wrong_name:
        found += len(wrong_name)
        print(f"ПОЛЕ НАЗВАНО ПОЧТИ ПРАВИЛЬНО — {len(wrong_name)}:")
        for rel, name in wrong_name[:20]:
            print(f"  {rel} → `{name}:` вместо `verify:`")
        if len(wrong_name) > 20:
            print(f"  … и ещё {len(wrong_name) - 20}")
        print("  Для проверки такого поля не существует, а выглядит оно выполненным")
        print("  обязательством. Имя поля — часть поля.\n")

    if no_verify:
        found += len(no_verify)
        print(f"СОВЕРШЁННОЕ ДЕЙСТВИЕ БЕЗ verify — {len(no_verify)}:")
        for rel, st in no_verify[:20]:
            print(f"  {rel} — status: {st}")
        if len(no_verify) > 20:
            print(f"  … и ещё {len(no_verify) - 20}")
        print("  Контракт требует verify именно здесь: отправлено, подано, оплачено,")
        print("  подписано. Утверждение без способа перепроверки — не факт.\n")

    # Отчёт всегда называет объём проверенного. «Чисто» без списка — это
    # утверждение шире выполненного: именно так пропуск измерения current
    # читался как пройденная проверка. И формулировка не шире сделанного:
    # «пустые verify» звучало как «verify проверен», а поле, названное
    # `verified`, проходило чистым.
    scope = ["ссылки", "сроки годности",
             "verify (пустой · подменённый именем · отсутствующий при статусе действия)"]
    if vetki_why == "репозитория нет":
        scope.append("неслитые ветки — неприменимо (репозитория нет)")
    elif vetki_why:
        scope.append("неслитые ветки — НЕ ПРОВЕРЕНО")
    else:
        scope.append(f"неслитые ветки ({len(vetki)})")
    scope.append("адресация инбокса" if inbox else "адресация инбокса — неприменимо (инбокса нет)")
    if report_inbox:
        scope.append(f"инбокс отчётов ({report_inbox_note})")
    elif report_inbox_error:
        scope.append("инбокс отчётов — НЕ ПРОВЕРЕН")
    else:
        scope.append(f"инбокс отчётов — {report_inbox_note}")
    if rules_sizes:
        values = ", ".join(f"{name}={value} B" for _path, name, value in rules_sizes)
        scope.append(f"runtime rules boot — MEASURED ({values})")
    else:
        scope.append("runtime rules boot — NOT_CHECKED (root rules file not found)")
    if entry.found:
        scope.append(f"current entry — MEASURED ({entry.where(root)}={size} B)")
    elif entry_note:
        scope.append("current entry — NOT_APPLICABLE")
    else:
        scope.append("current entry — NOT_CHECKED")
    if bootstrap is not None:
        if budget is None:
            scope.append(f"max project bootstrap — {bootstrap} B "
                         "(informational; project budget not declared)")
        else:
            state = "EXCEEDED" if budget_exceeded else "PASS"
            scope.append(f"project bootstrap budget — {state} "
                         f"({bootstrap}/{budget} B)")
    else:
        scope.append("max project bootstrap — NOT_CHECKED")

    if not found:
        print("целостность: чисто. Проверено: " + ", ".join(scope) + ".")
        if entry_note:
            print(f"  {entry_note}.")
        return 0

    print(f"итого находок: {found}. Проверено: " + ", ".join(scope) + ".")
    return 1


if __name__ == "__main__":
    sys.exit(main())
