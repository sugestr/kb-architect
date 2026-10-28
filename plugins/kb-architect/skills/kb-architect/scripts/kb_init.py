#!/usr/bin/env python3
"""kb_init.py — разворачивание минимума kb-architect (v3).

Создаёт то, что требует контракт, и ничего сверх. Расширенный набор — по флагу --extended.
Существующие файлы не перезаписывает — безопасен в непустой папке.

Использование:
    python3 kb_init.py <путь> [--areas "20:Клиенты" "30:Продукт"]
        [--knowledge-dir kb] [--sources] [--documents] [--output]
        [--decisions] [--archive] [--inbox]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kb_lock  # noqa: E402,F401  (UTF-8 вывод на Windows)
except ImportError:  # частичная копия скилла: без настройки вывода, но не падать
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "assets", "templates"))

# Правила и единый NOW.md, его адрес, канал плохих новостей, журнал и проверка.
CORE = {
    "CORRECTIONS.md": "CORRECTIONS.md",
    "SLOMALOS.md": "SLOMALOS.md",
    "QUESTIONS.md": "QUESTIONS.md",
    "CLAUDE.md": "CLAUDE.md",
    "NOW.md": "NOW.md",
    "KNOWLEDGE_INDEX.json": "knowledge-index.json",
}

# Сверх минимума — только по флагам, из справочника.
EXTRA = {
    "INDEX.md": "INDEX.md",
    "CHANGELOG.md": "CHANGELOG.md",
}

OPTIONAL_DIRS = {
    "sources": "первичные источники, читать по предметному маршруту и границам доступа",
    "documents": "оригиналы: сканы, PDF, фото",
    "output": "производимое наружу",
    "decisions": "решения, неизменяемые",
    "archive": "неактивное",
    "_inbox": "транзит, должен быть пуст",
}


def copy_template(name: str, dest: str, created: list, skipped: list) -> None:
    src = os.path.join(TEMPLATES, {**CORE, **EXTRA}[name])
    if os.path.lexists(dest):
        skipped.append(os.path.basename(dest))
        return
    shutil.copyfile(src, dest)
    text = open(dest, encoding="utf-8").read().replace("YYYY-MM-DD", dt.date.today().isoformat())
    if name == "KNOWLEDGE_INDEX.json":
        # Domain examples are not real files in a new project. Declare only
        # the current route whose source this initializer actually creates.
        data = json.loads(text)
        data["routes"] = [route for route in data["routes"]
                          if route["id"] == data["current"]]
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    open(dest, "w", encoding="utf-8").write(text)
    created.append(os.path.basename(dest))


def main() -> int:
    ap = argparse.ArgumentParser(description="Развернуть каркас kb-architect")
    ap.add_argument("root")
    ap.add_argument("--areas", nargs="*", default=[], help='пары "NN:Название"')
    ap.add_argument("--knowledge-dir", default="knowledge",
                    help="имя папки знания в этом проекте (по умолчанию knowledge)")
    ap.add_argument("--extended", action="store_true",
                    help="добавить INDEX/CHANGELOG из справочника")
    ap.add_argument("--force", action="store_true",
                    help="разрешить дописывать в уже существующие файлы проекта")
    for d in OPTIONAL_DIRS:
        ap.add_argument(f"--{d.lstrip('_')}", action="store_true", dest=d.lstrip("_"))
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    kdir = args.knowledge_dir
    destination = os.path.realpath(os.path.join(root, kdir))
    if (os.path.isabs(kdir) or destination == os.path.realpath(root)
            or os.path.commonpath([os.path.realpath(root), destination]) != os.path.realpath(root)):
        ap.error("--knowledge-dir must be a directory inside the project")
    if not os.path.lexists(os.path.join(root, "NOW.md")) and any(
            os.path.lexists(os.path.join(root, name)) for name in
            ("CLAUDE.md", "AGENTS.md", "PROJECT_RULES.md", "KNOWLEDGE_INDEX.json",
             "STATUS.md", "CURRENT.md")):
        print("CURRENT_ADOPTION_REQUIRED: existing project has no root NOW.md; "
              "use adopt-existing/migration to preserve its current state. No files changed.")
        return 1
    os.makedirs(root, exist_ok=True)

    created, skipped = [], []
    names = list(CORE) + (list(EXTRA) if args.extended else [])
    for name in names:
        copy_template(name, os.path.join(root, name), created, skipped)

    # Two runtime names, one physical canon. Do not create an independently
    # editable copy: that would reintroduce the split-brain this default removes.
    agents = os.path.join(root, "AGENTS.md")
    if os.path.lexists(agents):
        skipped.append("AGENTS.md")
    else:
        os.symlink("CLAUDE.md", agents)
        created.append("AGENTS.md -> CLAUDE.md")

    os.makedirs(os.path.join(root, kdir), exist_ok=True)
    created.append(f"{kdir}/")

    if kdir != "knowledge" and "CLAUDE.md" in created:
        rules = os.path.join(root, "CLAUDE.md")
        with open(rules, "a", encoding="utf-8") as stream:
            stream.write(f"\nЗнания проекта: [{kdir}/]({kdir}/).\n")

    for d in OPTIONAL_DIRS:
        if getattr(args, d.lstrip("_"), False):
            os.makedirs(os.path.join(root, d), exist_ok=True)
            if d == "_inbox":
                open(os.path.join(root, d, ".gitkeep"), "a").close()
            created.append(f"{d}/")

    if args.areas:
        lines = ["", "## План областей", ""]
        for a in args.areas:
            num, _, title = a.partition(":")
            lines.append(f"- `{num.strip()}` — {title.strip() or 'без названия'}")
        lines.append("")
        # План областей дописывается в карту, если карта в этом проекте есть
        # (её разворачивает --extended). Без карты он идёт в файл правил:
        # заводить ради него отдельный файл вне контракта — значит молча
        # добавить проекту сущность, которой он не просил.
        target = "INDEX.md" if os.path.exists(os.path.join(root, "INDEX.md")) else "CLAUDE.md"
        tpath = os.path.join(root, target)
        existed = os.path.exists(tpath)
        # Дописывать в чужой существующий файл без спроса — это правило 4
        # контракта, нарушенное собственным скриптом: файл только что был
        # объявлен «пропущен, уже есть», и в него же дописывался раздел.
        # Воспроизведено внешней критикой на реальном каталоге.
        if existed and target in skipped and not args.force:
            print(f"\nОСТАНОВЛЕНО: план областей должен дописаться в существующий {target},")
            print( "а он только что объявлен пропущенным. Молча дописывать в чужой файл нельзя.")
            print( "Вот что было бы добавлено:\n")
            print("\n".join("    " + l for l in lines if l))
            print(f"\nСогласен — повтори с `--force`. Не согласен — добавь руками туда, где место.")
            created.append("план областей → НЕ записан, нужен --force")
        else:
            with open(tpath, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
            created.append(f"план областей → {target}")

    # 8.3.3: новый проект рождается на номере установленного выпуска и с финализированной
    # квитанцией — перехода не было, подтверждать владельцу нечего; до этого hook не видел
    # новый проект (заглушка вместо номера), а kb_apply требовал приёмку перехода, которого нет
    # (зависимый скилл 27.10). Проверить: `kb_apply.py <root>` → PROJECT_VERSION_OK после первого коммита.
    try:
        import kb_paths
        version = kb_paths.skill_version()
    except Exception:
        version = None
    rules_path = os.path.join(root, "CLAUDE.md")
    if version and "CLAUDE.md" in created:
        with open(rules_path, encoding="utf-8") as f:
            text = f.read()
        stamped = re.sub(r"^kb_standard_version:.*$", f"kb_standard_version: {version}", text, count=1,
                         flags=re.MULTILINE)
        if stamped != text:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(stamped)
            created.append(f"kb_standard_version: {version}")
    receipt = os.path.join(root, "KB_RELEASE_APPLICATION.json")
    if version and not os.path.lexists(receipt):
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with open(receipt, "w", encoding="utf-8") as f:
            json.dump({"schema": 3, "application": {
                "from_version": None, "to_version": version, "status": "finalized",
                "source": {"commit": None, "version_source": "CLAUDE.md"},
                "owner": {"accepted_by": "kb_init: новый проект, перехода нет", "accepted_at": now},
                "finalized_at": now, "open": []}}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        created.append("KB_RELEASE_APPLICATION.json")
    print("Создано: " + ", ".join(created))
    if skipped:
        print("Пропущено (уже есть): " + ", ".join(skipped))
    print(
        "\nДальше:\n"
        "  1. Заполни NOW.md — где мы, что дальше, чего ждём, что не знаем.\n"
        "  2. Впиши в QUESTIONS.md пять вопросов проекта, один из них злой.\n"
        "  3. Заполни остальной CLAUDE.md: язык, вход в сессию, границы, блок «Соответствие» (номер выпуска уже стоит).\n"
        "  4. git init + приватный remote + первый коммит.\n"
        "\nСверх минимума ничего не заводи, пока в SLOMALOS.md не появится повтор."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
