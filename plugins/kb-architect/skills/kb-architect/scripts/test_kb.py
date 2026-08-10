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
SKILL_ROOT = os.path.dirname(HERE)
FAILED = []
PASSED = []


def skill_text(relative):
    with open(os.path.join(SKILL_ROOT, relative), encoding="utf-8") as f:
        return f.read()


def t_agent_message_transport_and_no_chatter():
    """Отчёт 10.08: один смысл сообщения на трёх маршрутах, без статусной болтовни."""
    ref = skill_text("references/collaboration.md")
    tpl = skill_text("assets/templates/agent-message.md")
    out = Vyvod(ref + "\n" + tpl, 0)
    fields = ("message_id:", "from_project:", "to_project:", "response_required:")
    check("сообщение агента одинаково для файла, канала и владельца",
          all(x in tpl for x in fields)
          and "не зависит от транспорта" in ref
          and "статусные сообщения" in ref.lower(), out,
          "адресованный конверт, transport-invariant семантика и anti-chatter")


def t_parallel_writers_need_worktrees():
    """Отчёт 10.08: ветка не изолирует двух писателей в одном рабочем дереве."""
    ref = skill_text("references/collaboration.md")
    out = Vyvod(ref, 0)
    check("последовательно один checkout, параллельно отдельные worktree",
          "один канонический checkout" in ref
          and "отдельный worktree" in ref
          and "Ветка без отдельного worktree не изолирует" in ref, out,
          "явно разделены последовательная и параллельная запись")


def t_shared_project_move_is_a_two_system_gate():
    """Владелец: каталог в общем поле означает совместимость, а не только mv."""
    ref = skill_text("references/move-project.md")
    skill = skill_text("SKILL.md")
    out = Vyvod(ref + "\n" + skill, 0)
    check("перенос в общее поле требует один канон и две приёмки",
          "перенеси себя в общее поле" in skill
          and "~/Documents/Projects" in ref
          and "один канонический checkout" in ref
          and "Две независимые приёмки" in ref
          and "Само нахождение каталога" in ref
          and "временный симлинк" in ref,
          out, "не простой mv: backup, один checkout, Claude + Codex acceptance")


def t_move_preserves_app_identity_and_chat_history():
    """Два переноса 10–11.08: folder grant приняли за membership проекта."""
    ref = skill_text("references/move-project.md")
    out = Vyvod(ref, 0)
    check("перенос различает checkout, app-projects и историю чатов",
          "Доступ чата к папке не делает его участником project" in ref
          and "сохранять существующий id" in ref
          and "chat membership" in ref
          and "codex app <canonical-path>" in ref
          and "ChatGPT project ради чистоты" in ref
          and "Один самостоятельный репозиторий" in ref
          and "Вспомогательный root" in ref
          and "Backup автоматически не удалять" in ref
          and "сначала разрешает только read-only" in ref
          and "по одному проекту" in ref
          and "Владелец выбирает точные строки" in ref,
          out, "project identity сохраняется; UI cleanup не уничтожает историю")


def t_reorganization_starts_from_purpose_and_separates_path_consumers():
    """Отчёт 10.08: старая карта не задаёт будущую ось, output не равен live path."""
    ref = skill_text("references/adopt-existing.md")
    out = Vyvod(ref, 0)
    check("перестройка начинает с назначения и различает живой путь и снимок",
          "устойчивый объект и назначение проекта" in ref
          and "не готовая папочная схема" in ref
          and "активные потребители" in ref
          and "исторических снимках" in ref
          and "не считают автоматическим запретом" in ref,
          out, "purpose gate до описи; active dependency != immutable output")


def t_move_backup_is_not_a_second_canon():
    """Отчёт 10.08: слово backup было принято за второй репозиторий."""
    ref = skill_text("references/move-project.md")
    out = Vyvod(ref, 0)
    check("backup переноса различает checkout, remote, bundle и данные вне Git",
          "канонический checkout" in ref
          and "remote-recovery" in ref
          and "замороженный файл всех refs" in ref
          and "snapshot данных вне Git" in ref
          and "второй remote" in ref,
          out, "recovery layers названы и не становятся рабочими копиями")


def t_domain_skill_location_follows_scope_not_agent():
    """Отчёт 10.08: один project-local навык или одна cross-project доставка."""
    ref = skill_text("references/collaboration.md")
    out = Vyvod(ref, 0)
    check("место доменного скилла определяется областью, не агентом",
          "областью действия, а не именем агента" in ref
          and "repo-local" in ref
          and "управляемая общая установка" in ref
          and "fail-closed" in ref
          and "не копируют отдельно под Claude и Codex" in ref,
          out, "один канон навыка для проекта или нескольких проектов")


def t_update_names_optional_capabilities():
    """4.19 установился, но проекты не узнали о новой работе Claude + Codex.

    Старый kb_apply.py читал только метки обязательных дел и при переходе
    4.18 → 4.20 печатал «ДЕЛ НЕТ». Новая способность без сигнала снаружи
    неотличима от отсутствующей.
    """
    d = base({"NOW.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nkb_standard_version: 4.18\n"})
    out = run("kb_apply.py", d)
    check("обновление показывает возможности, а не только обязанности",
          "НОВЫЕ ВОЗМОЖНОСТИ НА РЕШЕНИЕ" in out
          and "[4.19]" in out
          and "Claude и Codex" in out
          and "принято / отклонено /" in out,
          out, "4.19 видна как решение проекта, даже когда обязательных дел нет")
    shutil.rmtree(d, ignore_errors=True)


def t_knowledge_roles_are_domain_neutral_and_auditable():
    """Владелец: одна модель должна годиться от медицины до философии."""
    ref = skill_text("references/knowledge-roles.md")
    adopt = skill_text("references/adopt-existing.md")
    out = Vyvod(ref + "\n" + adopt, 0)
    roles = ("источник", "наблюдение", "утверждение", "интерпретация",
             "решение", "вопрос", "производное представление")
    check("роли знания — стартовая модель и legacy-чек-лист, не онтология",
          all(role in ref for role in roles)
          and "«Человек сказал X» и «X истинно»" in ref
          and "не семь папок" in ref
          and "Аудит исторического проекта" in ref
          and "knowledge-roles.md" in adopt,
          out, "происхождение + факт/интерпретация + адаптация без схемы папок")


def t_garbage_collection_is_evidence_safe_and_recoverable():
    """Владелец: дубли и квитанции не должны бесконечно раздувать поле."""
    ref = skill_text("references/garbage-collection.md")
    deleted = skill_text("assets/templates/DELETED.md")
    out = Vyvod(ref + "\n" + deleted, 0)
    check("сборка мусора проверяет доказательства, ссылки и восстановление",
          "retention authority" in ref
          and "единственным доказательством" in ref
          and "обратный поиск ссылок" in ref
          and "Recoverable quarantine" in ref
          and "восстановить один выборочный" in ref
          and "Факт" in deleted,
          out, "не удалять квитанцию только потому, что её редко открывают")


def t_service_distribution_is_public_not_development_symlink():
    """Владелец: свежая стабильная редакция приходит из public GitHub."""
    ref = skill_text("references/service-layer.md")
    tpl = skill_text("assets/templates/CLAUDE.md")
    updater = skill_text("scripts/kb_update.py")
    out = Vyvod(ref + "\n" + tpl + "\n" + updater, 0)
    check("сервисный контур использует public и исключает lab-symlink",
          "--public --сделать" in ref
          and "GitHub public https://github.com/sugestr/kb-architect" in tpl
          and "не каналом установки" in ref
          and "PUBLIC_REPOSITORY" in updater,
          out, "public stable distribution, private development authority")


def t_templates_do_not_silently_add_obligations():
    """Аудит 4.13: справочник и копируемые шаблоны не образуют скрытое ядро."""
    rules = skill_text("assets/templates/CLAUDE.md")
    handover = skill_text("assets/templates/handover.md")
    note = skill_text("assets/templates/knowledge-note.md")
    defect = skill_text("assets/templates/defect-report.md")
    out = Vyvod(rules + handover + note + defect, 0)
    check("шаблоны выровнены с условными обязательствами контракта",
          "явно принята диагностика" in rules
          and "достаточного `verify`" in rules
          and "## STATUS" not in handover
          and "NEXT 3" not in handover
          and "# verify:" in note
          and "только по явному поручению" in defect, out,
          "нет скрытой обязательной диагностики и устаревших имён разделов")


def t_declared_absent_questions_still_a_finding():
    """Аудит 4.12: обязательный тест нельзя превратить в PASS декларацией отказа."""
    d = base({"NOW.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nконтрольные вопросы: отсутствуют\n"})
    out = run("kb_due.py", d)
    check("объявленное отсутствие вопросов не становится нормой",
          "контрольных вопросов нет" in out and "ПОРА" in out, out,
          "объявление честно, но приёмочной проверки всё равно нет")
    shutil.rmtree(d, ignore_errors=True)


def t_computed_entry_is_unknown_not_ok():
    """Аудит 4.12: допустимый вычисляемый вход без результата не проверен."""
    d = base({"CLAUDE.md": "# правила\n\nвход: вычисляется командой make status\n"})
    out = run("kb_due.py", d)
    check("вычисляемый вход без запуска не получает зелёный исход",
          "НЕ ПРОВЕРЕНА" in out and "вычисляемым" in out, out,
          "форма допустима, но свежесть требует результата")
    shutil.rmtree(d, ignore_errors=True)


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


def t_update_nazyvaet_otstavshie_kopii():
    """Владелец: «мы же прописывали автообновление». Прописывали — но оно
    делает git pull в папке скилла и потому работает только там, где эта
    папка репозиторий. Замер на живой машине: одна установка из трёх.
    kb_update.py обязан назвать остальные, а не молчать о них."""
    # Тест обязан работать и из обычной installed-копии, у которой нет .git.
    # Поэтому источник создаётся явно, а не заимствуется у окружения теста.
    d = tempfile.mkdtemp(prefix="kbtest-update-source-")
    skill = os.path.join(d, "kb-architect")
    scripts = os.path.join(skill, "scripts")
    os.makedirs(scripts)
    shutil.copy2(os.path.join(HERE, "kb_update.py"), scripts)
    shutil.copy2(os.path.join(SKILL_ROOT, "SKILL.md"), skill)
    with open(os.path.join(scripts, "test_kb.py"), "w", encoding="utf-8") as f:
        f.write("import sys\nprint('fixture ok')\nsys.exit(0)\n")
    subprocess.run(["git", "init", "-q", d], capture_output=True)
    out = subprocess.run([sys.executable, os.path.join(scripts, "kb_update.py")],
                         capture_output=True, text=True, timeout=120)
    txt = Vyvod(out.stdout + out.stderr, out.returncode)
    check("обзор установок воспроизводим вне checkout установленной копии",
          "Источник:" in txt and "уровня приложения" in txt, txt,
          "явный repo-backed fixture, а не случайный .git вокруг test_kb.py")
    shutil.rmtree(d, ignore_errors=True)


def t_update_safe_replace_keeps_backup():
    """Владелец: копию обновлять автоматически, но обратимо и с тестами."""
    home = tempfile.mkdtemp(prefix="kbtest-update-home-")
    source = base({
        "SKILL.md": "---\nname: kb-architect\nmetadata:\n  version: \"9.9\"\n---\n",
        "scripts/test_kb.py": "import sys\nprint('fixture ok')\nsys.exit(0)\n",
    })
    destination = os.path.join(home, ".codex", "skills", "kb-architect")
    os.makedirs(destination)
    with open(os.path.join(destination, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: kb-architect\nmetadata:\n  version: \"1.0\"\n---\n")
    claude_parent = os.path.join(home, ".claude", "skills")
    os.makedirs(claude_parent)
    claude_destination = os.path.join(claude_parent, "kb-architect")
    os.symlink(source, claude_destination)
    env = dict(os.environ)
    env["HOME"] = home
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_update.py"),
         "--source", source, "--do"],
        capture_output=True, text=True, timeout=180, env=env)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    backups = os.path.join(home, ".codex", "skills", ".backups")
    claude_backups = os.path.join(home, ".claude", "skills", ".backups")
    check("updater ставит через тесты и сохраняет предыдущую копию",
          "копия обновлена: 1.0 → 9.9" in out
          and "симлинк заменён управляемой копией: 9.9 → 9.9" in out
          and os.path.isdir(backups)
          and len(os.listdir(backups)) == 1
          and os.path.isdir(claude_backups)
          and len(os.listdir(claude_backups)) == 1
          and not os.path.islink(claude_destination)
          and "9.9" in open(os.path.join(destination, "SKILL.md"),
                            encoding="utf-8").read(),
          out, "staging/test/backup/replace/post-test")
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(source, ignore_errors=True)


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
