#!/usr/bin/env python3
"""
test_kb.py — приёмочный контур скриптов. Запускается без зависимостей:

    python3 test_kb.py

Зачем он есть. Тысяча строк проверяющего кода соврала четыре раза подряд,
и каждый раз починка добавляла эвристику — то есть расширяла поверхность
следующей лжи. Внешняя критика назвала это прямо: у стандарта с приёмочной
метрикой «не соврать уверенно» не было ни одного теста. Пока их нет, любое
«починено» — заявление, а не факт.

Каждый тест ниже — **воспроизведение конкретного контрпримера**, а не
выдумка. Источник указан в имени. Тест, который нельзя привязать к
наблюдению, сюда не добавляется: иначе набор растёт быстрее, чем ловит.

Правило при провале: сначала решить, что верно — код или ожидание, — и
записать решение. Тест, поправленный под поведение кода, перестаёт быть
тестом.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FAILED = []
PASSED = []


def run(script, root):
    p = subprocess.run([sys.executable, os.path.join(HERE, script), root],
                       capture_output=True, text=True, timeout=120)
    return p.stdout + p.stderr


def base(files):
    d = tempfile.mkdtemp(prefix="kbtest-")
    for name, text in files.items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return d


def check(name, cond, out, hint=""):
    (PASSED if cond else FAILED).append((name, out, hint))
    print(("  ок   " if cond else "  ПРОВАЛ ") + name)
    if not cond and hint:
        print("       ожидалось: " + hint)


NOW_OK = "Обновлено: 2026-08-06\n\n## ГДЕ МЫ\nтекст\n"


def t_declared_entry_missing():
    """Критика 5.6: объявлен путь входа, которого нет, а настоящий вход рядом.
    Опечатка в объявлении не должна отключать единственную численную проверку."""
    d = base({"NOW.md": "Обновлено: 2026-08-06\n\n## ГДЕ МЫ\n" + "х" * 9000,
              "CLAUDE.md": "# правила\n\n## Соответствие kb-architect\n\nвход: missing/NOW.md\n"})
    out = run("kb_check.py", d)
    check("объявленный вход не существует → не «чисто»",
          "чисто" not in out, out,
          "находка о том, что объявление указывает в пустоту")
    shutil.rmtree(d, ignore_errors=True)


def t_declared_entry_and_second_file():
    """Критика 5.6: объявление вызывает ранний возврат, и второй вход не ищется."""
    d = base({"NOW.md": NOW_OK, "STATUS.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nвход: NOW.md\n"})
    out = run("kb_check.py", d)
    check("объявлен вход, рядом второй кандидат → дубль найден",
          "НЕСКОЛЬКИХ МЕСТАХ" in out, out,
          "«ВХОД НАЙДЕН В НЕСКОЛЬКИХ МЕСТАХ»: инвариант входа ровно один")
    shutil.rmtree(d, ignore_errors=True)


def t_stale_entry_with_foreign_date():
    """Критика 5.6: посторонняя свежая дата в шапке маскирует протухший вход."""
    d = base({"NOW.md": "Обновлено: 2020-01-01\nисточник: выгрузка от 2026-08-06\n\n## ГДЕ МЫ\nтекст\n"})
    out = run("kb_due.py", d)
    m = re.search(r"вход \(NOW\.md\) обновлён (\d+) дн", out)
    check("протухший вход не молодеет от чужой даты рядом",
          bool(m) and int(m.group(1)) > 365, out,
          "возраст берётся из строки «Обновлено», а не из максимума дат шапки")
    shutil.rmtree(d, ignore_errors=True)


def t_questions_never_run():
    """Критика 5.6: «прогонов не было» плюс любая дата → «последний прогон 0 дн.»."""
    d = base({"NOW.md": NOW_OK,
              "QUESTIONS.md": "# вопросы\n\nПрогонов не было.\n\n| 1 | что решили | ответ на 2026-08-06 |\n"})
    out = run("kb_due.py", d)
    check("«прогонов не было» не читается как прогон",
          "последний прогон" not in out, out,
          "либо молчание, либо явное «прогон не зафиксирован»")
    shutil.rmtree(d, ignore_errors=True)


def t_waiting_two_dates_one_row():
    """Критика 5.6: одна строка ожидания с двумя датами считается как два."""
    d = base({"NOW.md": "Обновлено: 2026-08-06\n\n## ЧЕГО ЖДЁМ\n"
                        "| Что | От кого | С какого числа | Если не будет |\n"
                        "|---|---|---|---|\n"
                        "| справка | контрагент | 2026-08-01 | напомнить 2026-07-01 |\n"})
    out = run("kb_due.py", d)
    m = re.search(r"ожиданий: (\d+)", out)
    check("одна строка ожидания считается за одно",
          bool(m) and int(m.group(1)) == 1, out,
          "ожиданий: 1 — счёт по строкам таблицы, а не по датам")
    shutil.rmtree(d, ignore_errors=True)


def t_git_enclosing_repo():
    """Критика 5.6: проверяется только <root>/.git, охватывающий репозиторий не виден."""
    d = base({"NOW.md": NOW_OK})
    subprocess.run(["git", "init", "-q", d], capture_output=True)
    sub = os.path.join(d, "podpapka")
    os.makedirs(sub, exist_ok=True)
    with open(os.path.join(sub, "NOW.md"), "w", encoding="utf-8") as f:
        f.write(NOW_OK)
    out = run("kb_due.py", sub)
    check("подпапка внутри git не объявляется «без репозитория»",
          "git-репозитория нет" not in out, out,
          "поиск .git вверх по дереву, а не только в корне")
    shutil.rmtree(d, ignore_errors=True)


def t_verify_lookalike():
    """Отчёт из эксплуатации: `verified` вместо `verify` проходил как чисто."""
    d = base({"NOW.md": NOW_OK,
              "letter.md": "---\nstatus: sent\nverified: 2026-08-06\n---\n\nписьмо\n"})
    out = run("kb_check.py", d)
    check("подменённое имя поля ловится",
          "ПОЧТИ ПРАВИЛЬНО" in out, out, "находка про `verified:` вместо `verify:`")
    shutil.rmtree(d, ignore_errors=True)


def t_mirror_vocabulary_not_flagged():
    """Критика Fable: `verified_at` предписан паттерну зеркал справочником."""
    d = base({"NOW.md": NOW_OK,
              "zerkalo.md": "---\ntype: mirror\nverified_at: 2026-08-06\n---\n\nконспект\n"})
    out = run("kb_check.py", d)
    check("словарь зеркал не считается подменой",
          "ПОЧТИ ПРАВИЛЬНО" not in out, out, "verified_at у зеркала — норма")
    shutil.rmtree(d, ignore_errors=True)


def t_entry_in_subfolder():
    """Отчёт «Медицина»: вход в подпапке — потолок молча не проверялся."""
    d = base({"claude/STATUS.md": "Обновлено: 2026-08-06\n\n## ГДЕ МЫ\n" + "х" * 9000})
    out = run("kb_check.py", d)
    check("вход в подпапке найден и измерен",
          "ПЕРЕРОС ПОТОЛОК" in out, out, "потолок проверен на claude/STATUS.md")
    shutil.rmtree(d, ignore_errors=True)


def t_no_entry_is_a_finding():
    """3.18: промах поиска входа должен быть находкой, а не молчанием."""
    d = base({"prosto.md": "текст\n"})
    out = run("kb_check.py", d)
    check("вход не найден → находка, а не «чисто»",
          "НЕ ПРОВЕРЕН" in out and "чисто" not in out, out,
          "«ПОТОЛОК ВХОДА НЕ ПРОВЕРЕН»")
    shutil.rmtree(d, ignore_errors=True)


def t_scope_line_always_present():
    """3.18: отчёт всегда называет объём проверенного."""
    d = base({"NOW.md": NOW_OK})
    out = run("kb_check.py", d)
    check("отчёт называет объём проверенного",
          "Проверено:" in out, out, "строка «Проверено: …»")
    shutil.rmtree(d, ignore_errors=True)


def main():
    print(__doc__.strip().splitlines()[0])
    print()
    for fn in sorted(
            (v for k, v in globals().items() if k.startswith("t_")),
            key=lambda f: f.__name__):
        fn()
    print()
    print(f"пройдено {len(PASSED)}, провалено {len(FAILED)}")
    if FAILED:
        print()
        print("Провалы — это не повод править тест. Сначала реши, что верно:")
        print("код или ожидание, — и запиши решение там, где принимал.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
