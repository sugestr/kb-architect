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


class Vyvod(str):
    """Вывод скрипта вместе с кодом возврата.

    Строка — чтобы все проверки вида «фраза in out» работали как раньше;
    код рядом — чтобы `check` мог отличить «скрипт отработал и промолчал»
    от «скрипт не запустился». Аудит 08.08 показал, зачем: при подмене
    запуска на пустую строку **восемь тестов из двадцати печатали «ок»**.
    Отрицательное условие «плохой фразы нет» выполняется и тогда, когда
    нет вообще ничего, — то есть контур, написанный против fail-open,
    сам был fail-open на сорока процентах.
    """
    def __new__(cls, text, code):
        o = super().__new__(cls, text)
        o.code = code
        return o


# Ненулевой код — не всегда поломка: kb_check.py возвращает 1, когда нашёл
# находки, и это штатный успех. Поломкой считается всё от 2 и выше — нет
# папки, исключение, не запустилось.
KOD_POLOMKI = 2


def run(script, root, path_prefix=None):
    env = dict(os.environ)
    if path_prefix:
        env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")
    p = subprocess.run([sys.executable, os.path.join(HERE, script), root],
                       capture_output=True, text=True, timeout=120, env=env)
    return Vyvod(p.stdout + p.stderr, p.returncode)


def base(files):
    d = tempfile.mkdtemp(prefix="kbtest-")
    for name, text in files.items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return d


def check(name, cond, out, hint=""):
    # Оракул сначала спрашивает, отработал ли скрипт вообще. Без этого
    # любое отрицательное условие («в выводе нет слова X») выполняется
    # на пустоте, и тест зеленеет на сломанном коде.
    kod = getattr(out, "code", 0)
    if kod is not None and kod >= KOD_POLOMKI:
        cond, hint = False, f"скрипт завершился с кодом {kod} — проверять нечего"
    elif not str(out).strip():
        cond, hint = False, "скрипт не напечатал ничего — отрицательное условие ничего не значит"
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


def t_journal_one_column():
    """Отчёт «Медицина»: журнал, перенесённый в раздел, потерял вторую колонку.
    Имя файла несёт одну половину смысла, шапка — обе; переезжает имя."""
    d = base({"NOW.md": NOW_OK,
              "SLOMALOS.md": "# журнал\n\n## СЛОМАЛОСЬ\n\n- 2026-08-06 · правило дорого\n"})
    out = run("kb_due.py", d)
    check("журнал одной колонкой → находка",
          "одной колонкой" in out, out,
          "вторая колонка обязательна, иначе разбор голосует за резку")
    shutil.rmtree(d, ignore_errors=True)


def t_journal_two_columns_silent():
    """Обе колонки на месте — молчание, а не похвала."""
    d = base({"NOW.md": NOW_OK,
              "SLOMALOS.md": "# журнал\n\n## СЛОМАЛОСЬ\n\n- 2026-08-06 · дорого\n"
                             "\n## СРАБОТАЛО\n\n- 2026-08-06 · правило поймало расхождение\n"})
    out = run("kb_due.py", d)
    check("обе колонки → тревоги нет",
          "одной колонкой" not in out, out, "молчание")
    shutil.rmtree(d, ignore_errors=True)


def t_corrections_multiline_closed():
    """Отчёт agent-config: отметка закрытия стоит на строке продолжения —
    ровно так, как выглядит формат в собственном шаблоне. Скрипт искал её
    только в первой строке записи, marked оказывался False, и ветка
    «неразобранное про вход» была недостижима в принципе."""
    d = base({"NOW.md": "Обновлено: 2026-08-01\n\n## ГДЕ МЫ\nстарое\n",
              "CORRECTIONS.md": "# канал\n\n- 2026-08-02 · `a.md` — разошлось.\n"
                                "  Источник: прогон.\n  ✔ закрыто 2026-08-02\n"
                                "- 2026-08-06 · `NOW.md` — вход утверждает старое.\n"
                                "  Источник: сверка.\n"})
    out = run("kb_due.py", d)
    check("отметка закрытия на строке продолжения видна",
          "ни одной отметки" not in out, out,
          "запись = первая строка плюс продолжения, CLOSED ищется по всему телу")
    check("неразобранное про вход поднимает тревогу",
          "про сам вход" in out, out,
          "ветка pending должна быть достижима")
    shutil.rmtree(d, ignore_errors=True)


def t_questions_run_log_only():
    """Отчёт agent-config: дата из заголовка колонки «Верный ответ (на …)»
    засчитывалась как дата прогона, а «прогон ещё не проводился» не попадало
    под шаблон отрицания."""
    d = base({"NOW.md": NOW_OK,
              "QUESTIONS.md": "# вопросы\n\n| # | Вопрос | Верный ответ (на 2026-08-02) |\n"
                              "|---|---|---|\n| 1 | сколько | 13 |\n"
                              "\n## Журнал прогонов\nпрогон ещё не проводился\n"})
    out = run("kb_due.py", d)
    check("дата эталона не засчитывается как прогон",
          "последний прогон" not in out, out,
          "дата берётся из журнала прогонов, а не откуда попало")
    shutil.rmtree(d, ignore_errors=True)


def t_source_state_says_when_it_did_not_ask():
    """Восьмой fail-open: сравнение шло с последним скачанным состоянием,
    поэтому давно не обновлявшаяся установка печатала «новее ничего нет».
    «Не спросили» обязано быть отличимо от нуля."""
    sys.path.insert(0, HERE)
    import kb_paths
    r = kb_paths.published_version()
    check("ответ об источнике различает «ноль» и «не знаю»",
          isinstance(r, tuple) and len(r) == 3 and (r[1] is not None or bool(r[2])), repr(r),
          "тройка (версия, отставание, почему неизвестно); отставание None → причина названа")


def t_branches_with_unmerged_work():
    """Отчёт проекта ВНЖ, наблюдение 5: семь веток, пять пустых, две с работой,
    невлитой сутки. Ветка с нулём уникальных коммитов внешне неотличима от ветки
    с работой — сигнала не возникает, и каждая сессия добавляет ещё одну."""
    d = base({"NOW.md": NOW_OK, "CLAUDE.md": "# правила\n\nвход: NOW.md\n"})
    g = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("add", "-A"); g("commit", "-q", "-m", "первый")
    g("branch", "pustaya")                      # без уникальных коммитов
    g("checkout", "-q", "-b", "s-rabotoy")
    open(os.path.join(d, "novoe.md"), "w").write("работа\n")
    g("add", "novoe.md"); g("commit", "-q", "-m", "работа в ветке")
    g("checkout", "-q", "main")
    out = run("kb_due.py", d)
    check("ветка с невлитой работой названа",
          "s-rabotoy" in out and "невлитой" in out, out,
          "для следующей сессии этой работы не существует")
    check("пустая ветка отделена от ветки с работой",
          "pustaya" in out and "уникального коммита" in out, out,
          "пустые — кандидаты на удаление, не тревога")
    shutil.rmtree(d, ignore_errors=True)


def t_dolya_otmetok_ne_bulevo():
    """Отчёт медицинского архива, наблюдение 2: счётчик горел неделю не падая.
    Отметка закрытия — доля, а не «есть/нет»: на живой базе 239 записей и 59
    отметок (25%). Прежний код при любой одной отметке считал все непомеченные
    неразобранными, и раздел «ПОРА» содержал строку, которая горит всегда."""
    corr = "# правки\n\n"
    for i in range(1, 9):                       # 8 записей, 2 с отметкой = 25%
        corr += "- 2026-08-0%d · `NOW.md` — запись %d\n" % (i, i)
        if i <= 2:
            corr += "  ✔ закрыто 2026-08-0%d\n" % i
        corr += "\n"
    d = base({"NOW.md": NOW_OK, "CORRECTIONS.md": corr,
              "CLAUDE.md": "# правила\n\nвход: NOW.md\n"})
    out = run("kb_due.py", d)
    check("частичная разметка не даёт тревогу, а даёт справку",
          "25%" in out and "в находки не выношу" in out, out,
          "непомеченное при частичной разметке не значит неразобранное")
    shutil.rmtree(d, ignore_errors=True)


def t_git_oshibka_ne_stanovitsya_chistym_derevom():
    """Внешний аудит 08.08, находка 3.3 и раздел 5: обёртка git глотала код
    возврата, и ошибка команды становилась пустой строкой — неотличимой от
    честного пустого stdout. Дальше пустые dirty и ahead складывались
    в «дерево чистое» под заголовком «в порядке». Полный путь от невыполненной
    проверки к уверенно неверному утверждению."""
    d = base({"NOW.md": NOW_OK, "CLAUDE.md": "# правила\n\nвход: NOW.md\n"})
    os.makedirs(os.path.join(d, ".git"), exist_ok=True)
    binx = tempfile.mkdtemp(prefix="kbtest-bin-")
    with open(os.path.join(binx, "git"), "w") as f:
        f.write("#!/bin/sh\nexit 2\n")
    os.chmod(os.path.join(binx, "git"), 0o755)
    out = run("kb_due.py", d, path_prefix=binx)
    check("отказ git не читается как «дерево чистое»",
          "дерево чистое" not in out and "НЕ ПРОВЕРЕНО" in out, out,
          "невыполненная проверка обязана называться невыполненной")
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(binx, ignore_errors=True)


def t_objavlennye_no_otsutstvuyushchie_adresa():
    """Аудит, находка 3.2: объявленный и отсутствующий журнал попадал
    в «в порядке», а объявленный и отсутствующий канал правок не давал
    ни одной строки вообще. Молчание о непроверенном неотличимо
    от проверенного."""
    d = base({"NOW.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nвход: NOW.md\nжурнал: missing/J.md\n"
                           "канал правок: missing/C.md\n"})
    out = run("kb_due.py", d)
    check("битый адрес журнала — находка, а не «в порядке»",
          "журнал объявлен по адресу" in out and "НЕ ПРОВЕРЕН" in out, out,
          "опечатка в пути отключала разбор молча")
    check("битый адрес канала правок не молчит",
          "канал правок объявлен по адресу" in out, out,
          "раньше для этого исхода не было ветки вовсе")
    shutil.rmtree(d, ignore_errors=True)


def t_ozhidaniya_pod_vlozhennym_podzagolovkom():
    """Аудит, находка 3.1: локальная section() обрывала раздел на любом
    следующем заголовке, включая вложенный. «## ЧЕГО ЖДЁМ» → «### Внешнее» —
    и все ожидания исчезали до анализа, без единой строки в отчёте."""
    d = base({"NOW.md": "Обновлено: 2026-08-08\n\n## ГДЕ МЫ\nтекст\n\n"
                        "## ЧЕГО ЖДЁМ\n\n### Внешнее\n\n"
                        "| что | от кого | с какого числа |\n|---|---|---|\n"
                        "| ответ реестра | UGE | 2026-05-01 |\n",
              "CLAUDE.md": "# правила\n\nвход: NOW.md\n"})
    out = run("kb_due.py", d)
    check("ожидания под подзаголовком не теряются",
          "ожиданий: 1" in out, out,
          "раздел читается до заголовка того же или высшего уровня")
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
