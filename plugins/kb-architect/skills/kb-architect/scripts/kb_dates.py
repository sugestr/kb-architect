"""
kb_dates.py — разбор дат в тех записях, которые встречаются в живых базах.

Общий модуль для kb_due.py и kb_check.py: формат дат — один класс знания,
и разбирать его двумя независимыми копиями означало бы нарушить первое
правило контракта внутри собственных инструментов.

**Почему это вообще понадобилось.** Первая версия понимала только
`YYYY-MM-DD`. Контракт формат дат не задаёт — он требует инвариант
(«отметка свежести сверху»), а шаблон показывает ISO именно как шаблон.
Проект, выполнивший контракт буквально и выбравший `DD/MM/YYYY`, получал
инструмент, который систематически сообщал о невыполнении выполненного:
файл с журналом прогонов выглядел как не содержащий ни одной даты.

**Главное свойство: при неразрешимой неоднозначности — молчать.**
Ошибка всегда шла в сторону «не сделано», а односторонняя ложная тревога
хуже разовой: когда постоянно горящих строк станет две-три, вывод
читается как фон, и инструмент уничтожает условие собственного
применения. Молчание дешевле: «не наблюдали» стандарт уже умеет отличать
от «не работает».
"""

import datetime
import re

ISO = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
DMY = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b")


def _safe(y, m, d):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def infer_order(texts):
    """Порядок дня и месяца по всей базе, а не по одному файлу.

    Проект использует одну конвенцию дат, но в отдельном файле может не
    оказаться ни одной однозначной записи: «02/08/2026» само по себе не
    отличить от американского порядка. Достаточно одной даты с числом
    больше двенадцати где угодно в базе, чтобы вопрос закрылся для всех
    файлов сразу. Не нашлось нигде — молчим, как и раньше.
    """
    for text in texts:
        for a, b, _ in DMY.findall(text):
            if int(a) > 12:
                return True
            if int(b) > 12:
                return False
    return None


def parse_dates(text, past_only=False, today=None, day_first=None):
    """Все даты текста. Возвращает (список дат, было_ли_нераспознанное).

    Второе значение важнее первого: оно позволяет отличить «дат нет» от
    «даты есть, но я их не понял». Утверждать «ни разу не делалось» можно
    только в первом случае.
    """
    dates, unparsed = [], False

    for y, m, d in ISO.findall(text):
        got = _safe(int(y), int(m), int(d))
        if got:
            dates.append(got)
        else:
            unparsed = True

    # порядок берётся снаружи (по всей базе), иначе выводится из этого файла
    raw = DMY.findall(text)
    if day_first is None:
        for a, b, _ in raw:
            if int(a) > 12:
                day_first = True
                break
            if int(b) > 12:
                day_first = False
                break

    for a, b, y in raw:
        ia, ib = int(a), int(b)
        if ia > 12:
            got = _safe(int(y), ib, ia)
        elif ib > 12:
            got = _safe(int(y), ia, ib)
        elif day_first is True:
            got = _safe(int(y), ib, ia)
        elif day_first is False:
            got = _safe(int(y), ia, ib)
        else:
            # 01/02/2026 в файле без единой однозначной даты — не гадаем
            unparsed = True
            continue
        if got:
            dates.append(got)
        else:
            unparsed = True

    if past_only:
        today = today or datetime.date.today()
        dates = [d for d in dates if d <= today]

    return dates, unparsed


def last_date(text, today=None, day_first=None):
    """Последняя прошедшая дата и признак нераспознанного."""
    dates, unparsed = parse_dates(text, past_only=True, today=today, day_first=day_first)
    return (max(dates) if dates else None), unparsed
