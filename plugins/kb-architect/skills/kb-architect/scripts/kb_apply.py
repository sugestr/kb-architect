#!/usr/bin/env python3
"""
kb_apply.py — что новая редакция значит для ЭТОЙ базы.

    python3 kb_apply.py <корень базы>
    python3 kb_apply.py <корень базы> --target-version 6.0.1

Скрипт **сам ничего не применяет**: он детерминированно обнаруживает дельту.
Это не делает весь workflow read-only. В action-first задаче «Обнови скилл базы
знаний» вызывающий агент после кода 1 продолжает обратимые локальные изменения по
`references/migration.md`; в явном audit/read-only режиме он только сообщает итог.
Post-results acceptance, secrets/private runtime и push остаются отдельными gates.
Migration unit is the minimum compatible project level (currently 7.0.0);
a future patch does not reopen a project already accepted there.

Код 1 означает `NEEDS_APPLICATION` либо `APPLICATION_UNPROVEN`: проект отстаёт
по минимальному уровню или его 6.0+ marker не подтверждён короткой финальной квитанцией.
Patch history не превращается в project ledger.

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

import argparse
import hashlib
import json
import os
import posixpath
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
# A release series may advance without changing the project contract.  New
# decoupled releases record the mapping explicitly; older rows keep the
# historical major.minor fallback.
LINE = re.compile(r"⟦LINE:\s*(\d+(?:\.\d+)+)\s*⟧")
MIN_PROJECT = re.compile(r"⟦MIN_PROJECT:\s*(\d+(?:\.\d+)+)\s*⟧")
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


def contract_line(v):
    """Return the minimum project level; patch builds do not create migrations."""
    parts = ver_key(v)
    if len(parts) < 2:
        raise ValueError(v)
    # From 6.3 onward the public vocabulary uses a full minimum project
    # version. Missing patch means .0; release patches never reopen migration.
    if parts[:2] >= (6, 3):
        return parts[:2] + (0,)
    return parts[:2]


def line_text(v):
    return ".".join(str(part) for part in contract_line(v))


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


def release_contract_line(version):
    """Return the minimum project level carried by one release."""
    for current, text in releases_between("0", version):
        if current != version:
            continue
        match = MIN_PROJECT.search(text) or LINE.search(text)
        return contract_line(match.group(1)) if match else contract_line(version)
    return contract_line(version)


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


def source_bytes_at_commit(root, commit, source):
    """Read the runtime source at a commit, following safe in-repo symlinks.

    Git stores a symlink as a blob containing its target.  A migration records
    the file through which the marker was actually read, so a recommended
    ``AGENTS.md -> CLAUDE.md`` canon must be verified against the target bytes,
    not against the link text.  Resolution remains inside the same commit and
    project root; absolute, escaping, looping and over-deep links fail closed.
    """
    current = source.replace("\\", "/")
    seen = set()
    for _ in range(16):
        if current in seen:
            return None, "version_source symlink loop"
        seen.add(current)
        listing = git(root, "ls-tree", "-z", commit, "--", current, binary=True)
        if listing.returncode or not listing.stdout:
            return None, "version_source is absent at source commit"
        record = listing.stdout.split(b"\0", 1)[0]
        header, separator, _name = record.partition(b"\t")
        fields = header.split()
        if not separator or len(fields) < 3:
            return None, "version_source tree record is unreadable"
        shown = git(root, "show", f"{commit}:{current}", binary=True)
        if shown.returncode:
            return None, "version_source is absent at source commit"
        if fields[0] != b"120000":
            return shown.stdout, None
        try:
            target = shown.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None, "version_source symlink target is not UTF-8"
        if not target or posixpath.isabs(target):
            return None, "version_source symlink leaves project root"
        current = posixpath.normpath(posixpath.join(posixpath.dirname(current), target))
        if current == ".." or current.startswith("../"):
            return None, "version_source symlink leaves project root"
    return None, "version_source symlink chain is too deep"


def marker_line_at_commit(root, commit, source):
    """Return the contract line visible through ``source`` at one commit."""
    data, error = source_bytes_at_commit(root, commit, source)
    if error:
        return None
    marker = marker_from_bytes(data)
    if not marker:
        return None
    try:
        return line_text(marker)
    except (AttributeError, ValueError):
        return None


def actual_transition_parent(root, source_commit, source, from_version, to_version, marker):
    """Find the actual parent on which the current project-version candidate was based.

    A session-start commit may remain an ancestor after another writer advances the
    branch.  That makes it useful provenance but no longer the exact pre-change
    rollback promised by the compact receipt.  Check the uncommitted candidate first,
    then the first-parent history after the recorded source.
    """
    head_run = git(root, "rev-parse", "HEAD")
    if head_run.returncode:
        return None, "cannot resolve candidate HEAD"
    head = head_run.stdout.strip()
    head_line = marker_line_at_commit(root, head, source)
    expected_from = line_text(from_version) if from_version is not None else None
    expected_to = line_text(to_version)
    try:
        current_line = line_text(marker)
    except (AttributeError, ValueError):
        return None, "current marker is not a project version"

    # Before commit, HEAD itself is the only honest candidate parent.
    if head_line != current_line:
        if head_line == expected_from and current_line == expected_to:
            return head, None
        return None, "working-tree marker is not based on the declared from_version"

    history = git(root, "rev-list", "--first-parent", "--reverse",
                  f"{source_commit}..HEAD")
    if history.returncode:
        return None, "cannot inspect project-version transition history"
    for candidate in history.stdout.splitlines():
        parent_run = git(root, "rev-parse", f"{candidate}^1")
        if parent_run.returncode:
            continue
        parent = parent_run.stdout.strip()
        before = marker_line_at_commit(root, parent, source)
        after = marker_line_at_commit(root, candidate, source)
        if before == expected_from and after == expected_to:
            return parent, None
    return None, "cannot locate the declared project-version transition after source commit"


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
    schema = data.get("schema")
    if schema in {2, 3}:
        application = data.get("application")
        if not isinstance(application, dict):
            return [f"{APPLICATION_RECEIPT} schema {schema} requires one application object"]
        errors = []
        # Schema 3 uses the one-version vocabulary. Schema 2 remains readable
        # so an already accepted project is not forced through a cosmetic migration.
        from_key, to_key = (("from_version", "to_version") if schema == 3
                            else ("from_line", "to_line"))
        from_version = application.get(from_key)
        to_version = application.get(to_key)
        if application.get("status") != "finalized" or not application.get("finalized_at"):
            errors.append("compact application is not finalized")
        try:
            if line_text(marker) != line_text(to_version):
                errors.append(f"compact application {to_key} does not match project version")
            if from_version is not None:
                contract_line(from_version)
        except (AttributeError, ValueError):
            errors.append(f"compact application has invalid {from_key}/{to_key}")
        source = application.get("source")
        if not isinstance(source, dict) or not source.get("commit") \
                or not source.get("version_source"):
            errors.append("compact application source needs commit and version_source")
        else:
            commit = source["commit"]
            locator = source["version_source"]
            if os.path.isabs(locator) or ".." in locator.replace("\\", "/").split("/"):
                errors.append("compact application version_source leaves project root")
            elif git(root, "rev-parse", "--verify", commit + "^{commit}").returncode:
                errors.append("compact application source commit is unavailable")
            elif git(root, "merge-base", "--is-ancestor", commit, "HEAD").returncode:
                errors.append("compact application source commit is not an ancestor of HEAD")
            else:
                shown, source_error = source_bytes_at_commit(root, commit, locator)
                if source_error:
                    errors.append(source_error)
                else:
                    old_marker = marker_from_bytes(shown)
                    if from_version is not None and (not old_marker or
                                                     line_text(old_marker) !=
                                                     line_text(from_version)):
                        errors.append("compact application source marker does not match "
                                      f"{from_key}")
                    transition_parent, transition_error = actual_transition_parent(
                        root, commit, locator, from_version, to_version, marker)
                    if transition_error:
                        errors.append(transition_error)
                    elif transition_parent != commit:
                        errors.append("compact application source commit is not the actual "
                                      f"candidate parent; expected {transition_parent}")
        owner = application.get("owner")
        if not isinstance(owner, dict) or not owner.get("accepted_by") \
                or not owner.get("accepted_at"):
            errors.append("compact application lacks owner acceptance")
        if not isinstance(application.get("open", []), list):
            errors.append("compact application open must be an array")
        return errors

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
                    shown, source_error = source_bytes_at_commit(root, commit, source)
                    if source_error:
                        errors.append(f"{label} {source_error}")
                    else:
                        if sha256(shown) != expected_sha:
                            errors.append(f"{label} version_source hash does not match snapshot")
                        source_marker = marker_from_bytes(shown)
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
    parser = argparse.ArgumentParser(
        description="Проверить применение release delta к конкретной базе")
    parser.add_argument("root", help="корень базы")
    parser.add_argument(
        "--target-version",
        help=("явная граница текущего migration cycle; более новая установленная "
              "редакция остаётся следующей дельтой и не расширяет scope"),
    )
    args = parser.parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2

    proj, raw = kb_paths.project_version(root)
    inst = kb_paths.skill_version()
    declared_line = kb_paths.skill_contract_line()

    if not inst:
        print("не вижу установленной редакции — читать нечего")
        return 2
    if not declared_line:
        print("минимальный уровень проекта отсутствует или записан некорректно — "
              "нельзя определить обязательное обновление")
        return 2
    target = args.target_version or inst
    try:
        target_key = ver_key(target)
        installed_key = ver_key(inst)
        target_line = release_contract_line(target)
        installed_line = contract_line(declared_line)
        released_line = release_contract_line(inst)
    except (AttributeError, ValueError):
        print(f"некорректная целевая редакция: {target}")
        return 2
    if released_line != installed_line:
        print(f"минимальный уровень {declared_line} расходится с release history "
              f"для build {inst} — migration state неизвестен")
        return 2
    if target_key > installed_key:
        print(f"целевая редакция {target} новее установленного скилла {inst} — "
              "эта копия не может проверить будущую версию")
        return 2
    known_targets = {version for version, _ in releases_between("0", inst)}
    known_lines = {release_contract_line(version) for version in known_targets}
    known_lines.add(installed_line)
    if target not in known_targets and target_line not in known_lines:
        print(f"целевая версия проекта {line_text(target)} отсутствует в release history "
              f"установленного скилла {inst}")
        return 2
    if not proj:
        print(f"Редакция проекта не записана числом{f' (записано: «{raw}»)' if raw else ''}.")
        print(f"Установлен скилл {inst}. Впиши в «Соответствие» строку")
        print(f"«kb_standard_version: {line_text(declared_line)}» только после короткой приёмки —")
        print("без исходной редакции сначала надо восстановить source snapshot.")
        return 1
    try:
        project_line = contract_line(proj)
    except (AttributeError, ValueError):
        print(f"некорректная редакция проекта: {proj}")
        return 2
    if project_line >= target_line:
        if project_line >= (6, 2):
            receipt_errors = application_receipt_errors(root, proj)
            if receipt_errors:
                print(f"APPLICATION_UNPROVEN: версия проекта {line_text(proj)} не имеет короткой "
                      "финальной квитанции.")
                for error in receipt_errors:
                    print("  ERROR:", error)
                return 1
            print(f"APPLICATION_RECEIPT_OK: {APPLICATION_RECEIPT} подтверждает версию проекта "
                  f"{line_text(proj)}.")
        if project_line == target_line and ver_key(proj) != target_key:
            print(f"PROJECT_VERSION_OK: проект принят на версии {line_text(proj)}; "
                  f"выпуск {target} не открывает новую миграцию.")
        elif target != inst:
            print(f"TARGET_APPLICATION_OK: версия проекта {line_text(proj)} уже покрывает "
                  f"цель {line_text(target)}.")
        else:
            print(f"версия проекта {line_text(proj)}, установлен скилл {inst} — "
                  "миграции нет")
        return 0

    # A migration applies the current minimum project level directly. Patch
    # history is tool provenance, not a to-do list every project must replay.
    target_line_name = ".".join(str(part) for part in target_line)
    rows = []
    for version, text in releases_between("0", target):
        marker = MIN_PROJECT.search(text) or LINE.search(text)
        if ((marker and contract_line(marker.group(1)) == target_line) or
                (not marker and version == target_line_name)):
            rows.append((version, text))
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

    print(f"Версия проекта {line_text(proj)}, цель {target_line_name}, "
          f"установлен скилл {inst}.\n")

    if not dela:
        print("ОБЯЗАТЕЛЬНЫХ ДЕЛ НЕТ. Правки инструментов и текста уже работают,")
        print("потому что скилл установлен.\n")
    else:
        print(f"ТРЕБУЮТ ДЕЙСТВИЯ: {len(dela)} для версии {target_line_name}.\n")
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
    print("Короткий путь:")
    print("  1. сохранить exact pre-change Git commit;")
    print("  2. применить текущий минимальный уровень, не проигрывая patch history;")
    print("  3. для ролей: один узкий project check и один обычный fresh-context вопрос;")
    print("  4. показать владельцу изменения и честные OPEN;")
    print(f"  5. после acceptance записать одну schema-3 квитанцию в {APPLICATION_RECEIPT},")
    print(f"     поставить kb_standard_version: {target_line_name}, commit и отдельно push.")
    print("Full core suite, повтор каждого runtime и mutation receipts принадлежат")
    print("выпуску скилла или специальному аудиту, а не обычной миграции проекта.")
    print("\nNEEDS_APPLICATION: дельта проекта не закрыта.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
