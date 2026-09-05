#!/usr/bin/env python3
"""
kb_lookup.py — что база уже знает по этим темам.

Запускается ДО того, как сессия сформулировала вывод. На вход — список тем
из нового источника, на выход — что по каждой уже лежит в базе.

    python3 kb_lookup.py <корень> "фимоз|circuncision|circumcision" "офтальмолог|oftalmolog|retina"

Для существенного вывода из проектной базы включается fail-closed режим:

    python3 kb_lookup.py <корень> --claim "вывод" --receipt /tmp/evidence.json \
      --support "подтверждающая тема|синоним" \
      --challenge "ограничение|противоречие|синоним"

Первый запуск всегда возвращает REVIEW_REQUIRED и код 1. После чтения каждого
кандидата квитанция закрывается отдельным вызовом `--finalize`; до этого вывод
остаётся черновиком. Сам lexical lookup не доказывает истинность: предметная роль
задаёт темы и оценивает найденное, а скрипт делает пропуск и cherry-picking
видимыми.

Каждый аргумент после корня — одна тема; варианты написания через `|`.

Зачем варианты. Архив многоязычный, и документ по теме может называться
на другом языке: поиск по русскому слову не найдёт `circuncision-fimosis.md`.
Ровно так и была пропущена операция, лежавшая в базе. Выписывая тему,
выписывай её переводы и обиходные синонимы — это часть запроса, а не
украшение.

Зачем скрипт, а не правило. Правило «прежде чем писать „вопрос открыт“ —
поищи в базе» было записано и нарушено через час: проверка стоит дороже,
чем её пропуск, и конкурирует с желанием сообщить находку. Скрипт снимает
конкуренцию — его вывод уже перед глазами к моменту, когда вывод только
формулируется.

Вывод годится для цитирования: строка «НЕ НАЙДЕНО» с перечнем того, что
именно искали, — это след выполненного запроса, а не самоотчёт о
добросовестности.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_paths

TEXT_EXT = {".md", ".txt", ".json", ".yml", ".yaml", ".csv", ".tsv", ".py", ".org", ".rst"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".obsidian"}
MAX_FILES_SHOWN = 8
SNIPPET = 110
RECEIPT_SCHEMA = 1
MAX_EVIDENCE_OUTPUT_BYTES = 12 * 1024


def collect(root, excluded=()):
    excluded = {os.path.realpath(path) for path in excluded}
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                path = os.path.join(dirpath, fn)
                if os.path.realpath(path) not in excluded:
                    out.append(path)
    return sorted(out)


def search(files, root, variants, errors=None):
    """Возвращает [(путь, строка-совпадение или None если совпало только имя)]."""
    pats = [re.compile(re.escape(v.strip()), re.IGNORECASE) for v in variants if v.strip()]
    hits = []
    for path in files:
        rel = os.path.relpath(path, root)
        name_hit = any(p.search(rel) for p in pats)
        line_hit = None
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if any(p.search(line) for p in pats):
                        line_hit = line.strip()[:SNIPPET]
                        break
        except OSError as exc:
            if errors is not None:
                errors.append(f"{rel}: {exc}")
            continue
        if name_hit or line_hit:
            hits.append((rel, line_hit))
    return hits


def search_refs(root, refs, variants, errors=None):
    """Совпадения в неслитых ветках: [(ветка, файл, строка или None)].

    Рабочее дерево — не весь репозиторий. Отчёт 18.08: полис лежал в ветке,
    не влитой четыре дня, поиск ответил «в базе нет», и документ выкачали и
    разобрали заново. Вывод «этого нет» обязан покрывать и то, что доставлено,
    но не слито, — иначе он говорит о рабочем дереве, а звучит про базу.
    """
    git_root = kb_paths.find_git(root)
    if not git_root:
        return []
    errors = errors if errors is not None else []
    prefix = os.path.relpath(os.path.realpath(root), git_root)
    prefix = "" if prefix == "." else prefix.replace(os.sep, "/") + "/"
    pathspec = ["--", ":(literal)" + prefix.rstrip("/")] if prefix else []
    hits = []
    blobs = {}
    for ref in refs:
        tree, why = kb_paths.git_out(git_root, "ls-tree", "-r", "-z", ref, *pathspec)
        if why:
            errors.append(f"{ref}: {why}")
            continue
        names = []
        for item in tree.split("\0"):
            meta, _, path = item.partition("\t")
            parts = meta.split()
            if len(parts) == 3:
                blobs[(ref, path)] = parts[2]
                names.append(path)
        for v in variants:
            v = v.strip()
            if not v:
                continue
            out, why = kb_paths.git_out(git_root, "grep", "-F", "-I", "-i", "-n", "-z",
                                        "-e", v, ref, *pathspec, ok_codes=(0, 1))
            if why:
                errors.append(f"{ref}: {why}")
            for line in (out or "").split("\n"):
                if not line:
                    continue
                location, separator, rest = line.partition("\0")
                if not separator or not location.startswith(ref + ":"):
                    errors.append(f"{ref}: unreadable grep record; coverage incomplete")
                    continue
                number, _, snippet = rest.partition("\0")
                hits.append((ref, location[len(ref) + 1:], snippet.strip()[:SNIPPET]))
            for path in names:
                if path and re.search(re.escape(v), path, re.IGNORECASE):
                    hits.append((ref, path, None))
    # один файл — одна строка, первая находка
    seen, out, local_blobs = set(), [], {}
    for ref, path, line in hits:
        if (ref, path) in seen:
            continue
        seen.add((ref, path))
        local = os.path.join(git_root, path)
        if os.path.isfile(local):
            if path not in local_blobs:
                value, why = kb_paths.git_out(git_root, "hash-object", "--no-filters", "--", local)
                local_blobs[path] = value.strip() if value else None
                if why:
                    errors.append(f"{path}: {why}")
            if local_blobs[path] == blobs.get((ref, path)):
                continue
        out.append((ref, path[len(prefix):], line))
    return out


def parser():
    p = argparse.ArgumentParser(
        description="Ищет темы в KB; evidence mode оставляет fail-closed receipt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""evidence workflow:
  --claim TEXT --receipt FILE --support TOPIC --challenge TOPIC starts review.
  --page FILE --offset N reads more; --review FILE records a batch with --reason.
  --finalize FILE --outcome supported|qualified|unknown closes review.
  Use --supports/--limits/--irrelevant; one document can support AND limit.
  Unreviewed evidence or changed corpus forbids a positive outcome.
  Role assesses truth; this tool records lexical coverage, not semantic proof.""")
    p.add_argument("root", help="корень проектной базы")
    p.add_argument("topics", nargs="*", help="темы обычного lookup, варианты через |")
    p.add_argument("--claim", help="существенный project-derived вывод")
    p.add_argument("--receipt", help="куда записать evidence receipt")
    p.add_argument("--support", action="append", default=[],
                   help="тема подтверждений; можно повторять")
    p.add_argument("--challenge", action="append", default=[],
                   help="тема ограничений/противоречий; можно повторять")
    p.add_argument("--finalize", help="закрыть ранее созданный receipt")
    p.add_argument("--review", help="сохранить оценку партии")
    p.add_argument("--page", help="страница receipt")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--outcome", choices=("supported", "qualified", "unknown"))
    p.add_argument("--supports", action="append", default=[], metavar="ID",
                   help="прочитанный кандидат, поддерживающий вывод")
    p.add_argument("--limits", action="append", default=[], metavar="ID",
                   help="прочитанный кандидат, ограничивающий вывод")
    p.add_argument("--irrelevant", action="append", default=[], metavar="ID",
                   help="прочитанный, но нерелевантный кандидат")
    p.add_argument("--reason", help="почему выбран этот outcome")
    return p


def write_json(path, data):
    destination = os.path.abspath(path)
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".kb-evidence-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, destination)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def repository_scope(root, excluded=()):
    files = collect(root, excluded=excluded)
    vetki, vetki_why = kb_paths.unmerged_refs(root)
    refs = [v.name for v in vetki]
    if refs:
        gde = f"{len(files)} текстовых файлов + неслитых веток: {len(refs)}"
    elif vetki_why:
        gde = f"{len(files)} текстовых файлов; неслитые ветки не проверены — {vetki_why}"
    else:
        gde = f"{len(files)} текстовых файлов; неслитых веток нет"
    return files, refs, vetki_why, gde


def scope_fingerprint(files, root, refs, refs_why):
    """Bind the receipt to the exact local corpus and unmerged branch tips."""
    digest = hashlib.sha256()
    errors = []
    for path in files:
        rel = os.path.relpath(path, root)
        digest.update(f"file\0{rel}\0".encode("utf-8"))
        try:
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
        digest.update(b"\0")
    git_root = kb_paths.find_git(root)
    ref_tips = {}
    for ref in refs:
        tip, why = kb_paths.git_out(git_root, "rev-parse", "--verify",
                                    f"{ref}^{{commit}}")
        if tip is None:
            errors.append(f"{ref}: {why}")
            continue
        ref_tips[ref] = tip.strip()
        digest.update(f"ref\0{ref}\0{tip.strip()}\0".encode("utf-8"))
    digest.update(f"refs-status\0{refs_why or ''}\0".encode("utf-8"))
    return digest.hexdigest(), errors, ref_tips


def evidence_candidates(files, root, refs, groups):
    """Один путь — один кандидат с перечислением запросов, которые его нашли."""
    found = {}
    order = []
    searches = []
    errors = []
    for role, query in groups:
        variants = query.split("|")
        ids = []
        local = [(None, path, line) for path, line in search(files, root, variants, errors)]
        branch = search_refs(root, refs, variants, errors) if refs else []
        for ref, path, line in local + branch:
            key = (ref or "", path)
            if key not in found:
                candidate_id = f"c{len(order) + 1}"
                found[key] = {
                    "id": candidate_id,
                    "path": path,
                    "ref": ref,
                    "snippet": line,
                    "found_by": [],
                }
                order.append(key)
            candidate = found[key]
            label = f"{role}:{query}"
            if label not in candidate["found_by"]:
                candidate["found_by"].append(label)
            ids.append(candidate["id"])
        searches.append({
            "role": role,
            "query": query,
            "variants": [v.strip() for v in variants if v.strip()],
            "candidate_ids": list(dict.fromkeys(ids)),
        })
    return [found[key] for key in order], searches, sorted(set(errors))


def candidate_output(candidates):
    lines = []
    for item in candidates:
        location = f"{item['ref']}: {item['path']}" if item["ref"] else item["path"]
        lines.append(f"{item['id']}  {location}")
        lines.append(f"   найдено: {', '.join(item['found_by'])}")
        if item["snippet"]:
            lines.append(f"   … {item['snippet']}")
    return "\n".join(lines)


def print_page(receipt, offset=0):
    candidates = receipt["candidates"]
    if offset < 0 or offset > len(candidates):
        print("invalid offset", file=sys.stderr)
        return 2
    rendered, index = "", offset
    while index < len(candidates):
        item = candidate_output([candidates[index]]) + "\n"
        if len((rendered + item).encode("utf-8")) > MAX_EVIDENCE_OUTPUT_BYTES:
            if rendered:
                break
            item = item.encode("utf-8")[:MAX_EVIDENCE_OUTPUT_BYTES - 160].decode("utf-8", errors="ignore")
            item += "\n[display shortened; full candidate retained in receipt]\n"
        rendered += item
        index += 1
    print(rendered, end="")
    print(f"CANDIDATES={len(candidates)} SHOWN={index - offset} OFFSET={offset} "
          f"NEXT_OFFSET={index if index < len(candidates) else 'END'}")
    return 0


def begin_evidence(args, root):
    if args.topics or not args.claim or not args.receipt or not args.support or not args.challenge:
        print("evidence mode требует --claim, --receipt, хотя бы один --support и "
              "хотя бы один --challenge; positional topics здесь не используются",
              file=sys.stderr)
        return 2
    files, refs, refs_why, gde = repository_scope(root, excluded=(args.receipt,))
    fingerprint, fingerprint_errors, ref_tips = scope_fingerprint(
        files, root, refs, refs_why)
    groups = ([('support', query) for query in args.support]
              + [('challenge', query) for query in args.challenge])
    candidates, searches, search_errors = evidence_candidates(files, root, refs, groups)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "tool": "kb_lookup.py",
        "root": os.path.realpath(root),
        "claim": args.claim,
        "status": "review_required",
        "coverage": {
            "text_files": len(files),
            "unmerged_refs": refs,
            "unmerged_ref_tips": ref_tips,
            "unmerged_refs_unchecked_reason": refs_why or None,
            "content_sha256": fingerprint,
            "fingerprint_errors": fingerprint_errors,
            "search_errors": search_errors,
        },
        "searches": searches,
        "candidates": candidates,
        "output_budget": {
            "candidate_bytes": len(candidate_output(candidates).encode("utf-8")),
            "limit_bytes": MAX_EVIDENCE_OUTPUT_BYTES,
        },
        "review": None,
    }
    try:
        write_json(args.receipt, receipt)
    except OSError as exc:
        print(f"receipt не записан: {exc}", file=sys.stderr)
        return 2

    print(f"База: {root} — {gde}")
    print(f"Вывод: {args.claim}\n")
    print_page(receipt)
    if not candidates:
        print("Кандидатов не найдено; это не доказывает отсутствие или истинность вывода.")
    print("\nEVIDENCE_GATE=REVIEW_REQUIRED")
    print(f"Receipt: {os.path.abspath(args.receipt)}")
    print("Продолжение: --page FILE --offset N. Оценка партии: --review FILE. "
          "Все кандидаты сохранены; до --finalize это черновик.")
    return 1


def finalize_evidence(args, root):
    partial = bool(args.review)
    receipt_path = args.review or args.finalize
    if (args.topics or args.claim or args.receipt or args.support or args.challenge
            or (not partial and not args.outcome) or (partial and args.outcome) or not args.reason):
        print("finalize mode требует --finalize, --outcome и --reason; новый поиск "
              "создаётся отдельным вызовом", file=sys.stderr)
        return 2
    try:
        with open(receipt_path, encoding="utf-8") as f:
            receipt = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"receipt не прочитан: {exc}", file=sys.stderr)
        return 2
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("tool") != "kb_lookup.py":
        print("неподдерживаемый evidence receipt", file=sys.stderr)
        return 2
    if receipt.get("root") != os.path.realpath(root):
        print("receipt относится к другому корню базы", file=sys.stderr)
        return 2
    if receipt.get("status") == "refine_required":
        receipt["status"] = "review_required"
    if receipt.get("status") != "review_required" or receipt.get("review") is not None:
        print("receipt уже закрыт; для пересмотра создай новый поиск", file=sys.stderr)
        return 2

    files, refs, refs_why, _ = repository_scope(root, excluded=(receipt_path,))
    fingerprint, fingerprint_errors, ref_tips = scope_fingerprint(
        files, root, refs, refs_why)
    old_coverage = receipt.get("coverage", {})
    if (fingerprint != old_coverage.get("content_sha256")
            or ref_tips != old_coverage.get("unmerged_ref_tips", {})
            or fingerprint_errors != old_coverage.get("fingerprint_errors", [])):
        print("база изменилась после поиска; создай новый evidence receipt",
              file=sys.stderr)
        return 2

    candidates = {item["id"]: item for item in receipt.get("candidates", [])}
    classes = {
        "support": args.supports,
        "limit": args.limits,
        "irrelevant": args.irrelevant,
    }
    selected = [item for values in classes.values() for item in values]
    unknown_ids = sorted(set(selected) - set(candidates))
    incompatible = sorted(set(args.irrelevant) & (set(args.supports) | set(args.limits)))
    if unknown_ids or incompatible:
        if unknown_ids:
            print("неизвестные candidate id: " + ", ".join(unknown_ids), file=sys.stderr)
        if incompatible:
            print("irrelevant несовместим с support/limit: " + ", ".join(incompatible), file=sys.stderr)
        return 2

    assessments = receipt.setdefault("assessments", {})
    for candidate_id in set(selected):
        assessments[candidate_id] = {
            "classes": [key for key, values in classes.items() if candidate_id in values],
            "reason": args.reason,
        }
    if partial:
        if not selected:
            print("review requires at least one candidate", file=sys.stderr)
            return 2
        write_json(receipt_path, receipt)
        print(f"REVIEWED={len(assessments)}/{len(candidates)}; EVIDENCE_GATE=REVIEW_REQUIRED")
        return 1
    missing_ids = sorted(set(candidates) - set(assessments))
    if missing_ids and args.outcome != "unknown":
        print("не прочитаны/не классифицированы: " + ", ".join(missing_ids), file=sys.stderr)
        return 2
    supports = [key for key, value in assessments.items() if "support" in value["classes"]]
    limits = [key for key, value in assessments.items() if "limit" in value["classes"]]
    irrelevant = [key for key, value in assessments.items() if "irrelevant" in value["classes"]]
    if args.outcome == "supported" and (not supports or limits):
        print("supported требует support и запрещает непринятое ограничение", file=sys.stderr)
        return 2
    if args.outcome == "qualified" and (not supports or not limits):
        print("qualified требует и support, и limit", file=sys.stderr)
        return 2
    if args.outcome != "unknown" and not candidates:
        print("без кандидатов допустим только unknown", file=sys.stderr)
        return 2
    incomplete_git = old_coverage.get("unmerged_refs_unchecked_reason")
    if (old_coverage.get("fingerprint_errors") or old_coverage.get("search_errors")
            or (incomplete_git and incomplete_git != "репозитория нет")):
        if args.outcome != "unknown":
            print("неполный охват допускает только unknown", file=sys.stderr)
            return 2

    receipt["status"] = args.outcome
    receipt["review"] = {
        "outcome": args.outcome,
        "reason": args.reason,
        "support_ids": supports,
        "limit_ids": limits,
        "irrelevant_ids": irrelevant,
        "unreviewed_ids": missing_ids,
    }
    try:
        write_json(receipt_path, receipt)
    except OSError as exc:
        print(f"receipt не закрыт: {exc}", file=sys.stderr)
        return 2
    print(f"EVIDENCE_GATE={args.outcome.upper()}")
    print(f"Receipt: {os.path.abspath(receipt_path)}")
    if args.outcome == "unknown":
        print("Вывод остаётся UNKNOWN: не записывай его как current-state fact.")
        return 1
    return 0


def main():
    args = parser().parse_args()
    root = args.root
    if not os.path.isdir(root):
        print(f"нет такой папки: {root}")
        return 2
    if args.page:
        try:
            with open(args.page, encoding="utf-8") as stream:
                receipt = json.load(stream)
            if receipt.get("root") != os.path.realpath(root) or receipt.get("tool") != "kb_lookup.py":
                raise ValueError("receipt belongs to a different root/tool")
            print("Snapshot page; freshness is checked when recording review or finalizing.")
            return print_page(receipt, args.offset)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"invalid receipt: {exc}", file=sys.stderr)
            return 2
    if args.finalize or args.review:
        return finalize_evidence(args, root)
    if args.claim or args.receipt or args.support or args.challenge:
        return begin_evidence(args, root)
    if not args.topics:
        print(__doc__)
        return 2

    files, refs, _, gde = repository_scope(root)
    print(f"База: {root} — {gde}\n")

    found_any = False
    errors = []
    for topic in args.topics:
        variants = topic.split("|")
        hits = search(files, root, variants, errors)
        shown = " / ".join(v.strip() for v in variants)
        vne = search_refs(root, refs, variants, errors) if refs else []

        if not hits and not vne:
            print(f"── {shown}")
            print(f"   НЕ НАЙДЕНО. Искали: {shown} — в {gde}")
            print( "   Прежде чем писать «этого нет»: добавь переводы и обиходные")
            print( "   синонимы и прогони ещё раз. Один язык — это не поиск.\n")
            continue

        found_any = True
        if hits:
            print(f"── {shown} — найдено в {len(hits)} файлах:")
            for rel, line in hits[:MAX_FILES_SHOWN]:
                print(f"   {rel}")
                if line:
                    print(f"      … {line}")
            if len(hits) > MAX_FILES_SHOWN:
                print(f"   … и ещё {len(hits) - MAX_FILES_SHOWN}")
        else:
            print(f"── {shown} — в рабочем дереве нет.")

        if vne:
            print(f"   ЕСТЬ ВНЕ КАНОНА — {len(vne)} файлов в неслитых ветках:")
            for ref, path, line in vne[:MAX_FILES_SHOWN]:
                print(f"   {ref}: {path}")
                if line:
                    print(f"      … {line}")
            if len(vne) > MAX_FILES_SHOWN:
                print(f"   … и ещё {len(vne) - MAX_FILES_SHOWN}")
            print( "   Это доставлено, но не влито. Не переделывай работу заново")
            print( "   и не пиши «в базе нет»: сначала слияние или явный отказ.")
        print()

    if found_any:
        print("По темам с находками вывод «вопрос открыт» делать нельзя,")
        print("не прочитав найденное. Обрыв сюжета внутри источника означает")
        print("«не было в этом канале», а не «не было».")
    if errors:
        print("COVERAGE=UNKNOWN: " + "; ".join(sorted(set(errors))))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
