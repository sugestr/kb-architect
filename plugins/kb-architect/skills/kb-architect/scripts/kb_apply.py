#!/usr/bin/env python3
"""
kb_apply.py — что новая редакция значит для ЭТОЙ базы.

    python3 kb_apply.py <корень базы>

Скрипт **ничего не применяет**. Он собирает разбор и заканчивается вопросом
владельцу. Установить новый код и привести базу в соответствие — разные
действия; второе меняет соглашения проекта, а это правило 4: показать, что
меняется, получить «да», потом делать.

Код 1 означает `NEEDS_APPLICATION` либо `APPLICATION_UNPROVEN`: проект отстаёт
или его marker не подтверждён полным release ledger. Это не crash, а машинно
заметное незавершённое применение. Для редакций 6.0+ код 0 возможен только при
валидной `KB_RELEASE_APPLICATION.json`, а не по одному номеру в правилах.

Зачем отдельная команда. `kb_due.py` умеет сказать «проект записан на 4.0,
установлен 4.5 — посмотри таблицу выпусков». Это верно и бесполезно:
таблица выпусков — семьдесят килобайт, и владелец не должен её читать,
чтобы узнать, касается ли его хоть одна строка. Здесь строки между двумя
редакциями достаются сами, и рядом с каждой — признак: есть ли в этой
базе то, чего она касается.

Признаки грубые и помечены как грубые. Они отвечают «возможно, касается»,
а не «касается»; ошибка в сторону лишнего внимания здесь дешевле, чем
пропуск. Точный ответ даёт прогон проверок после применения.
"""

import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_paths

ROW = re.compile(r"^\|\s*(\d+(?:\.\d+)+)\s*\|\s*(.+?)\s*\|\s*[^|]*\|\s*$", re.MULTILINE)
# Метка «что обязан сделать проект». Ставится только у выпусков, менявших
# обязанности проекта.
ACT = re.compile(r"⟦Д:\s*(.+?)⟧", re.DOTALL)
# Метка новой опциональной возможности. Она не становится обязанностью оттого,
# что приехала со скиллом, но должна быть видна владельцу: 4.19 добавил работу
# Claude + Codex, а старый kb_apply.py напечатал «дел нет», поэтому ни один
# проект не узнал о способности. Молчание смешало «действий нет» и «решение не
# принято» — тот же fail-open, ради которого существует весь скрипт.
CHOICE = re.compile(r"⟦В:\s*(.+?)⟧", re.DOTALL)
APPLICATION_RECEIPT = "KB_RELEASE_APPLICATION.json"
RECEIPT_REQUIRED_FROM = (6, 0)
APPLICATION_DECISIONS = {
    "applied", "deferred", "declined", "not-applicable", "tool-inherited",
}
VERSION_MARKER = re.compile(
    r"^[ \t]*(?:[-*>+][ \t]*)?[`*_\"']{0,2}[ \t]*"
    r"kb_standard_version[`*_\"']{0,2}[ \t]*:[ \t]*([^\n]+)$",
    re.IGNORECASE | re.MULTILINE,
)


def ver_key(v):
    return tuple(int(x) for x in v.split("."))


def releases_between(low, high):
    """Строки таблицы выпусков в (low, high] — по возрастанию."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     os.pardir, "references", "releases.md")
    rows = []
    for v, text in ROW.findall(kb_paths.read(p)):
        try:
            if ver_key(low) < ver_key(v) <= ver_key(high):
                rows.append((v, text))
        except ValueError:
            continue
    return sorted(rows, key=lambda r: ver_key(r[0]))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args, binary=False):
    return subprocess.run(
        ["git", "-C", root, *args], capture_output=True,
        text=not binary, timeout=30)


def marker_from_bytes(data):
    match = VERSION_MARKER.search(data.decode("utf-8", errors="replace"))
    if not match:
        return None
    return match.group(1).strip().strip("`*_ ").strip()


def _evidence_errors(root, value, label):
    if not isinstance(value, list) or not value:
        return [f"{label} has no evidence"]
    errors = []
    for index, item in enumerate(value):
        item_label = f"{label}.evidence[{index}]"
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{item_label} is not a project-relative path")
            continue
        normalized = item.replace("\\", "/")
        if os.path.isabs(item) or ".." in normalized.split("/"):
            errors.append(f"{item_label} leaves project root")
            continue
        path = os.path.join(root, item)
        if not os.path.isfile(path):
            errors.append(f"{item_label} is missing")
        elif git(root, "ls-files", "--error-unmatch", item).returncode:
            errors.append(f"{item_label} is not Git-tracked")
    return errors


def application_receipt_errors(root, marker):
    """Prove that a v6+ marker came from a complete, reviewable migration.

    The receipt does not decide project duties.  It makes the already-made
    decisions, immutable source snapshot and post-results owner acceptance
    mechanically visible so changing the marker cannot erase its own preconditions.
    """
    path = os.path.join(root, APPLICATION_RECEIPT)
    if not os.path.isfile(path):
        return [f"missing {APPLICATION_RECEIPT}"]
    tracked = git(root, "ls-files", "--error-unmatch", APPLICATION_RECEIPT)
    if tracked.returncode:
        return [f"{APPLICATION_RECEIPT} is not Git-tracked"]
    try:
        data = json.loads(kb_paths.read(path))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{APPLICATION_RECEIPT} is unreadable: {exc}"]
    applications = data.get("applications")
    if data.get("schema") != 1 or not isinstance(applications, list) or not applications:
        return [f"{APPLICATION_RECEIPT} requires schema 1 and applications array"]

    errors = []
    previous_to = None
    for index, application in enumerate(applications):
        label = f"application[{index}]"
        if not isinstance(application, dict):
            errors.append(f"{label} is not an object")
            continue
        kind = application.get("kind", "migration")
        from_version = application.get("from_version")
        to_version = application.get("to_version")
        try:
            if kind not in {"migration", "initial-adoption"}:
                raise ValueError
            if not isinstance(to_version, str):
                raise ValueError
            if kind == "migration" and (not isinstance(from_version, str)
                                        or ver_key(from_version) >= ver_key(to_version)):
                errors.append(f"{label} version range is not increasing")
            if kind == "initial-adoption" and (index != 0 or from_version is not None):
                errors.append(f"{label} initial-adoption must be first with null from_version")
        except ValueError:
            errors.append(f"{label} has invalid kind/from_version/to_version")
            continue
        if previous_to is not None and from_version != previous_to:
            errors.append(f"{label} does not continue previous to_version {previous_to}")
        previous_to = to_version
        if application.get("status") != "finalized":
            errors.append(f"{label} is not finalized")

        snapshot = application.get("source_snapshot")
        if not isinstance(snapshot, dict):
            errors.append(f"{label} has no source_snapshot")
        else:
            commit = snapshot.get("commit")
            ref = snapshot.get("ref")
            source = snapshot.get("version_source")
            expected_sha = snapshot.get("version_source_sha256")
            if not all(isinstance(value, str) and value for value in
                       (commit, ref, source, expected_sha)):
                errors.append(f"{label} source_snapshot is incomplete")
            elif os.path.isabs(source) or ".." in source.replace("\\", "/").split("/"):
                errors.append(f"{label} version_source leaves project root")
            else:
                commit_probe = git(root, "rev-parse", "--verify", commit + "^{commit}")
                ref_probe = git(root, "rev-parse", "--verify", ref + "^{commit}")
                ancestor = git(root, "merge-base", "--is-ancestor", commit, "HEAD")
                if commit_probe.returncode:
                    errors.append(f"{label} source commit is unavailable")
                elif ref_probe.returncode or ref_probe.stdout.strip() != commit_probe.stdout.strip():
                    errors.append(f"{label} source ref does not resolve to source commit")
                elif ancestor.returncode:
                    errors.append(f"{label} source commit is not an ancestor of HEAD")
                else:
                    shown = git(root, "show", f"{commit}:{source}", binary=True)
                    if shown.returncode:
                        errors.append(f"{label} version_source is absent at source commit")
                    else:
                        if sha256(shown.stdout) != expected_sha:
                            errors.append(f"{label} version_source hash does not match snapshot")
                        source_marker = marker_from_bytes(shown.stdout)
                        if kind == "migration" and source_marker != from_version:
                            errors.append(f"{label} source marker does not match from_version")
                        if kind == "initial-adoption" and source_marker is not None:
                            errors.append(f"{label} initial source unexpectedly has a marker")

        ledger = application.get("release_ledger")
        known_to = any(version == to_version for version, _ in
                       releases_between("0", to_version))
        if not known_to:
            errors.append(f"{label} to_version is absent from release history")
        expected_versions = ([to_version] if kind == "initial-adoption" else
                             [version for version, _ in
                              releases_between(from_version, to_version)])
        observed_versions = []
        if not isinstance(ledger, list):
            errors.append(f"{label} has no release_ledger array")
        else:
            for row_index, row in enumerate(ledger):
                row_label = f"{label}.release_ledger[{row_index}]"
                if not isinstance(row, dict):
                    errors.append(f"{row_label} is not an object")
                    continue
                version = row.get("version")
                observed_versions.append(version)
                if row.get("decision") not in APPLICATION_DECISIONS:
                    errors.append(f"{row_label} has unsupported decision")
                errors.extend(_evidence_errors(root, row.get("evidence"), row_label))
            if observed_versions != expected_versions:
                errors.append(
                    f"{label} release ledger must be exact {expected_versions}, "
                    f"got {observed_versions}")

        acceptance = application.get("owner_acceptance")
        if not isinstance(acceptance, dict) or not acceptance.get("accepted_by") \
                or not acceptance.get("accepted_at"):
            errors.append(f"{label} lacks post-results owner acceptance evidence")
        else:
            errors.extend(_evidence_errors(
                root, acceptance.get("evidence"), f"{label}.owner_acceptance"))
        if not application.get("finalized_at"):
            errors.append(f"{label} lacks finalized_at")

    if previous_to != marker:
        errors.append(f"receipt ends at {previous_to}, project marker is {marker}")
    return errors


def base_traits(root):
    """Грубые признаки базы: что в ней есть такого, чего касаются правки."""
    t = {}
    entry = kb_paths.locate(root, "entry")
    journal = kb_paths.locate(root, "journal")
    corr = kb_paths.locate(root, "corrections")
    quest = kb_paths.locate(root, "questions")

    t["вход"] = entry.found or bool(entry.declared)
    t["вход не в корне"] = bool(entry.path) and os.path.dirname(
        os.path.abspath(entry.path)) != os.path.abspath(root)
    t["журнал разделом"] = journal.found and journal.path is None
    t["журнал"] = journal.found
    t["канал правок"] = corr.found
    t["многострочные записи канала"] = corr.found and any(
        not ln.lstrip().startswith(("- ", "* ", "#")) and ln.strip()
        for ln in corr.text().splitlines())
    t["контрольные вопросы"] = quest.found
    t["журнал прогонов"] = quest.found and kb_paths.section(
        quest.text(), ("ЖУРНАЛ ПРОГОНОВ", "ПРОГОНЫ")) is not None
    marker = os.path.join(root, ".git")
    t["git"] = os.path.isdir(marker) or os.path.isfile(marker)
    rules = kb_paths.rules_path(root)
    rtext = kb_paths.read(rules) if rules else ""
    t["несколько пишущих"] = bool(re.search(r"владени|несколько пишущих|две линии|"
                                            r"два агента|codex", rtext, re.IGNORECASE))
    t["зеркала"] = bool(re.search(r"зеркал|mirror", rtext, re.IGNORECASE))
    return t


# Ключевое слово в строке выпуска → признак базы, который делает её применимой.
APPLICABLE = [
    ("вход", "вход"),
    ("подпапк", "вход не в корне"),
    ("журнал", "журнал"),
    ("колонк", "журнал"),
    ("канал правок", "канал правок"),
    ("многострочн", "многострочные записи канала"),
    ("контрольны", "контрольные вопросы"),
    ("прогон", "журнал прогонов"),
    ("git", "git"),
    ("коммит", "git"),
    ("пишущ", "несколько пишущих"),
    ("зеркал", "зеркала"),
]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = os.path.abspath(sys.argv[1])
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2

    proj, raw = kb_paths.project_version(root)
    inst = kb_paths.skill_version()

    if not inst:
        print("не вижу установленной редакции — читать нечего")
        return 2
    if not proj:
        print(f"Редакция проекта не записана числом{f' (записано: «{raw}»)' if raw else ''}.")
        print(f"Установлен скилл {inst}. Впиши в «Соответствие» строку")
        print(f"«kb_standard_version: {inst}» только после release-wide ledger и приёмки —")
        print("без исходной редакции сначала надо восстановить source snapshot.")
        return 1
    if ver_key(proj) >= RECEIPT_REQUIRED_FROM:
        receipt_errors = application_receipt_errors(root, proj)
        if receipt_errors:
            print(f"APPLICATION_UNPROVEN: marker {proj} не доказывает применение выпуска.")
            for error in receipt_errors:
                print("  ERROR:", error)
            print(f"Сохрани source snapshot, полный release ledger и post-results acceptance в "
                  f"{APPLICATION_RECEIPT}; marker не повышай до finalize.")
            return 1
        print(f"APPLICATION_RECEIPT_OK: {APPLICATION_RECEIPT} доказывает marker {proj}.")
    if ver_key(proj) >= ver_key(inst):
        print(f"проект на {proj}, установлен {inst} — применять нечего")
        return 0

    rows = releases_between(proj, inst)
    traits = base_traits(root)

    dela = []
    vozmozhnosti = []
    for v, text in rows:
        for m in ACT.findall(text):
            value = " ".join(m.split())
            # Releases 4.17/4.21 name the marker syntax itself as `⟦Д: …⟧`.
            # The ellipsis is documentation, not an instruction to a project.
            if value not in {"…", "..."}:
                dela.append((v, value))
        for m in CHOICE.findall(text):
            value = " ".join(m.split())
            if value not in {"…", "..."}:
                vozmozhnosti.append((v, value))

    print(f"Проект на {proj}, установлен скилл {inst}. Между ними выпусков: {len(rows)}.\n")

    if not dela:
        print("ОБЯЗАТЕЛЬНЫХ ДЕЛ НЕТ. Правки инструментов и текста уже работают,")
        print("потому что скилл установлен.\n")
    else:
        print(f"ТРЕБУЮТ ДЕЙСТВИЯ: {len(dela)} из {len(rows)}. Остальные — правки инструментов")
        print("и текста, они уже работают и от базы ничего не требуют.\n")
        for k, (v, act) in enumerate(dela, 1):
            print(f"  {k}. [{v}] {act}\n")

    if vozmozhnosti:
        print(f"НОВЫЕ ВОЗМОЖНОСТИ НА РЕШЕНИЕ: {len(vozmozhnosti)}.")
        print("Они не применяются автоматически и не становятся обязанностью проекта.\n")
        for k, (v, choice) in enumerate(vozmozhnosti, 1):
            print(f"  {k}. [{v}] {choice}\n")
    else:
        print("НОВЫХ ВОЗМОЖНОСТЕЙ, ТРЕБУЮЩИХ РЕШЕНИЯ, НЕТ.\n")

    hits_all = sorted({t for t in traits if traits[t]})
    if hits_all:
        print(f"Что в этой базе вообще есть: {', '.join(hits_all)}.")
    print()
    print("─" * 70)
    print("Дальше по порядку:")
    print("  0. до первой проектной правки сохранить Git source snapshot и")
    print(f"     начать полный ledger в {APPLICATION_RECEIPT};")
    print("  1. сделать обязательные дела выше в обратимом shadow;")
    print("  2. по каждому выпуску и новой возможности записать: applied /")
    print("     deferred / declined / not-applicable / tool-inherited;")
    print("     для возможности отдельно сохранить решение владельца;")
    print("  3. прогнать kb_check.py и kb_due.py: они написаны новее вашей")
    print("     редакции и найдут ошибки, которые база могла накопить под старой;")
    print("  4. поправить найденное, каждую правку — записью в канал с адресом;")
    print("  5. показать ledger, hashes, PASS/FAIL/UNKNOWN и rollback владельцу;")
    print("  6. только после post-results acceptance финализировать receipt и")
    print("     обновить kb_standard_version на " + str(inst) + ".")
    print()
    print("От чего-то можно отказаться — это часть системы, а не отступление.")
    print("Но отказ записывается, иначе следующая сессия примет его за недоделку.")
    print("\nNEEDS_APPLICATION: дельта проекта не закрыта.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
