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
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

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
    fields = ("message_id:", "from_project:", "to_project:", "response_required:",
              "delivery_target:", "delivery_state:", "collector:",
              "required_roles:", "role_coverage:", "evidence_receipt:")
    check("сообщение агента одинаково для файла, канала и владельца",
          all(x in tpl for x in fields)
          and "не зависит от транспорта" in ref
          and "prepared" in ref and "delivered" in ref and "acknowledged" in ref
          and "истории source-задачи" in ref
          and "статусные сообщения" in ref.lower(), out,
          "envelope, delivery states, dedup-before-request and anti-chatter")


def t_report_only_envelope_cancels_old_write_authority():
    """11–12.08: короткий report-only follow-up почти продолжил старый write plan."""
    ref = skill_text("references/collaboration.md")
    router = skill_text("SKILL.md")
    out = Vyvod(ref + "\n" + router, 0)
    check("текущий report-only envelope отменяет старую write-authority",
          "отменяют старое разрешение на запись" in ref
          and "точные разрешённые targets" in ref
          and "старое разрешение на запись не переносится" in router,
          out, "current task scope wins before first write")


def t_620_thin_router_points_to_versioned_contract():
    """The core stays versioned without putting its full text into every turn."""
    router = skill_text("SKILL.md")
    contract = skill_text("references/contract.md")
    out = Vyvod(router + "\n" + contract, 0)
    check("тонкий entry маршрутизирует к версионируемому обязательному контракту",
          len(router.encode("utf-8")) <= 8_192
          and "references/contract.md" in router
          and "С версии 6.1 контракт снова **версионируется**" in contract
          and "role posture" in contract
          and "пустой lexical/search result не доказывает отсутствие" in contract
          and "Cost baseline — **потолок/бюджет**" in contract
          and "Project entry/current ≤8 КиБ" in contract
          and "Readiness имеет один канонический executable command" in contract
          and "CORRECTIONS.md" in contract
          and "обычный fresh-context вопрос" in contract
          and "найти существующее" in contract
          and "реальный stop/conflict" in contract,
          out, "router <=8KiB; versioned core keeps truth, roles, cost and semantic acceptance")


def t_layer_cost_is_measured_from_the_single_router():
    """23.08: raw file count drifted 12 to 18; savings lacked a reproducible measure."""
    router = skill_text("SKILL.md")
    help_run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), "--help"],
        capture_output=True, text=True, timeout=120)
    evidence_help = help_run.stdout + help_run.stderr
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_cost.py"), "--json", "--check"],
        capture_output=True, text=True, timeout=120)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    try:
        data = __import__("json").loads(p.stdout)
    except (ValueError, TypeError):
        data = {}
    routes = data.get("routes", [])
    ordinary = next(
        (x for x in routes if x.get("task", "").startswith("Обычная работа")), {})
    evidence = next(
        (x for x in routes if x.get("task", "").startswith("Сделать существенный")), {})
    measured = next(
        (x for x in routes if "стоимость слоёв" in x.get("task", "")), {})
    check("стоимость entry и routed-слоёв воспроизводима без второго route registry",
          p.returncode == 0
          and data.get("entry_bytes", 99_999) <= 8_192
          and data.get("module_limit") is None
          and data.get("baseline_version") == "6.2.1"
          and len(routes) >= 15
          and ordinary.get("extra_bytes") == 0
          and 0 < evidence.get("extra_bytes", 0) <= 2_500
          and "matching project role" in router
          and "current state" in router
          and "Не перечитывай неизменный reference" in router
          and "сбрасывает эту квитанцию" in router
          and help_run.returncode == 0
          and len(evidence_help.encode("utf-8")) <= 2_500
          and all(x in evidence_help for x in
                  ("--support", "--challenge", "read every cN", "A limit forbids supported"))
          and "references/measurement.md" in measured.get("resources", []),
          out, "entry <=8KiB; section/help costs and accepted release baseline are measured")


def t_analytical_delta_keeps_canon_and_primary_scope_visible():
    """20.08: old policy looked new and an incomplete SUM replaced a MiFID total."""
    ref = skill_text("references/operations.md")
    out = Vyvod(ref, 0)
    check("аналитика различает канон, новую дельту и охват производного агрегата",
          "уже в каноне" in ref
          and "новая дельта" in ref
          and "Переформулированный канон не становится новой находкой" in ref
          and "агрегат производного слоя" in ref
          and "первичный документ" in ref,
          out, "canon path vs new delta; derived scope cannot overrule fuller primary evidence")


def t_project_entry_is_two_layer_and_keeps_stop_gates():
    """Шесть проектов: entry rules достигали 52 КБ; authority нельзя потерять."""
    tpl = skill_text("assets/templates/CLAUDE.md")
    out = Vyvod(tpl, 0)
    check("project boot entry короткий, routed и fail-closed",
          len(tpl.encode("utf-8")) <= 8_000
          and "короткий boot canon" in tpl
          and "подробные правила" in tpl
          and "Authority и stop-gates" in tpl
          and "обязательная project role" in tpl
          and "один\n   объявленный readiness command/manifest" in tpl
          and "role readiness: `PROJECT_ROLES.json`" in tpl
          and "measure-route-costs.py" not in tpl
          and "`UNKNOWN`, не PASS" in tpl,
          out, "static details move out; current, authority, checks and role trigger remain")


def t_interactive_result_precedes_durable_tail():
    """13.08: copyable draft waited 19 minutes behind intake/check/commit/push."""
    ref = skill_text("references/operations.md")
    router = skill_text("SKILL.md")
    draft = "покажи владельцу явно помеченный черновик"
    durable = "один общий точечный commit и"
    out = Vyvod(ref + "\n" + router, 0)
    check("interactive draft is not blocked by the durable tail",
          draft in ref
          and durable in ref
          and ref.index(draft) < ref.index(durable)
          and "time to first useful result" in ref
          and "time to durable completion" in ref
          and "Не коммить" in ref
          and "60 секунд" in ref
          and "три последовательных tool round-trip" in ref
          and "коммуникационный порог" in ref
          and "integration audit" in ref
          and "durable tail не" in router,
          out, "show a checked draft first; save one coherent block afterwards")


def t_warm_turn_does_not_restart_project_boot():
    """13.08: service entry was read as a per-message cycle in a warm task."""
    router = skill_text("SKILL.md")
    service = skill_text("references/service-layer.md")
    template = skill_text("assets/templates/CLAUDE.md")
    out = Vyvod(router + "\n" + service + "\n" + template, 0)
    check("warm turn reuses boot receipt and keeps service work off answer path",
          "Новый пользовательский turn — не новый вход" in router
          and "только ответ" in router
          and "не при каждом сообщении" in service
          and "не запускай этот цикл снова" in service
          and "до current state" in service
          and "на первой безопасной границе" in service
          and "один раз на новую task/session" in template,
          out, "cold task updates before work; warm turns reuse receipt; long task waits for a safe boundary")


def t_moved_project_retires_stale_runtime_bindings():
    """13.08: old task kept deleted cwd and could not write the canonical target."""
    ref = skill_text("references/move-project.md")
    out = Vyvod(ref, 0)
    check("old runtime binding is stale for writes after a project move",
          "fresh target-bound session" in ref
          and "stale for writes" in ref
          and "frozen `cwd`" in ref
          and "пробный безопасный" in ref
          and "не означает сохранение рабочего runtime" in ref,
          out, "preserve history but move writes to a proven target-bound session")


def t_entry_ack_can_close_without_closing_subject():
    """12.08: open subject was mistaken for an entry update still waiting."""
    ref = skill_text("references/operations.md")
    out = Vyvod(ref, 0)
    check("entry acknowledgement does not close the subject correction",
          "два независимых состояния" in ref
          and "✔ Вход учтён YYYY-MM-DD; предметное расхождение остаётся открытым" in ref
          and "Не закрывай предмет искусственно" in ref,
          out, "partial receipt closes only the entry-sync debt")


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


def t_shared_move_names_ai_projects_not_the_folder():
    """Уточнение владельца 11.08: звёздочка — UI-метка двух AI, не путь."""
    ref = skill_text("references/move-project.md")
    skill = skill_text("SKILL.md")
    out = Vyvod(ref + "\n" + skill, 0)
    check("перенос различает UI-имя, каталог и repo slug",
          "`* <каноническое имя проекта>`" in ref
          and "метка в интерфейсе искусственного интеллекта" in ref
          and "не часть имени папки" in ref
          and "slug основного Git-репозитория" in ref
          and "переименовать отображаемый Claude project" in ref
          and "переименовать отображаемый Codex local project в `* <каноническое имя проекта>`" in ref
          and "Миграцию может вести Codex" in ref
          and "все чаты прежнего Claude project" in ref
          and "все задачи/чаты прежнего local project" in ref
          and "каждый чат/задача" in ref
          and "перепривязать его, не создавая новый" in ref
          and "добавить target" in ref
          and "сделать target основной" in ref
          and "удалить source из списка" in ref
          and "прежний project ID" in ref
          and "list_projects" in ref
          and "list_threads" in ref
          and "root существующего Codex project неизменяем" in ref
          and "получают `* `" in skill,
          out, "оба AI получают * name; folder и repo остаются без звёздочки")


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
          and "pinned cross-repo dependency" in ref
          and ".agents/skills/" in ref
          and ".claude/skills/" in ref
          and "fail-closed" in ref
          and "не копируют отдельно под Claude и Codex" in ref,
          out, "один канон навыка для проекта или нескольких проектов")


def skill_registry(name, canonical, codex, claude):
    return {
        "schema": 2,
        "supported_agents": ["codex", "claude"],
        "role_policy": {
            "status": "required",
            "rationale": "fixture makes material subject-matter judgements",
            "unmatched_material_work": "stop",
            "multiple_matches": "load-all",
            "conflict": "preserve-and-escalate",
        },
        "skills": [{
            "name": name,
            "required": True,
            "roles": [{
                "id": "subject-auditor",
                "purpose": "fixture procedure",
                "required_when": "subject work",
                "scope": "procedure only; project facts stay in KB",
            }],
            "modality": "evidence-led professional adviser",
            "authority_ladder": ["applicable primary authority", "case evidence", "secondary analysis", "community lead"],
            "conflict_resolution": "higher applicable authority wins; preserve the conflict",
            "evidence_threshold": "cite sufficient project evidence before a conclusion",
            "stop_conditions": ["applicability unresolved", "required source unavailable"],
            "prohibited_actions": ["invent missing facts", "act beyond owner authority"],
            "canonical": canonical,
            "owner": "project owner",
            "project_precedence": "PROJECT_RULES.md",
            "version": "1.0.0",
            "validation": {"command": "python3 tests.py", "environment": "python 3"},
            "failure_policy": "fail-closed",
            "recovery_cost": "fresh clone plus declared dependencies",
            "discovery": {"codex": codex, "claude": claude},
        }],
    }


def visible_role_registry(name, canonical, codex, claude,
                          entry_bytes=100_000, extra_roles=None):
    roles = [{
        "id": "subject-auditor",
        "purpose": "fixture professional method",
        "load_when": ["subject work"],
        "skill": name,
        "knowledge_routes": ["case-state"],
    }]
    roles.extend(extra_roles or [])
    return {
        "schema": 1,
        "supported_agents": ["codex", "claude"],
        "role_posture": {
            "status": "required",
            "rationale": "fixture makes material subject-matter judgements",
            "unmatched_material_work": "stop",
            "multiple_matches": "load-all",
            "conflict": "preserve-and-escalate",
        },
        "roles": roles,
        "skills": [{
            "name": name,
            "canonical": canonical,
            "owner": "fixture project",
            "quality_owner": "fixture domain maintainer",
            "quality_review": f"{canonical}/ROLE_QUALITY_REVIEW.json",
            "version": "1.0.0",
            "validation": {
                "platform": {
                    "command": "python3 quick_validate.py",
                    "environment": "python 3",
                },
                "project": {
                    "command": "python3 tests.py",
                    "environment": "python 3",
                    "covers": ["role-selection", "knowledge-recall", "authority-stop",
                               "source-conflict", "context-cost"],
                },
            },
            "failure_policy": "fail-closed",
            "recovery_cost": "fresh clone plus declared dependencies",
            "discovery": {"codex": codex, "claude": claude},
        }],
        "cost_policy": {
            "review_above_bytes": 8192,
            "all_roles_scenario": "subject-work",
            "scenarios": [{
                "id": "subject-work",
                "roles": [role["id"] for role in roles],
                "route_files": ["knowledge/case.md"],
                "accepted_role_entry_bytes": entry_bytes,
                "accepted_static_route_bytes": entry_bytes + 100_000,
                "accepted_reason": "fixture baseline",
            }],
        },
    }


def write_role_acceptance(root, registry):
    import json
    registry["acceptance"] = {
        "status": "accepted",
        "receipt": "ROLE_ACCEPTANCE.json",
        "behavior_scope": "shared",
    }
    with open(os.path.join(root, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    index_path = os.path.join(root, "KNOWLEDGE_INDEX.json")
    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(knowledge_index(), f)
    skills = {}
    evidence_by_skill = {}
    for entry in registry["skills"]:
        path = entry["canonical"]
        skill_root = path if os.path.isabs(path) else os.path.join(root, path)
        skill_md = os.path.join(skill_root, "SKILL.md")
        evidence_path = os.path.join(skill_root, "tests", "acceptance.txt")
        os.makedirs(os.path.dirname(evidence_path), exist_ok=True)
        with open(evidence_path, "w", encoding="utf-8") as f:
            f.write("synthetic structural discovery behavior and owner evidence\n")
        evidence_relative = os.path.relpath(evidence_path, root).replace(os.sep, "/")
        evidence_sha = hashlib.sha256(open(evidence_path, "rb").read()).hexdigest()
        review_path = entry["quality_review"]
        review_path = (review_path if os.path.isabs(review_path)
                       else os.path.join(root, review_path))
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema": 1,
                "skill": entry["name"],
                "quality_owner": entry["quality_owner"],
                "reviewed_at": "2026-08-28",
                "result": "PASS",
                "review_scope": "internal-method",
                "professional_method": "fixture",
                "domain_regressions": ["fixture"],
                "external_practice_review": {
                    "status": "not-applicable", "rationale": "fixture",
                },
                "role_knowledge_boundary": {
                    "outcome": "method-only",
                    "reason": "fixture role contains only method",
                    "safe_current_mode": "keep project facts in indexed knowledge",
                },
                "evidence": [{"path": evidence_relative, "sha256": evidence_sha}],
            }, f)
        tree = hashlib.sha256()
        files = []
        for folder, _, names in os.walk(skill_root):
            files.extend(os.path.join(folder, filename) for filename in names)
        for file_path in sorted(files):
            relative = os.path.relpath(file_path, skill_root).replace(os.sep, "/")
            with open(file_path, "rb") as source:
                tree.update(relative.encode("utf-8") + b"\0" +
                            source.read() + b"\0")
        skills[entry["name"]] = {
            "skill_sha256": hashlib.sha256(open(skill_md, "rb").read()).hexdigest(),
            "skill_tree_sha256": tree.hexdigest(),
            "quality_review_sha256": hashlib.sha256(
                open(review_path, "rb").read()).hexdigest(),
        }
        evidence_by_skill[entry["name"]] = {
            "path": evidence_relative, "sha256": evidence_sha,
        }
    common_evidence = next(iter(evidence_by_skill.values()))
    agents = {}
    for agent in registry["supported_agents"]:
        inventory = []
        for entry in registry["skills"]:
            point = os.path.join(root, entry["discovery"][agent], "SKILL.md")
            inventory.append({
                "id": entry["name"],
                "path": os.path.relpath(point, root).replace(os.sep, "/"),
                "sha256": (hashlib.sha256(open(point, "rb").read()).hexdigest()
                           if os.path.isfile(point) else None),
                "version": str(entry["version"]),
            })
        agents[agent] = {
            "fresh_context": True,
            "unforced": True,
            "new_session_required": True,
            "session_boundary": "new-session",
            "inventory": inventory,
            "selected": list(inventory),
        }
    cases = {}
    behavior_folder = os.path.join(root, "role-acceptance")
    os.makedirs(behavior_folder, exist_ok=True)
    harness_path = os.path.join(behavior_folder, "fixture_behavior.py")
    with open(harness_path, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env python3\nraise SystemExit(0)\n")
    harness = {
        "path": os.path.relpath(harness_path, root).replace(os.sep, "/"),
        "sha256": hashlib.sha256(open(harness_path, "rb").read()).hexdigest(),
        "argv": [],
    }
    recorded_artifacts = {}
    case_run_ids = {}
    for case in ("role-selection", "knowledge-recall", "authority-stop",
                 "source-conflict", "context-cost"):
        artifacts = {}
        for kind, content in (
                ("input", {"case": case, "prompt": "synthetic fixture input"}),
                ("expected", {"case": case, "expected": "fixture PASS"}),
                ("observed", {"case": case, "observed": "fixture PASS"})):
            path = os.path.join(behavior_folder, f"{case}-{kind}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(content, f)
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            artifacts[kind] = {
                "path": relative,
                "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
            }
            recorded_artifacts[relative] = artifacts[kind]["sha256"]
        case_run_ids[case] = "fixture-" + case
        cases[case] = {
            "result": "PASS",
            "evidence": [common_evidence],
            "run": {
                "run_id": "fixture-" + case,
                "case": case,
                "executed_at": "2026-08-28T00:00:00Z",
                "runtime": "shared synthetic fixture",
                "harness": harness,
                "result": "PASS",
                **artifacts,
            },
        }
    execution_path = os.path.join(behavior_folder, "behavior-execution.json")
    with open(execution_path, "w", encoding="utf-8") as f:
        json.dump({
            "schema": 1,
            "protocol": "kb-behavior-run/v1",
            "runner_version": "1",
            "runner_sha256": "0" * 64,
            "started_at": "2026-08-28T00:00:00Z",
            "finished_at": "2026-08-28T00:00:00Z",
            "exit_code": 0,
            "harness": harness,
            "case_run_ids": case_run_ids,
            "artifacts": recorded_artifacts,
            "stdout_tail": "fixture PASS",
            "stderr_tail": "",
        }, f)
    execution_evidence = {
        "path": os.path.relpath(execution_path, root).replace(os.sep, "/"),
        "sha256": hashlib.sha256(open(execution_path, "rb").read()).hexdigest(),
    }
    for result in cases.values():
        result["run"]["execution_receipt"] = execution_evidence
    receipt = {
        "schema": 3,
        "outcomes": {
            "STRUCTURAL_PASS": {
                "status": "PASS", "evidence": [common_evidence],
                "validators": {
                    entry["name"]: {
                        gate: {"result": "PASS",
                               "command": entry["validation"][gate]["command"],
                               "evidence": [evidence_by_skill[entry["name"]]]}
                        for gate in ("platform", "project")
                    }
                    for entry in registry["skills"]
                },
            },
            "DISCOVERY_PASS": {"status": "PASS", "evidence": [common_evidence],
                               "agents": agents},
            "BEHAVIOR_PASS": {
                "status": "PASS", "proof_mode": "synthetic-first",
                "runtime_scope": "shared",
                "evidence": [common_evidence], "cases": cases,
                "private_real_data": {
                    "authority": "not-granted", "result": "UNKNOWN",
                    "reason": "fixture uses synthetic proof",
                },
            },
            "OWNER_ACCEPTED": {
                "status": "PASS", "accepted_by": "fixture owner",
                "accepted_at": "2026-08-28", "evidence": [common_evidence],
            },
        },
        "project_roles_sha256": hashlib.sha256(
            open(os.path.join(root, "PROJECT_ROLES.json"), "rb").read()).hexdigest(),
        "knowledge_index_sha256": hashlib.sha256(
            open(index_path, "rb").read()).hexdigest(),
        "skills": skills,
        "scenario_baselines": {
            item["id"]: {
                "accepted_role_entry_bytes": item["accepted_role_entry_bytes"],
                "accepted_static_route_bytes": item["accepted_static_route_bytes"],
                "route_files": item["route_files"],
            }
            for item in registry["cost_policy"]["scenarios"]
        },
        "actual_usage": {
            "status": "UNKNOWN", "reason": "fixture has no model token receipt",
        },
    }
    with open(os.path.join(root, "ROLE_ACCEPTANCE.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f)


def accepted_role_fixture(skill_body=None):
    import json
    body = (skill_body or
            "---\nname: domain-auditor\ndescription: Fixture role\n"
            "metadata:\n  version: 1.0.0\n---\nfixture\n")
    d = base({"skills/domain-auditor/SKILL.md": body,
              "knowledge/case.md": "fixture\n"})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/domain-auditor",
                   os.path.join(d, base_dir, "skills", "domain-auditor"))
    registry = visible_role_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor")
    write_role_acceptance(d, registry)
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json", "KNOWLEDGE_INDEX.json", "knowledge",
                    "skills", "role-acceptance", ".agents", ".claude"], check=True)
    return d, registry


def compact_role_fixture(accepted=False):
    """6.2 fixture: one manifest, one live scenario, no receipt tree."""
    import json
    d, _registry = accepted_role_fixture()
    registry_path = os.path.join(d, "PROJECT_ROLES.json")
    registry = json.load(open(registry_path, encoding="utf-8"))
    skill = registry["skills"][0]
    skill.pop("quality_review", None)
    skill["quality"] = {
        "status": "reviewed",
        "professional_method": "fixture source-led method",
        "external_practice": "not-applicable",
        "knowledge_boundary": "method-only",
        "reason": "fixture facts remain in indexed knowledge",
        "return_condition": None,
    }
    scenario = registry["cost_policy"]["scenarios"][0]
    for field in ("accepted_role_entry_bytes", "accepted_static_route_bytes",
                  "accepted_control_plane_bytes"):
        scenario.pop(field, None)
    scenario["accepted_end_to_end_bytes"] = 300_000
    skill_hash = hashlib.sha256(open(
        os.path.join(d, "skills", "domain-auditor", "SKILL.md"), "rb").read()).hexdigest()
    registry["acceptance"] = {
        "protocol": "kb-role-acceptance/v2",
        "status": "accepted" if accepted else "candidate",
        "accepted_skill_sha256": {"domain-auditor": skill_hash},
        "project_check": {
            "status": "PASS", "command": "python3 tests.py",
            "execution": {
                "executed_at": "2026-08-29T00:00:00Z", "exit_code": 0,
                "run_id": "fixture-project-check-run",
            },
        },
        "live_test": {
            "status": "PASS", "agent": "codex", "fresh_context": True,
            "unforced": True,
            "covers": ["role-selection", "knowledge-recall", "authority-stop"],
            "summary": "role selected, indexed fact found, unsupported action stopped",
            "observation": {
                "observed_at": "2026-08-29T00:00:00Z",
                "run_id": "fixture-fresh-context-run",
            },
        },
        "agents": {
            "codex": {"status": "TESTED", "basis": "live_test"},
            "claude": {"status": "INHERITED",
                       "basis": "same canonical bytes and unchanged wiring"},
        },
        "owner": ({"status": "PASS", "accepted_by": "fixture owner",
                   "accepted_at": "2026-08-29"} if accepted else
                  {"status": "PENDING", "accepted_by": None, "accepted_at": None}),
        "open": [],
    }
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f)
    with open(os.path.join(d, "tests.py"), "w", encoding="utf-8") as f:
        f.write("raise SystemExit(0)\n")
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json", "tests.py"],
                   check=True)
    return d


def upgrade_fixture_to_schema4(root):
    """Give the accepted fixture runner-owned per-case mutations."""
    import json
    acceptance_path = os.path.join(root, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    receipt["schema"] = 4
    harness_path = os.path.join(root, "role-acceptance", "fixture_behavior.py")
    with open(harness_path, "w", encoding="utf-8") as f:
        f.write(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "from pathlib import Path\n"
            "for path in Path('role-acceptance').glob('*-input.json'):\n"
            "    data = json.loads(path.read_text(encoding='utf-8'))\n"
            "    if data.get('prompt') != 'synthetic fixture input':\n"
            "        raise SystemExit(10)\n"
            "raise SystemExit(0)\n")
    harness_hash = hashlib.sha256(open(harness_path, "rb").read()).hexdigest()
    for case, result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].items():
        result["run"]["harness"]["sha256"] = harness_hash
        target_path = os.path.join(root, result["run"]["input"]["path"])
        target_data = json.load(open(target_path, encoding="utf-8"))
        target_data["neutral_note"] = "neutral fixture note"
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(target_data, f)
        target_hash = hashlib.sha256(open(target_path, "rb").read()).hexdigest()
        result["run"]["input"]["sha256"] = target_hash
        result["run"]["negative_control"] = {
            "id": "break-" + case,
            "target": {"path": result["run"]["input"]["path"],
                       "sha256": target_hash},
            "mutation": {"kind": "replace-text",
                         "find": "synthetic fixture input",
                         "replace": "BROKEN fixture input",
                         "count": 1},
            "neutral_mutation": {"kind": "replace-text",
                                 "find": "neutral fixture note",
                                 "replace": "neutral fixture note revised",
                                 "count": 1},
            "expected_exit": 10,
        }
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", root, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance"], check=True)
    return receipt


def upgrade_fixture_to_schema5(root):
    """Bind per-case results, portable argv and complete static budgets."""
    import json
    acceptance_path = os.path.join(root, "ROLE_ACCEPTANCE.json")
    receipt = upgrade_fixture_to_schema4(root)
    receipt["schema"] = 5
    registry_path = os.path.join(root, "PROJECT_ROLES.json")
    registry = json.load(open(registry_path, encoding="utf-8"))
    for scenario in registry["cost_policy"]["scenarios"]:
        scenario["accepted_control_plane_bytes"] = 100_000
        scenario["accepted_end_to_end_bytes"] = 300_000
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f)

    harness_path = os.path.join(root, "role-acceptance", "fixture_behavior.py")
    with open(harness_path, "w", encoding="utf-8") as f:
        f.write(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "from pathlib import Path\n"
            "cases = ('role-selection', 'knowledge-recall', 'authority-stop', "
            "'source-conflict', 'context-cost')\n"
            "results = {}\n"
            "for case in cases:\n"
            "    path = Path('role-acceptance') / (case + '-input.json')\n"
            "    data = json.loads(path.read_text(encoding='utf-8'))\n"
            "    results[case] = ('PASS' if data.get('prompt') == "
            "'synthetic fixture input' else 'FAIL')\n"
            "print('KB_BEHAVIOR_RESULT ' + json.dumps({"
            "'protocol': 'kb-behavior-result/v1', 'results': results}, "
            "sort_keys=True))\n"
            "raise SystemExit(10 if 'FAIL' in results.values() else 0)\n")
    harness_hash = hashlib.sha256(open(harness_path, "rb").read()).hexdigest()
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["harness"]["sha256"] = harness_hash
    receipt["project_roles_sha256"] = hashlib.sha256(
        open(registry_path, "rb").read()).hexdigest()
    receipt["scenario_baselines"] = {
        item["id"]: {
            "accepted_role_entry_bytes": item["accepted_role_entry_bytes"],
            "accepted_static_route_bytes": item["accepted_static_route_bytes"],
            "route_files": item["route_files"],
            "accepted_control_plane_bytes": item["accepted_control_plane_bytes"],
            "accepted_end_to_end_bytes": item["accepted_end_to_end_bytes"],
        }
        for item in registry["cost_policy"]["scenarios"]
    }
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", root, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json", "role-acceptance"], check=True)
    return receipt


def execute_and_bind_behavior(root):
    """Run the canonical recorder and bind its immutable receipt to every case."""
    import json
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), root,
         "--execute", "--replace"], capture_output=True, text=True, timeout=30)
    execution_path = os.path.join(root, "role-acceptance", "behavior-execution.json")
    execution = json.load(open(execution_path, encoding="utf-8"))
    execution_sha = hashlib.sha256(open(execution_path, "rb").read()).hexdigest()
    acceptance_path = os.path.join(root, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["executed_at"] = execution["finished_at"]
        result["run"]["execution_receipt"]["sha256"] = execution_sha
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", root, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/behavior-execution.json"], check=True)
    return run, execution


def t_610_schema_two_role_receipt_remains_backward_readable():
    """Installed 6.1 must not invalidate an accepted 6.0.1 project before migration."""
    import json
    body = (
        "---\nname: domain-auditor\ndescription: Fixture role\n"
        "metadata:\n  version: 1.0.0\n---\n"
        "Load [the detailed method](references/deep.md) for subject work.\n"
    )
    d, registry = accepted_role_fixture(skill_body=body)
    support = os.path.join(d, "skills", "domain-auditor", "references", "deep.md")
    os.makedirs(os.path.dirname(support), exist_ok=True)
    with open(support, "w", encoding="utf-8") as f:
        f.write("x" * 1_000_000)
    write_role_acceptance(d, registry)
    path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(path, encoding="utf-8"))
    receipt["schema"] = 2
    receipt["outcomes"]["BEHAVIOR_PASS"].pop("runtime_scope")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "skills/domain-auditor",
                    "PROJECT_ROLES.json", "ROLE_ACCEPTANCE.json"], check=True)
    out = run_skills(d)
    check("schema-2 role acceptance остаётся читаемой до project migration 6.1",
          out.code == 0
          and "ROLE_ACCEPTANCE_SCHEMA_2_LEGACY" in out
          and "ROLE_COST_SCHEMA_2_LEGACY" in out
          and "linked-role-support=1000000" in out,
          out, "new linked-support accounting is a migration delta, not a retroactive failure")
    shutil.rmtree(d, ignore_errors=True)


def t_610_behavior_scope_is_machine_readable_and_bound():
    """Sk-tax audit: opaque prose claimed per-runtime behavior beyond the green receipt."""
    import json
    d, _registry = accepted_role_fixture()
    path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(path, encoding="utf-8"))
    receipt["outcomes"]["BEHAVIOR_PASS"]["runtime_scope"] = "per-runtime"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    out = run_skills(d)
    check("behavior scope manifest и receipt не расходятся в свободном тексте",
          out.code == 1
          and "BEHAVIOR_PASS.runtime_scope must match acceptance.behavior_scope" in out,
          out, "schema 3 binds shared behavior while discovery remains per runtime")
    shutil.rmtree(d, ignore_errors=True)


def t_610_role_cost_uses_headroom_budget_not_exact_mutable_snapshot():
    """Claude audit: exact baselines over append-only routes punish correct project work."""
    d, registry = accepted_role_fixture()
    scenario = registry["cost_policy"]["scenarios"][0]
    scenario["accepted_role_entry_bytes"] = 1024
    scenario["accepted_static_route_bytes"] = 4096
    scenario["accepted_reason"] = "fixture budget with normal-growth headroom"
    write_role_acceptance(d, registry)
    path = os.path.join(d, "knowledge", "case.md")
    with open(path, "a", encoding="utf-8") as f:
        f.write("ordinary append-only growth\n" * 100)
    within = run_skills(d)
    with open(path, "a", encoding="utf-8") as f:
        f.write("x" * 5_000)
    above = run_skills(d)
    combined = Vyvod(str(within) + "\n" + str(above), above.code)
    check("role cost baseline — бюджет с headroom, а не точный слепок",
          within.code == 0 and above.code == 1
          and "OPTIMIZATION_REQUIRED subject-work" in above,
          combined, "normal change stays green; only growth beyond the accepted ceiling reopens cost")
    shutil.rmtree(d, ignore_errors=True)


def t_610_linked_role_support_cannot_hide_from_cost_gate():
    """Independent audit: standard Markdown link forms must all enter role cost."""
    variants = [
        ("inline", "[method](references/deep.md)", "references/deep.md"),
        ("reference", "[method][deep]\n\n[deep]: references/deep.md",
         "references/deep.md"),
        ("angle", "[method](<references/deep method.md>)",
         "references/deep method.md"),
        ("percent-space", "[method](references/deep%20method.md)",
         "references/deep method.md"),
        ("parentheses", "[method](references/deep(1).md)",
         "references/deep(1).md"),
    ]
    passed = True
    details = []
    for label, link, relative in variants:
        body = (
            "---\nname: domain-auditor\ndescription: Fixture role\n"
            "metadata:\n  version: 1.0.0\n---\n"
            f"Load {link} for subject work.\n"
        )
        d, registry = accepted_role_fixture(skill_body=body)
        support = os.path.join(d, "skills", "domain-auditor", *relative.split("/"))
        os.makedirs(os.path.dirname(support), exist_ok=True)
        with open(support, "w", encoding="utf-8") as f:
            f.write("x" * 1_000_000)
        write_role_acceptance(d, registry)
        subprocess.run(["git", "-C", d, "add", "skills/domain-auditor",
                        "ROLE_ACCEPTANCE.json"], check=True)
        out = run_skills(d)
        variant_passed = (out.code == 1
                          and "OPTIMIZATION_REQUIRED subject-work" in out
                          and "linked-role-support=1000000" in out)
        passed = passed and variant_passed
        details.append(f"{label}: {out}")
        shutil.rmtree(d, ignore_errors=True)
    out = Vyvod("\n".join(details), 0 if passed else 1)
    check("linked supporting file роли автоматически входит в cost gate",
          passed, out, "inline, reference and angle destinations cannot hide 1 MB context")


def knowledge_index():
    return {
        "schema": 1,
        "routes": [{
            "id": "case-state",
            "description": "fixture case knowledge",
            "load_when": ["subject work"],
            "aliases": ["case", "state"],
            "paths": ["knowledge/case.md"],
        }],
    }


def run_skills(root, home=None, execute_project_check=False):
    env = dict(os.environ)
    if home:
        env["HOME"] = home
    command = [sys.executable, os.path.join(HERE, "kb_skills.py"), root]
    if execute_project_check:
        command.append("--execute-project-check")
    p = subprocess.run(
        command,
        capture_output=True, text=True, timeout=120, env=env)
    return Vyvod(p.stdout + p.stderr, p.returncode)


def t_required_global_only_skill_blocks_recovery():
    """11.08: fresh clone kept the KB but lost a required user-global procedure."""
    d = base({})
    home = os.path.join(d, "home")
    canonical = os.path.join(home, ".codex", "skills", "domain-auditor")
    os.makedirs(canonical)
    with open(os.path.join(canonical, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: domain-auditor\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\n")
    registry = skill_registry("domain-auditor", canonical,
                              ".agents/skills/domain-auditor",
                              ".claude/skills/domain-auditor")
    with open(os.path.join(d, ".kb-skills.json"), "w", encoding="utf-8") as f:
        import json
        json.dump(registry, f)
    out = run_skills(d, home)
    check("обязательный global-only skill блокирует fresh-clone readiness",
          out.code == 1 and "required skill is user-global only" in out,
          out, "global install is delivery, not a recoverable project source")
    shutil.rmtree(d, ignore_errors=True)


def t_external_role_checkout_must_match_declared_pin():
    """A mutable sibling checkout must not masquerade as a pinned dependency."""
    import json
    external = base({"skills/shared-role/SKILL.md":
                     "---\nname: shared-role\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\nfirst\n"})
    subprocess.run(["git", "-C", external, "init", "-q"], check=True)
    subprocess.run(["git", "-C", external, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", external, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", external, "remote", "add", "origin",
                    "https://example.invalid/roles.git"], check=True)
    subprocess.run(["git", "-C", external, "add", "skills/shared-role/SKILL.md"],
                   check=True)
    subprocess.run(["git", "-C", external, "commit", "-qm", "first"], check=True)
    first = subprocess.run(["git", "-C", external, "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=True).stdout.strip()
    with open(os.path.join(external, "skills/shared-role/SKILL.md"), "a",
              encoding="utf-8") as f:
        f.write("second\n")
    subprocess.run(["git", "-C", external, "add", "skills/shared-role/SKILL.md"],
                   check=True)
    subprocess.run(["git", "-C", external, "commit", "-qm", "second"], check=True)

    d = base({"README.md": "fixture\n"})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    canonical = os.path.join(external, "skills", "shared-role")
    os.symlink(canonical, os.path.join(d, ".agents", "skills", "shared-role"))
    os.symlink(canonical, os.path.join(d, ".claude", "skills", "shared-role"))
    registry = skill_registry(
        "shared-role", canonical, ".agents/skills/shared-role",
        ".claude/skills/shared-role")
    registry["skills"][0]["dependency"] = {
        "repository": "https://example.invalid/roles.git",
        "pin": first,
        "recovery": "clone and checkout the exact commit",
    }
    with open(os.path.join(d, ".kb-skills.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", ".kb-skills.json", ".agents", ".claude"],
                   check=True)
    out = run_skills(d)
    check("external role bytes совпадают с объявленным pin",
          out.code == 1 and "HEAD does not match dependency pin" in out,
          out, "a sibling checkout at a newer commit is not the pinned role")
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(external, ignore_errors=True)


def t_broken_project_skill_discovery_is_visible():
    """11.08: a declared discovery link must not fail open after a move."""
    d = base({"skills/domain-auditor/SKILL.md":
              "---\nname: domain-auditor\n---\n"})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    os.symlink("../../skills/missing", os.path.join(d, ".agents", "skills", "domain-auditor"))
    os.symlink("../../skills/domain-auditor", os.path.join(d, ".claude", "skills", "domain-auditor"))
    registry = visible_role_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor")
    write_role_acceptance(d, registry)
    import json
    os.makedirs(os.path.join(d, "knowledge"))
    with open(os.path.join(d, "knowledge", "case.md"), "w", encoding="utf-8") as f:
        f.write("fixture\n")
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json", "ROLE_ACCEPTANCE.json", "role-acceptance",
                    "KNOWLEDGE_INDEX.json", "knowledge", "skills",
                    ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("битая discovery-ссылка называется ошибкой",
          out.code == 1 and "broken codex discovery symlink" in out,
          out, "missing link cannot look like agent acceptance")
    shutil.rmtree(d, ignore_errors=True)


def t_role_registry_version_must_match_loaded_skill():
    """27.08 field audit: tg-archive registry said 3.2 while its skill was 3.3."""
    d = base({"skills/domain-auditor/SKILL.md":
              "---\nname: domain-auditor\ndescription: Fixture role\nmetadata:\n  version: 2.0.0\n---\n"})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    os.symlink("../../skills/domain-auditor",
               os.path.join(d, ".agents", "skills", "domain-auditor"))
    os.symlink("../../skills/domain-auditor",
               os.path.join(d, ".claude", "skills", "domain-auditor"))
    registry = visible_role_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor")
    write_role_acceptance(d, registry)
    import json
    os.makedirs(os.path.join(d, "knowledge"))
    with open(os.path.join(d, "knowledge", "case.md"), "w", encoding="utf-8") as f:
        f.write("fixture\n")
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json", "ROLE_ACCEPTANCE.json", "role-acceptance",
                    "KNOWLEDGE_INDEX.json", "knowledge", "skills",
                    ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("устаревшая версия role registry не получает PASS",
          out.code == 1 and "registry version 1.0.0 != SKILL.md metadata.version 2.0.0" in out,
          out, "declared role version must describe the bytes an agent loads")
    shutil.rmtree(d, ignore_errors=True)


def t_large_composite_role_emits_cost_signal():
    """27.08 field audit: a broad company skill loaded unrelated professional lanes."""
    d = base({"skills/company-adviser/SKILL.md":
              "---\nname: company-adviser\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\n" + "x" * 9000})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/company-adviser",
                   os.path.join(d, base_dir, "skills", "company-adviser"))
    second_role = {
        "id": "labour-adviser",
        "purpose": "employment procedure",
        "load_when": ["employment work"],
        "skill": "company-adviser",
        "knowledge_routes": ["case-state"],
    }
    registry = visible_role_registry(
        "company-adviser", "skills/company-adviser",
        ".agents/skills/company-adviser", ".claude/skills/company-adviser",
        entry_bytes=20_000, extra_roles=[second_role])
    write_role_acceptance(d, registry)
    import json
    os.makedirs(os.path.join(d, "knowledge"))
    with open(os.path.join(d, "knowledge", "case.md"), "w", encoding="utf-8") as f:
        f.write("fixture\n")
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json", "ROLE_ACCEPTANCE.json", "role-acceptance",
                    "KNOWLEDGE_INDEX.json", "knowledge", "skills",
                    ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("большая составная роль получает измеримый cost signal",
          out.code == 0 and "COST_SIGNAL subject-work" in out
          and "route-cost subject-work" in out,
          out, "review threshold is a signal; accepted route baseline is authoritative")
    shutil.rmtree(d, ignore_errors=True)


def t_project_without_role_posture_is_visible():
    """27.08 field audit: UAD did substantive work while role absence passed."""
    d = base({"README.md": "ordinary project\n"})
    out = run_skills(d)
    check("отсутствие role posture больше не выдаётся за осознанное решение",
          out.code == 1 and "professional role posture is undeclared" in out,
          out, "project must declare required roles or explicit not-applicable")
    shutil.rmtree(d, ignore_errors=True)


def t_explicit_non_domain_project_is_valid():
    """A pure storage/communication project can consciously decline domain roles."""
    import json
    d = base({"README.md": "ordinary project\n"})
    registry = {
        "schema": 1,
        "supported_agents": ["codex", "claude"],
        "role_posture": {
            "status": "not-applicable",
            "rationale": "stores and transports knowledge; makes no domain judgement",
        },
        "roles": [],
        "skills": [],
    }
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json"], check=True)
    out = run_skills(d)
    check("осознанный non-domain проект проходит без декоративной роли",
          out.code == 0 and "role posture: not-applicable" in out
          and "declared=0 errors=0" in out,
          out, "explicit rationale distinguishes not-applicable from forgotten")
    shutil.rmtree(d, ignore_errors=True)


def t_capability_registry_expresses_role_not_only_location():
    """Дополнение владельца 11.08: discovery alone does not define a profession."""
    import json
    data = json.loads(skill_text("assets/templates/project-roles.json"))
    entry = data["skills"][0]
    role = data["roles"][0]
    policy = data["role_posture"]
    scenario = data["cost_policy"]["scenarios"][0]
    acceptance = data["acceptance"]
    out = Vyvod(str(entry) + str(acceptance), 0)
    check("видимый реестр проводит роль, знания, recovery и cost без копии метода",
          data.get("schema") == 1
          and policy.get("unmatched_material_work") == "stop"
          and policy.get("multiple_matches") == "load-all"
          and policy.get("conflict") == "preserve-and-escalate"
          and all(role.get(field) for field in
                  ("id", "purpose", "load_when", "skill", "knowledge_routes"))
          and entry.get("canonical")
          and entry.get("quality_owner") and entry.get("quality")
          and set(entry["validation"]) == {"platform", "project"}
          and set(entry["validation"]["project"]["covers"]) == {
              "role-selection", "knowledge-recall", "authority-stop"}
          and all(key in scenario for key in
                  ("accepted_end_to_end_bytes", "route_files"))
          and acceptance.get("protocol") == "kb-role-acceptance/v2"
          and acceptance["live_test"].get("fresh_context") is True
          and acceptance["live_test"].get("unforced") is True
          and set(acceptance["live_test"].get("observation", {})) == {
              "observed_at", "run_id"}
          and set(acceptance["project_check"].get("execution", {})) == {
              "executed_at", "exit_code", "run_id"}
          and acceptance["agents"]["codex"]["status"] == "TESTED"
          and acceptance["agents"]["claude"]["status"] == "UNKNOWN",
          out, "method stays in one SKILL; registry carries split gates and costs")


def t_600_legacy_schema_one_remains_usable_during_migration():
    """Major migration must not make all existing role projects red at once."""
    import json
    d = base({"skills/domain-auditor/SKILL.md":
              "---\nname: domain-auditor\n---\n"})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/domain-auditor",
                   os.path.join(d, base_dir, "skills", "domain-auditor"))
    legacy = skill_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor")
    legacy["schema"] = 1
    legacy.pop("role_policy")
    role = legacy["skills"][0].pop("roles")[0]
    legacy["skills"][0].update({
        "purpose": role["purpose"],
        "required_when": role["required_when"],
        "scope": role["scope"],
    })
    with open(os.path.join(d, ".kb-skills.json"), "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", ".kb-skills.json", "skills",
                    ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("legacy schema 1 получает migration note, а не искусственный hard failure",
          out.code == 0 and "LEGACY_ROLE_REGISTRY" in out
          and "migrate interactively" in out,
          out, "v6 is backward-readable and migration remains owner-paced")
    shutil.rmtree(d, ignore_errors=True)


def t_600_role_must_resolve_project_knowledge_route():
    """A role must not hide a missing KB route by carrying facts in its prompt."""
    import json
    d = base({"skills/domain-auditor/SKILL.md":
              "---\nname: domain-auditor\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\n"})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/domain-auditor",
                   os.path.join(d, base_dir, "skills", "domain-auditor"))
    registry = visible_role_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor")
    write_role_acceptance(d, registry)
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "routes": []}, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json", "ROLE_ACCEPTANCE.json", "role-acceptance",
                    "KNOWLEDGE_INDEX.json", "skills", ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("неизвестный knowledge route блокирует предметную готовность",
          out.code == 1 and "unknown knowledge route case-state" in out,
          out, "role behaviour cannot substitute for discoverable project knowledge")
    shutil.rmtree(d, ignore_errors=True)


def t_600_unaccepted_role_route_growth_fails_closed():
    """Cost is measured on the actual combination of roles loaded for a task."""
    import json
    d = base({
        "skills/domain-auditor/SKILL.md":
            "---\nname: domain-auditor\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\n" + "x" * 300,
        "knowledge/case.md": "fixture\n",
    })
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/domain-auditor",
                   os.path.join(d, base_dir, "skills", "domain-auditor"))
    registry = visible_role_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor",
        entry_bytes=100)
    write_role_acceptance(d, registry)
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json", "ROLE_ACCEPTANCE.json", "role-acceptance",
                    "KNOWLEDGE_INDEX.json", "knowledge", "skills",
                    ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("непринятый рост role route создаёт optimization request",
          out.code == 1 and "OPTIMIZATION_REQUIRED subject-work" in out
          and "100 ->" in out,
          out, "baseline follows a declared task route, not package size or role count")
    shutil.rmtree(d, ignore_errors=True)


def t_600_role_acceptance_is_bound_to_loaded_bytes():
    """A declared test list is not proof after the accepted skill bytes change."""
    import json
    d = base({
        "skills/domain-auditor/SKILL.md":
            "---\nname: domain-auditor\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\ninitial\n",
        "skills/domain-auditor/references/method.md": "accepted method\n",
        "knowledge/case.md": "fixture\n",
    })
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/domain-auditor",
                   os.path.join(d, base_dir, "skills", "domain-auditor"))
    registry = visible_role_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor")
    write_role_acceptance(d, registry)
    with open(os.path.join(d, "skills/domain-auditor/references/method.md"), "a",
              encoding="utf-8") as f:
        f.write("changed after acceptance\n")
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json", "role-acceptance", "KNOWLEDGE_INDEX.json", "knowledge",
                    "skills", ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("role acceptance привязана ко всему дереву роли",
          out.code == 1 and "accepted skill tree hash does not match loaded files" in out,
          out, "edited routed role file invalidates the prior behavioral receipt")
    shutil.rmtree(d, ignore_errors=True)


def t_600_cost_has_an_all_roles_upper_bound():
    """Separate ordinary scenarios must not hide the maximum combined role load."""
    import json
    d = base({
        "skills/company-adviser/SKILL.md":
            "---\nname: company-adviser\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\nfixture\n",
        "knowledge/case.md": "fixture\n",
    })
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/company-adviser",
                   os.path.join(d, base_dir, "skills", "company-adviser"))
    second_role = {
        "id": "labour-adviser", "purpose": "employment procedure",
        "load_when": ["employment work"], "skill": "company-adviser",
        "knowledge_routes": ["case-state"],
    }
    registry = visible_role_registry(
        "company-adviser", "skills/company-adviser",
        ".agents/skills/company-adviser", ".claude/skills/company-adviser",
        extra_roles=[second_role])
    registry["cost_policy"]["scenarios"][0]["roles"] = ["subject-auditor"]
    write_role_acceptance(d, registry)
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json", "role-acceptance", "KNOWLEDGE_INDEX.json", "knowledge",
                    "skills", ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("cost scenarios содержат верхнюю границу совместной загрузки ролей",
          out.code == 1 and "all_roles_scenario" in out,
          out, "ordinary one-role scenarios cannot conceal the all-roles upper bound")
    shutil.rmtree(d, ignore_errors=True)


def t_600_acceptance_binds_selection_and_knowledge_wiring():
    """Accepted behavior must become stale when triggers or knowledge routes change."""
    import json
    d = base({
        "skills/domain-auditor/SKILL.md":
            "---\nname: domain-auditor\ndescription: Fixture role\nmetadata:\n  version: 1.0.0\n---\nfixture\n",
        "knowledge/case.md": "fixture\n",
        "knowledge/other.md": "other\n",
    })
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    for base_dir in (".agents", ".claude"):
        os.symlink("../../skills/domain-auditor",
                   os.path.join(d, base_dir, "skills", "domain-auditor"))
    registry = visible_role_registry(
        "domain-auditor", "skills/domain-auditor",
        ".agents/skills/domain-auditor", ".claude/skills/domain-auditor")
    write_role_acceptance(d, registry)
    registry["roles"][0]["load_when"] = ["a different material task"]
    changed_index = knowledge_index()
    changed_index["routes"][0]["paths"] = ["knowledge/other.md"]
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(changed_index, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json", "role-acceptance", "KNOWLEDGE_INDEX.json", "knowledge",
                    "skills", ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("role acceptance привязана к selection и knowledge wiring",
          out.code == 1
          and "does not match PROJECT_ROLES.json" in out
          and "does not match KNOWLEDGE_INDEX.json" in out,
          out, "post-acceptance rewiring invalidates role-selection and recall evidence")
    shutil.rmtree(d, ignore_errors=True)


def t_600_knowledge_index_resolves_without_imposing_types():
    """Index exposes project-chosen routes and rejects paths outside the project."""
    import json
    d = base({"knowledge/case.md": "fixture\n"})
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(knowledge_index(), f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "KNOWLEDGE_INDEX.json", "knowledge"],
                   check=True)
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_index.py"), d,
         "--require", "case-state"], capture_output=True, text=True, timeout=30)
    bad = knowledge_index()
    bad["routes"][0]["paths"] = ["../outside.md"]
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(bad, f)
    p_bad = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_index.py"), d],
        capture_output=True, text=True, timeout=30)
    out = Vyvod(p.stdout + p.stderr + p_bad.stdout + p_bad.stderr, 0)
    check("knowledge index resolves an arbitrary project route and stays inside root",
          p.returncode == 0 and "ROUTE case-state: knowledge/case.md" in p.stdout
          and p_bad.returncode == 1 and "path leaves project root" in p_bad.stdout,
          out, "discoverability is enforced without a universal fact taxonomy")
    shutil.rmtree(d, ignore_errors=True)


def t_600_knowledge_index_rejects_local_only_knowledge():
    """A present ignored/untracked file is not evidence of fresh-clone recovery."""
    import json
    d = base({"knowledge/local-only.md": "fixture\n"})
    index = knowledge_index()
    index["routes"][0]["paths"] = ["knowledge/local-only.md"]
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(index, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "KNOWLEDGE_INDEX.json"], check=True)
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_index.py"), d],
        capture_output=True, text=True, timeout=30)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    check("knowledge index не обещает recovery локального untracked-файла",
          p.returncode == 1 and "path is not Git-tracked and recoverable" in p.stdout,
          out, "cloud/AWS recall needs tracked knowledge or a tracked recovery pointer")
    shutil.rmtree(d, ignore_errors=True)


def t_600_knowledge_index_rejects_partial_directory_and_local_symlink():
    """A tracked child or symlink is not proof that the addressed corpus recovers."""
    import json
    d = base({"knowledge/tracked.md": "tracked\n",
              "knowledge/local-only.md": "local\n"})
    index = knowledge_index()
    index["routes"][0]["paths"] = ["knowledge"]
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(index, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "KNOWLEDGE_INDEX.json",
                    "knowledge/tracked.md"], check=True)
    directory = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_index.py"), d],
        capture_output=True, text=True, timeout=30)
    os.symlink("local-only.md", os.path.join(d, "knowledge", "pointer.md"))
    index["routes"][0]["paths"] = ["knowledge/pointer.md"]
    with open(os.path.join(d, "KNOWLEDGE_INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(index, f)
    subprocess.run(["git", "-C", d, "add", "KNOWLEDGE_INDEX.json",
                    "knowledge/pointer.md"], check=True)
    symlink = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_index.py"), d],
        capture_output=True, text=True, timeout=30)
    out = Vyvod(directory.stdout + directory.stderr + symlink.stdout + symlink.stderr, 0)
    check("knowledge index не принимает частичный каталог и local-only symlink",
          directory.returncode == 1 and "path must resolve to a file" in directory.stdout
          and symlink.returncode == 1
          and "symlink target is not Git-tracked and recoverable" in symlink.stdout,
          out, "every routed file or pointer target must recover in a fresh clone")
    shutil.rmtree(d, ignore_errors=True)


def t_600_shadow_manifest_does_not_preempt_owner_acceptance():
    """A shadow candidate must not silently become authoritative by existing."""
    import json
    d = base({"README.md": "fixture\n"})
    legacy = {"schema": 1, "supported_agents": ["codex", "claude"], "skills": []}
    shadow = {"schema": 1, "supported_agents": ["codex", "claude"],
              "roles": [], "skills": []}  # deliberately missing role_posture
    with open(os.path.join(d, ".kb-skills.json"), "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(shadow, f)
    default = run_skills(d)
    explicit = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_skills.py"), d,
         "--registry", os.path.join(d, "PROJECT_ROLES.json")],
        capture_output=True, text=True, timeout=30)
    out = Vyvod(str(default) + explicit.stdout + explicit.stderr, default.code)
    check("shadow role manifest не переключает проект до приёмки владельца",
          default.code == 0 and "SHADOW_ROLE_REGISTRY" in default
          and explicit.returncode == 1 and "requires role_posture" in explicit.stdout,
          out, "legacy stays authoritative until it becomes a superseded pointer")
    shutil.rmtree(d, ignore_errors=True)


def t_600_legacy_role_address_forwards_without_second_canon():
    """The v6 checker follows the old address without keeping a stale copy."""
    import json
    d = base({"README.md": "fixture\n"})
    visible = {
        "schema": 1,
        "supported_agents": ["codex", "claude"],
        "role_posture": {"status": "not-applicable", "rationale": "fixture"},
        "roles": [],
        "skills": [],
    }
    with open(os.path.join(d, "PROJECT_ROLES.json"), "w", encoding="utf-8") as f:
        json.dump(visible, f)
    with open(os.path.join(d, ".kb-skills.json"), "w", encoding="utf-8") as f:
        f.write(skill_text("assets/templates/legacy-role-registry.json"))
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    ".kb-skills.json"], check=True)
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_skills.py"), d,
         "--registry", os.path.join(d, ".kb-skills.json")],
        capture_output=True, text=True, timeout=30)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    check("v6 checker разыменовывает старый role registry адрес в новый канон",
          p.returncode == 0
          and "ROLE_REGISTRY_MOVED: .kb-skills.json -> PROJECT_ROLES.json" in p.stdout
          and "role posture: not-applicable" in p.stdout,
          out, "a tombstone preserves navigation without maintaining duplicate rules")
    shutil.rmtree(d, ignore_errors=True)


def environment_registry(provider_status="unavailable", provider_kind="managed-connector"):
    provider = {"status": provider_status, "kind": provider_kind}
    if provider_status == "accepted":
        provider.update({
            "provider": "mail-provider", "identity": "owner-mailbox",
            "scope": "read-only", "authority": "current task",
            "validation": "read-only probe", "accepted_at": "2026-08-13",
        })
    return {
        "schema": 1,
        "cloud_policy": "allowed",
        "supported_runtimes": ["codex-local", "claude-local", "codex-cloud"],
        "capabilities": [{
            "id": "email.personal.read",
            "purpose": "read task-relevant mail",
            "required_when": "mail request",
            "required_by_default": False,
            "sensitivity": "private",
            "failure_policy": "fail-closed",
            "prohibited_actions": ["send without authority"],
            "providers": {"codex-cloud": provider},
            "fallback": "owner export",
        }],
    }


def environment_fixture(registry):
    import json
    d = base({
        "AGENTS.md": "# portable entry\nproject root: .\n",
        "CLAUDE.md": "# portable entry\nproject root: .\n",
        ".kb-environments.json": json.dumps(registry),
    })
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "remote", "add", "origin",
                    "https://example.invalid/owner/project.git"], check=True)
    subprocess.run(["git", "-C", d, "add", "AGENTS.md", "CLAUDE.md",
                    ".kb-environments.json"], check=True)
    return d


def run_environments(root, *args):
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_environments.py"), root, *args],
        capture_output=True, text=True, timeout=120)
    return Vyvod(p.stdout + p.stderr, p.returncode)


def t_runtime_capability_template_separates_identity_scope_and_authority():
    """13.08: local mail access was nearly inferred for an isolated cloud task."""
    import json
    data = json.loads(skill_text("assets/templates/kb-environments.json"))
    item = data["capabilities"][0]
    cloud = item["providers"]["codex-cloud"]
    module = skill_text("references/modules.md")
    out = Vyvod(str(item) + "\n" + module, 0)
    check("runtime registry separates logical capability from each provider",
          item["id"] == "email.personal.read"
          and all(cloud.get(field) for field in
                  ("status", "kind", "provider", "identity", "scope",
                   "authority", "validation"))
          and "Одинаковое имя сервера не доказывает" in module
          and "не на каждый обычный вопрос" in module,
          out, "logical email capability; per-runtime identity/scope/authority and routed audit")


def t_keychain_is_storage_canon_not_blanket_non_disclosure():
    """14.08: owner permits task-scoped reveal; Git still stores only the locator."""
    module = skill_text("references/modules.md")
    patterns = skill_text("references/patterns.md")
    out = Vyvod(module + "\n" + patterns, 0)
    check("Keychain rule separates storage, task use and disclosure traces",
          "Это правило хранения, а не запрет агенту" in module
          and "tool output, shell history или чат" in module
          and "Always Allow" in module
          and "Cloud runtime локальный\nKeychain по-прежнему не наследует" in module
          and "агент может получить значение" in patterns
          and "ключ или пароль расшифровки" in patterns.lower()
          and "канон остаётся в Keychain/secret store" in patterns
          and "Разовый перенос существующего plaintext" in patterns
          and "ставится на ротацию/отзыв" in patterns,
          out, "Git keeps a locator; authorized local use is allowed and auditable")


def t_620_apply_does_not_replay_historical_cleanup():
    """6.2 applies the current contract directly instead of replaying old duties."""
    d = base({"NOW.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nkb_standard_version: 5.3\n"})
    out = run("kb_apply.py", d)
    check("6.2 application does not replay historical cleanup rows",
          "[6.2]" in out
          and "[5.4]" not in out
          and "credential cleanup" not in out,
          out, "current contract line replaces a per-patch historical replay")
    shutil.rmtree(d, ignore_errors=True)


def t_55_agent_vault_keeps_read_simple_and_actions_gated():
    """14.08: owner chose one system-wide local read profile, not per-project ACLs."""
    module = skill_text("references/modules.md")
    skill = skill_text("SKILL.md")
    start = module.index("## `agent_vault_and_external_actions`")
    recipe = module[start:]
    out = Vyvod(recipe + "\n" + skill, 0)
    check("agent vault grants broad local read without broad purchase authority",
          "одна общая системная граница, не разрешения по\n   проектам" in recipe
          and "не добавляет обязательного\nproject registry" in recipe
          and "чтение из принятого сейфа не требует отдельного вопроса" in recipe
          and "merchant/допустимый класс и максимальную общую сумму" in recipe
          and "повторный вопрос перед оплатой не нужен" in recipe
          and "3-D Secure" in recipe and "owner handoff" in recipe
          and "локальный Keychain не существует в контейнере" in recipe
          and "пароль" in skill and "карточка" in skill,
          out, "one accepted local vault; current task gates use; irreversible challenge hands off")


def t_55_agent_vault_does_not_make_generic_shell_a_secret_broker():
    """A one-time convenience grant must not silently authorize every executable."""
    module = skill_text("references/modules.md")
    start = module.index("## `agent_vault_and_external_actions`")
    recipe = module[start:]
    out = Vyvod(recipe, 0)
    check("agent vault is mediated by an accepted helper",
          "Не выдавать то же\n   право универсальному shell, Terminal или произвольному процессу" in recipe
          and "Субагенты обращаются через тот же\n   принятый helper" in recipe
          and "не вывести список или значения всего сейфа" in recipe,
          out, "system-wide for Codex tasks does not mean system-wide for arbitrary code")


def t_55_one_time_keychain_enrollment_builds_a_derived_vault():
    """Keychain stays canonical; owner does not retype existing values."""
    module = skill_text("references/modules.md")
    start = module.index("### Разовое первичное наполнение")
    recipe = module[start:module.index("По прямой задаче владельца", start)]
    compact = " ".join(recipe.split())
    out = Vyvod(recipe, 0)
    check("one-time Keychain enrollment builds a replaceable derived vault",
          "один раз проверить" in compact
          and "повторно не вводит" in compact
          and "все логины и пароли к медицинским системам" in compact
          and "оканчивающаяся на 7011" in compact
          and "не выводя значения" in compact
          and "не менять и не удалять исходную запись" in compact
          and "никогда не становится каноном" in compact
          and "Карты не импортировать массово" in compact
          and "без секретов" in compact
          and "расходуется после одного enrollment-pass" in compact
          and "повторный просмотр личного Keychain требует новой" in compact,
          out, "Keychain is source; owner-scoped enrollment creates an erasable cache")


def t_56_modern_passwords_enrollment_is_owner_mediated_and_trace_free():
    """A working AutoFill credential can be unreachable to exact Keychain lookup."""
    module = skill_text("references/modules.md")
    start = module.index("Современная запись Apple Passwords")
    recipe = module[start:module.index("Такое разрешение можно дать", start)]
    compact = " ".join(recipe.split())
    out = Vyvod(recipe, 0)
    check("modern Passwords uses one owner-mediated derived-vault handoff",
          "source недоступен этому provider" in compact
          and "не отсутствие credential" in compact
          and "Не создавать ради обхода второй generic-password source" in compact
          and "alias, ожидаемые domain/account и `cloud_policy`" in compact
          and "stdout, clipboard, argv/env, файл или лог" in compact
          and "Cancel, пустой выбор, mismatch или отказ не создают запись" in compact
          and "системным Passwords AutoFill" in compact
          and "ручная передача через чат не становится fallback" in compact
          and "Refresh такой записи снова требует owner-mediated UI" in compact,
          out, "one selected modern credential reaches the vault without a secret trace")


def t_optional_cloud_connector_does_not_block_repo_work():
    """13.08: missing connector must block its task, not all Git work."""
    d = environment_fixture(environment_registry())
    out = run_environments(d, "--runtime", "codex-cloud")
    check("optional unavailable cloud capability leaves portable project ready",
          out.code == 0 and "optional capabilities unavailable here" in out
          and "errors=0" in out,
          out, "optional mail is named unavailable without blocking repo work")
    shutil.rmtree(d, ignore_errors=True)


def t_required_cloud_connector_fails_closed():
    """13.08: 'check my mail' requires an accepted provider in this runtime."""
    d = environment_fixture(environment_registry("pending"))
    out = run_environments(d, "--runtime", "codex-cloud",
                           "--require", "email.personal.read")
    check("required pending cloud mail capability fails closed",
          out.code == 1 and "required but status is pending" in out,
          out, "no accepted provider means BLOCKED, not a claimed mailbox check")
    shutil.rmtree(d, ignore_errors=True)


def t_host_only_mcp_cannot_be_accepted_as_cloud_provider():
    """13.08: a Mac-local MCP declaration is not cloud acceptance evidence."""
    d = environment_fixture(environment_registry("accepted", "local-mcp"))
    out = run_environments(d, "--runtime", "codex-cloud",
                           "--require", "email.personal.read")
    check("host-only MCP cannot masquerade as Codex Cloud provider",
          out.code == 1 and "codex-cloud cannot accept host-only kind local-mcp" in out,
          out, "cloud needs a separately accepted managed connector or remote MCP")
    shutil.rmtree(d, ignore_errors=True)


def t_shared_boot_rejects_absolute_local_root_consistently():
    """13.08: service-layer exact-root wording contradicted the portable template."""
    registry = environment_registry()
    d = environment_fixture(registry)
    entry = os.path.join(d, "AGENTS.md")
    with open(entry, "w", encoding="utf-8") as f:
        f.write("# shared entry\ncanonical root: /" + "Users/example/project\n")
    subprocess.run(["git", "-C", d, "add", "AGENTS.md"], check=True)
    out = run_environments(d, "--runtime", "codex-local")
    service = skill_text("references/service-layer.md")
    template = skill_text("assets/templates/CLAUDE.md")
    check("shared boot canon uses a repo-relative root consistently",
          out.code == 1
          and "shared boot canon must use a repo-relative root" in out
          and "переносимый repo-relative root" in service
          and "project root: ." in service
          and "project root: ." in template,
          out, "absolute local path is acceptance evidence, not a cloud-shared instruction")
    shutil.rmtree(d, ignore_errors=True)


def t_claude_cloud_is_a_first_class_runtime():
    """13.08: an accepted claude.ai connector must not be mislabeled as local/Codex."""
    registry = environment_registry("accepted")
    registry["supported_runtimes"].append("claude-cloud")
    provider = registry["capabilities"][0]["providers"].pop("codex-cloud")
    registry["capabilities"][0]["providers"]["claude-cloud"] = provider
    d = environment_fixture(registry)
    out = run_environments(d, "--runtime", "claude-cloud",
                           "--require", "email.personal.read")
    check("claude-cloud provider is declared and accepted independently",
          out.code == 0
          and "accepted in claude-cloud" in out
          and "errors=0" in out,
          out, "claude.ai is neither claude-local nor codex-cloud")
    shutil.rmtree(d, ignore_errors=True)


def t_620_update_does_not_replay_old_optional_capabilities():
    """A direct contract migration does not reopen historical choices."""
    d = base({"NOW.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nkb_standard_version: 4.18\n"})
    out = run("kb_apply.py", d)
    check("обновление не переоткрывает старые опциональные возможности",
          "[6.2]" in out
          and "[4.19]" not in out
          and "НОВЫХ ВОЗМОЖНОСТЕЙ, ТРЕБУЮЩИХ РЕШЕНИЯ, НЕТ" in out,
          out, "the project considers choices declared by the current contract line")
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
    entry = skill_text("SKILL.md")
    ref = skill_text("references/service-layer.md")
    tpl = skill_text("assets/templates/CLAUDE.md")
    updater = skill_text("scripts/kb_update.py")
    out = Vyvod(entry + "\n" + ref + "\n" + tpl + "\n" + updater, 0)
    check("сервисный контур использует public и исключает lab-symlink",
          "--public --fast --сделать" in ref
          and "GitHub public https://github.com/sugestr/kb-architect" in tpl
          and "не каналом установки" in ref
          and "git ls-remote" in ref
          and "установленного локального `SKILL.md`" in ref
          and "не открывает public README/SKILL вручную" in ref
          and "до current state" in ref
          and "«Обнови скилл базы знаний»" in entry
          and "«Обнови скилл базы знаний»" in tpl
          and "не report-only" in entry
          and "UPDATE_STATUS=INSTALLED" in updater
          and "REREAD_INSTALLED_ENTRY" in updater
          and "PUBLIC_REPOSITORY" in updater,
          out, "public stable update precedes project work and emits a session action")


def t_fast_update_checks_remote_even_with_fresh_receipt():
    """A recent receipt may save a clone, but cannot prove a newer release absent."""
    import contextlib
    import importlib.util
    import io
    import json

    home = tempfile.mkdtemp(prefix="kbtest-fast-home-")
    destination = os.path.join(home, ".codex", "skills", "kb-architect")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copytree(SKILL_ROOT, destination)
    spec = importlib.util.spec_from_file_location(
        "kb_update_fixture", os.path.join(HERE, "kb_update.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cache = os.path.join(home, "update-state.json")
    with open(cache, "w", encoding="utf-8") as stream:
        json.dump({
            "schema": 1,
            "repository": module.PUBLIC_REPOSITORY,
            "remote_head": "fixture-head",
            "version": module.versiya(destination),
            "fingerprint": module.fingerprint(destination),
            "checked_at_epoch": time.time(),
        }, stream)
    old_cache = os.environ.get("KB_ARCHITECT_UPDATE_CACHE")
    module.MESTA = [("Codex", destination)]
    calls = []
    module.public_head = lambda: (calls.append("ls-remote") or
                                  ("fixture-head", None))
    try:
        os.environ["KB_ARCHITECT_UPDATE_CACHE"] = cache
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = module.fast_public_check(24)
    finally:
        if old_cache is None:
            os.environ.pop("KB_ARCHITECT_UPDATE_CACHE", None)
        else:
            os.environ["KB_ARCHITECT_UPDATE_CACHE"] = old_cache
    out = Vyvod(stream.getvalue(), code)
    check("fresh receipt still probes public HEAD but skips clone when unchanged",
          out.code == 0 and calls == ["ls-remote"]
          and "public HEAD не изменился" in out
          and "UPDATE_STATUS=CURRENT" in out
          and "полный gate" not in out,
          out, "one cheap remote proof replaces the stale TTL assumption")
    shutil.rmtree(home, ignore_errors=True)


def t_fast_update_detects_new_release_despite_fresh_receipt():
    """The 6.0 receipt must not mask a patch published one minute later."""
    import contextlib
    import importlib.util
    import io
    import json

    home = tempfile.mkdtemp(prefix="kbtest-fast-new-head-")
    destination = os.path.join(home, ".codex", "skills", "kb-architect")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copytree(SKILL_ROOT, destination)
    spec = importlib.util.spec_from_file_location(
        "kb_update_new_head_fixture", os.path.join(HERE, "kb_update.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cache = os.path.join(home, "update-state.json")
    with open(cache, "w", encoding="utf-8") as stream:
        json.dump({
            "schema": 1,
            "repository": module.PUBLIC_REPOSITORY,
            "remote_head": "old-head",
            "version": module.versiya(destination),
            "fingerprint": module.fingerprint(destination),
            "checked_at_epoch": time.time(),
        }, stream)
    old_cache = os.environ.get("KB_ARCHITECT_UPDATE_CACHE")
    module.MESTA = [("Codex", destination)]
    module.public_head = lambda: ("new-head", None)
    try:
        os.environ["KB_ARCHITECT_UPDATE_CACHE"] = cache
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = module.fast_public_check(24)
    finally:
        if old_cache is None:
            os.environ.pop("KB_ARCHITECT_UPDATE_CACHE", None)
        else:
            os.environ["KB_ARCHITECT_UPDATE_CACHE"] = old_cache
    out = Vyvod(stream.getvalue(), 0 if code is None else code)
    check("fresh receipt cannot hide a newly published stable",
          code is None and "запускается полный gate" in out
          and "UPDATE_STATUS=CURRENT" not in out,
          out, "changed remote HEAD must enter the validated clone/install gate")
    shutil.rmtree(home, ignore_errors=True)


def t_natural_update_enters_project_action_mode():
    """A project update request continues into reversible work, not another report."""
    import contextlib
    import importlib.util
    import io

    fixture = tempfile.mkdtemp(prefix="kbtest-update-action-")
    skill = os.path.join(fixture, "skill")
    project = os.path.join(fixture, "project")
    os.makedirs(os.path.join(skill, "scripts"))
    os.makedirs(project)
    with open(os.path.join(skill, "scripts", "kb_apply.py"), "w",
              encoding="utf-8") as stream:
        stream.write("import sys\nsys.exit(1)\n")
    spec = importlib.util.spec_from_file_location(
        "kb_update_action_fixture", os.path.join(HERE, "kb_update.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    action_stream = io.StringIO()
    with contextlib.redirect_stdout(action_stream):
        action_code = module.apply_project(skill, project, action_mode=True)
    inspect_stream = io.StringIO()
    with contextlib.redirect_stdout(inspect_stream):
        inspect_code = module.apply_project(skill, project, action_mode=False)
    out = Vyvod(action_stream.getvalue() + inspect_stream.getvalue(), 0)
    check("project update distinguishes action-first from standalone inspection",
          action_code == 1 and inspect_code == 1
          and "SESSION_ACTION=APPLY_PROJECT_DELTA_NOW" in action_stream.getvalue()
          and "Команда обновления — не report-only" in action_stream.getvalue()
          and "SESSION_STATE=PROJECT_DELTA_OPEN" in inspect_stream.getvalue()
          and "APPLY_PROJECT_DELTA_NOW" not in inspect_stream.getvalue(),
          out, "--do supplies an executable continuation while audit stays read-only")
    shutil.rmtree(fixture, ignore_errors=True)


def t_full_update_report_only_never_calls_stale_install_current():
    """A validated source plus a stale install is AVAILABLE, not CURRENT."""
    import contextlib
    import importlib.util
    import io
    from types import SimpleNamespace

    fixture = tempfile.mkdtemp(prefix="kbtest-update-report-only-")
    source = os.path.join(fixture, "source")
    destination = os.path.join(fixture, "installed")
    os.makedirs(source)
    os.makedirs(destination)
    with open(os.path.join(source, "SKILL.md"), "w", encoding="utf-8") as stream:
        stream.write('---\nmetadata:\n  version: "6.0.2"\n---\nsource\n')
    with open(os.path.join(destination, "SKILL.md"), "w", encoding="utf-8") as stream:
        stream.write('---\nmetadata:\n  version: "6.0.1"\n---\ninstalled\n')
    spec = importlib.util.spec_from_file_location(
        "kb_update_report_only_fixture", os.path.join(HERE, "kb_update.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MESTA = [("Codex", destination)]
    module.prepare_source = lambda _src, _do: (True, "fixture source", None)
    module.test_skill = lambda _src: (True, "")
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = module.update_from_source(
            source, SimpleNamespace(do_update=False), "fixture")
    out = Vyvod(stream.getvalue(), code)
    check("full report-only gate cannot label a stale installation CURRENT",
          out.code == 1 and "UPDATE_STATUS=UPDATE_AVAILABLE" in out
          and "SESSION_ACTION=RERUN_WITH_DO" in out
          and "UPDATE_STATUS=CURRENT" not in out,
          out, "observation mode exposes the open install action instead of a false pass")
    shutil.rmtree(fixture, ignore_errors=True)


def t_legacy_update_ttl_option_remains_parse_compatible():
    """6.0/6.0.1 project commands may keep TTL while it no longer skips remote proof."""
    import contextlib
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location(
        "kb_update_legacy_ttl_fixture", os.path.join(HERE, "kb_update.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = []
    def fast_fixture(ttl):
        seen.append(ttl)
        print("UPDATE_STATUS=CURRENT")
        return 0
    module.fast_public_check = fast_fixture
    old_argv = sys.argv
    stream = io.StringIO()
    try:
        sys.argv = ["kb_update.py", "--public", "--fast", "--ttl-hours", "24"]
        with contextlib.redirect_stdout(stream):
            code = module.main()
    finally:
        sys.argv = old_argv
    out = Vyvod(stream.getvalue(), code)
    check("legacy --ttl-hours is accepted but still enters remote fast check",
          out.code == 0 and seen == [24.0], out,
          "compatibility keeps old commands runnable without restoring TTL freshness")


def t_public_receipt_write_failure_suppresses_success_status():
    """Validated bytes without a durable public receipt remain UNKNOWN."""
    import contextlib
    import importlib.util
    import io
    from types import SimpleNamespace

    fixture = tempfile.mkdtemp(prefix="kbtest-update-receipt-failure-")
    source = os.path.join(fixture, "source")
    destination = os.path.join(fixture, "installed")
    os.makedirs(source)
    with open(os.path.join(source, "SKILL.md"), "w", encoding="utf-8") as stream:
        stream.write('---\nmetadata:\n  version: "6.0.2"\n---\nidentical\n')
    shutil.copytree(source, destination)
    spec = importlib.util.spec_from_file_location(
        "kb_update_receipt_failure_fixture", os.path.join(HERE, "kb_update.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MESTA = [("Codex", destination)]
    module.prepare_source = lambda _src, _do: (True, "fixture source", None)
    module.test_skill = lambda _src: (True, "")
    module.record_public_receipt = lambda _src: "fixture cache is read-only"
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = module.update_from_source(
            source, SimpleNamespace(do_update=False), "fixture", record_receipt=True)
    out = Vyvod(stream.getvalue(), 0)
    check("failed public receipt cannot coexist with CURRENT or INSTALLED",
          code == 2 and "UPDATE_STATUS=UNKNOWN" in out
          and "UPDATE_STATUS=CURRENT" not in out
          and "UPDATE_STATUS=INSTALLED" not in out,
          out, "a cache-write failure replaces the pass instead of merely annotating it")
    shutil.rmtree(fixture, ignore_errors=True)


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
          and "разрешённого проектом" in defect, out,
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


def t_512_report_inbox_is_a_direct_existing_directory():
    """24.08, tg-archive: строка указывала на inventory, где адреса не было."""
    indirect = base({
        "NOW.md": NOW_OK,
        "config/inventory.md": "# runtime inventory\n\nАдреса отчётов здесь нет.\n",
        "CLAUDE.md": "# правила\n\nвход: NOW.md\n"
                     "сервисный контур kb-architect: принят\n"
                     "инбокс отчётов: config/inventory.md\n",
    })
    out = run("kb_check.py", indirect)
    check("файл-указатель не выдаётся за каталог доставки отчёта",
          "ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН" in out
          and "указывает на файл" in out,
          out, "точный report target обязан быть существующим каталогом")
    shutil.rmtree(indirect, ignore_errors=True)

    missing = base({
        "NOW.md": NOW_OK,
        "CLAUDE.md": "# правила\n\nвход: NOW.md\n"
                     "сервисный контур kb-architect: принят\n",
    })
    out = run("kb_check.py", missing)
    check("принятый сервисный контур без report inbox не молчит",
          "ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН" in out
          and "прямой адрес" in out,
          out, "принятие contour делает route проверяемым обязательством проекта")
    shutil.rmtree(missing, ignore_errors=True)

    direct = base({
        "NOW.md": NOW_OK,
        "reports/.keep": "",
        "CLAUDE.md": "# правила\n\nвход: NOW.md\n"
                     "сервисный контур kb-architect: принят\n"
                     "инбокс отчётов: reports\n",
    })
    out = run("kb_check.py", direct)
    check("существующий прямой report inbox проходит проверку",
          out.code == 0 and "инбокс отчётов (reports)" in out
          and "ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН" not in out,
          out, "direct repo-relative directory is accepted")
    shutil.rmtree(direct, ignore_errors=True)


def t_513_invalid_parent_git_marker_is_not_a_repository():
    """24.08, два Codex Cloud scratch-контейнера: у `/tmp` либо `/workspace`
    находился служебный каталог `.git`, который не был Git-репозиторием.
    Поиск по одному имени маркера объявлял вложенный fixture репозиторием,
    проверка веток закономерно падала и превращала два честных теста в 77/79.
    Маркер — только кандидат; Git обязан подтвердить настоящий top-level.
    """
    outer = tempfile.mkdtemp(prefix="kbtest-cloud-scratch-")
    os.makedirs(os.path.join(outer, ".git"))
    project = os.path.join(outer, "project")
    os.makedirs(os.path.join(project, "reports"))
    with open(os.path.join(project, "NOW.md"), "w", encoding="utf-8") as f:
        f.write(NOW_OK)
    with open(os.path.join(project, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# rules\n\nentry: NOW.md\n"
                "kb-architect service layer: accepted\n"
                "report inbox: reports\n")

    out = run("kb_check.py", project)
    check("служебный invalid .git над scratch не становится Git root",
          out.code == 0
          and "неслитые ветки — неприменимо (репозитория нет)" in out
          and "инбокс отчётов (reports)" in out
          and "НЕ ПРОВЕРЕН" not in out,
          out, "git rev-parse, а не имя .git, подтверждает repository scope")
    shutil.rmtree(outer, ignore_errors=True)


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


def t_git_linked_worktree():
    """Шесть project-skill аудитов 11.08: linked worktree имеет .git-файл,
    но kb_due.py объявлял его нерепозиторием. Это поддерживаемый режим
    параллельных писателей, поэтому диагностика обязана видеть Git."""
    d = base({"NOW.md": NOW_OK, "CLAUDE.md": "# правила\n\nвход: NOW.md\n"})
    subprocess.run(["git", "init", "-q", d], capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "test@example.invalid"],
                   capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "kb test"],
                   capture_output=True)
    subprocess.run(["git", "-C", d, "add", "NOW.md", "CLAUDE.md"],
                   capture_output=True)
    subprocess.run(["git", "-C", d, "commit", "-q", "-m", "fixture"],
                   capture_output=True)
    parent = tempfile.mkdtemp(prefix="kbtest-worktree-")
    worktree = os.path.join(parent, "linked")
    subprocess.run(["git", "-C", d, "worktree", "add", "-q", "-b", "audit", worktree],
                   capture_output=True)
    out = run("kb_due.py", worktree)
    check("linked worktree не объявляется «без репозитория»",
          os.path.isfile(os.path.join(worktree, ".git"))
          and "git-репозитория нет" not in out, out,
          ".git-файл распознаётся так же, как .git-каталог")
    subprocess.run(["git", "-C", d, "worktree", "remove", "--force", worktree],
                   capture_output=True)
    shutil.rmtree(parent, ignore_errors=True)
    shutil.rmtree(d, ignore_errors=True)


def t_apply_ignores_marker_syntax_examples():
    """Отчёт local MCP 11.08: описание синтаксиса `⟦Д: …⟧` в строках
    4.17/4.21 превращалось в два фиктивных обязательных действия."""
    d = base({"NOW.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nkb_standard_version: 4.16\n"})
    out = run("kb_apply.py", d)
    check("пример маркера не становится действием проекта",
          "[4.17] …" not in out and "[4.21] …" not in out
          and "[5.0]" not in out and "[6.2]" in out
          and "ТРЕБУЮТ ДЕЙСТВИЯ" in out, out,
          "parser skips placeholders and shows only the current contract line")
    shutil.rmtree(d, ignore_errors=True)


def vetka_fixture(files_in_branch, also_on_main=None):
    """Репозиторий с одной неслитой веткой. Возвращает путь к корню."""
    d = base({"NOW.md": NOW_OK, "CLAUDE.md": "# правила\n\nвход: NOW.md\n",
              "kanon/staryy.md": "# канон\n\nтекст\n"})
    git = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True)
    subprocess.run(["git", "init", "-q", "-b", "main", d], capture_output=True)
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "kb test")
    git("add", "-A")
    git("commit", "-q", "-m", "fixture")
    git("checkout", "-q", "-b", "oblachnaya")
    for name, text in files_in_branch.items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    git("add", "-A")
    git("commit", "-q", "-m", "работа облачной сессии")
    git("checkout", "-q", "main")
    for name, text in (also_on_main or {}).items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    if also_on_main:
        git("add", "-A")
        git("commit", "-q", "-m", "то же содержимое в каноне")
    return d


def t_58_unmerged_branch_is_a_finding():
    """Отчёт 18.08: коммит и push состоялись, ветка не слита, и 32 файла
    доказательств четыре дня отсутствовали в каноне при чистом дереве."""
    d = vetka_fixture({"dokazatelstva/CLAIMS.md": "# требования\n\nRTA-EXCESS 1580\n"})
    out = run("kb_check.py", d)
    check("неслитая ветка с содержимым вне канона становится находкой",
          "НЕ СЛИТО В КАНОН" in out and "oblachnaya" in out
          and "dokazatelstva/CLAIMS.md" in out
          and "неслитые ветки (1)" in out, out,
          "чистое рабочее дерево не доказывает, что работа в каноне")
    shutil.rmtree(d, ignore_errors=True)


def t_58_moved_directory_is_not_a_loss():
    """Первый счёт того же случая назвал 27 потерянных путей, из которых
    потерян был один файл: считать надо по имени и содержимому, не по пути."""
    polis = "# полис\n\nпокрытие misfuelling, пункт 3(g)\n"
    d = vetka_fixture({"vetka/booking-polis.md": polis},
                      also_on_main={"kanon/policy-document.md": polis})
    out = run("kb_check.py", d)
    check("переезд и переименование не выдаются за потерю содержимого",
          "НЕ СЛИТО В КАНОН" not in out
          and "СОДЕРЖИМОЕ УЖЕ В КАНОНЕ" in out, out,
          "тот же документ под другим именем — не потеря; путь и имя этого не показывают")
    shutil.rmtree(d, ignore_errors=True)


def t_58_lookup_searches_unmerged_refs():
    """Полис лежал в неслитой ветке, поиск ответил «в базе нет», и документ
    выкачали и разобрали заново — вместе с неверной оценкой владельцу."""
    d = vetka_fixture({"dokazatelstva/polis.md": "# полис\n\nпокрытие misfuelling\n"})
    p = subprocess.run([sys.executable, os.path.join(HERE, "kb_lookup.py"),
                        d, "misfuelling"],
                       capture_output=True, text=True, timeout=120)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    check("поиск смотрит в неслитые ветки прежде, чем сказать «этого нет»",
          "НЕ НАЙДЕНО" not in out and "ЕСТЬ ВНЕ КАНОНА" in out
          and "polis.md" in out, out,
          "вывод об отсутствии обязан покрывать доставленное, но не слитое")
    shutil.rmtree(d, ignore_errors=True)


def t_515_material_interpretation_stays_red_until_all_candidates_reviewed():
    """26.08: causal summary won over a limiting fact because lookup was skipped
    and the omission looked exactly like a completed check."""
    timeline = "# limit\n\nLIMIT_JUNE_CONTEXT predates the therapy\n"
    d = base({
        "canon/cause.md": "# hypothesis\n\nTHERAPY_ONLY explains the change\n",
        "canon/timeline.md": timeline,
    })
    receipt = os.path.join(d, "_work", "evidence.json")
    begin = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), d,
         "--claim", "therapy caused the whole change", "--receipt", receipt,
         "--support", "THERAPY_ONLY", "--challenge", "LIMIT_JUNE_CONTEXT"],
        capture_output=True, text=True, timeout=120)
    data = __import__("json").load(open(receipt, encoding="utf-8"))
    by_path = {item["path"]: item["id"] for item in data["candidates"]}
    support_id = by_path["canon/cause.md"]
    limit_id = by_path["canon/timeline.md"]
    timeline_path = os.path.join(d, "canon", "timeline.md")
    with open(timeline_path, "a", encoding="utf-8") as f:
        f.write("NEW_CONTEXT arrived after lookup\n")
    stale_close = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), d,
         "--finalize", receipt, "--outcome", "qualified",
         "--supports", support_id, "--limits", limit_id,
         "--reason", "review belongs to a stale corpus"],
        capture_output=True, text=True, timeout=120)
    with open(timeline_path, "w", encoding="utf-8") as f:
        f.write(timeline)
    partial_close = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), d,
         "--finalize", receipt, "--outcome", "supported",
         "--supports", support_id, "--reason", "only the convenient file reviewed"],
        capture_output=True, text=True, timeout=120)
    false_close = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), d,
         "--finalize", receipt, "--outcome", "supported",
         "--supports", support_id, "--limits", limit_id,
         "--reason", "both files reviewed"],
        capture_output=True, text=True, timeout=120)
    close = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), d,
         "--finalize", receipt, "--outcome", "qualified",
         "--supports", support_id, "--limits", limit_id,
         "--reason", "the earlier context limits the causal attribution"],
        capture_output=True, text=True, timeout=120)
    final = __import__("json").load(open(receipt, encoding="utf-8"))
    out = Vyvod(begin.stdout + begin.stderr + stale_close.stdout + stale_close.stderr
                + partial_close.stdout
                + partial_close.stderr + false_close.stdout
                + false_close.stderr + close.stdout + close.stderr,
                close.returncode)
    check("существенный вывод не проходит без evidence/contradiction receipt",
          begin.returncode == 1
          and "EVIDENCE_GATE=REVIEW_REQUIRED" in begin.stdout
          and data["status"] == "review_required"
          and stale_close.returncode == 2
          and "база изменилась после поиска" in stale_close.stderr
          and partial_close.returncode == 2
          and "не прочитаны/не классифицированы" in partial_close.stderr
          and false_close.returncode == 2
          and close.returncode == 0
          and "EVIDENCE_GATE=QUALIFIED" in close.stdout
          and final["status"] == "qualified"
          and final["review"]["limit_ids"] == [limit_id],
          out, "snapshot-bound gate; every candidate classified; limit forbids supported")
    shutil.rmtree(d, ignore_errors=True)


def t_58_no_repository_is_named_not_silently_passed():
    """Проверка, которая не выполнилась, обязана отличаться от пройденной."""
    d = base({"NOW.md": NOW_OK, "CLAUDE.md": "# правила\n\nвход: NOW.md\n"})
    out = run("kb_check.py", d)
    check("без репозитория неприменимость названа, а не молчит",
          "неслитые ветки — неприменимо" in out, out,
          "строка «Проверено» называет объём выполненного, включая пропуски")
    shutil.rmtree(d, ignore_errors=True)


def t_59_outgoing_message_in_own_inbox_is_a_finding():
    """18.08: лаборатория положила задание проекту в свой же inbox и сказала
    «передано»; адресат проверил свой инбокс и нашёл его пустым."""
    msg = ("---\ntype: agent-message\nmessage_id: m1\n"
           "from_project: moya-baza\nto_project: chuzhoy-proekt\n"
           "delivery_state: delivered\n---\n\n# задание\n")
    vhod = ("---\ntype: agent-message\nmessage_id: m2\n"
            "from_project: chuzhoy-proekt\nto_project: moya-baza\n"
            "delivery_state: delivered\n---\n\n# входящее\n")
    d = tempfile.mkdtemp(prefix="kbtest-") + "/moya-baza"
    os.makedirs(d)
    for name, text in {"NOW.md": NOW_OK,
                       "CLAUDE.md": "# правила\n\nвход: NOW.md\n",
                       "_inbox/2026-08-18_zadanie.md": msg,
                       "_inbox/2026-08-18_vhodyashchee.md": vhod}.items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    out = run("kb_check.py", d)
    check("исходящее в собственном инбоксе — находка, входящее — нет",
          "ИСХОДЯЩЕЕ В СОБСТВЕННОМ ИНБОКСЕ" in out
          and "zadanie" in out and "vhodyashchee" not in out
          and "адресация инбокса" in out, out,
          "delivery_state: delivered не делает запись у себя доставкой")
    shutil.rmtree(os.path.dirname(d), ignore_errors=True)


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
    shutil.copy2(os.path.join(HERE, "kb_paths.py"), scripts)
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
    """Владелец: обновлять и same-version drift, обратимо и с тестами."""
    home = tempfile.mkdtemp(prefix="kbtest-update-home-")
    source = base({
        "SKILL.md": "---\nname: kb-architect\nmetadata:\n  version: \"9.9\"\n---\n",
        "scripts/test_kb.py": "import sys\nprint('fixture ok')\nsys.exit(0)\n",
    })
    destination = os.path.join(home, ".codex", "skills", "kb-architect")
    os.makedirs(destination)
    with open(os.path.join(destination, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: kb-architect\nmetadata:\n  version: \"9.9\"\n---\nlegacy\n")
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
          "копия обновлена: 9.9 → 9.9" in out
          and "симлинк заменён управляемой копией: 9.9 → 9.9" in out
          and os.path.isdir(backups)
          and len(os.listdir(backups)) == 1
          and os.path.isdir(claude_backups)
          and len(os.listdir(claude_backups)) == 1
          and not os.path.islink(claude_destination)
          and "9.9" in open(os.path.join(destination, "SKILL.md"),
                            encoding="utf-8").read()
          and "legacy" not in open(os.path.join(destination, "SKILL.md"),
                                   encoding="utf-8").read(),
          out, "same version still requires tree parity before skipping")
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(source, ignore_errors=True)


def t_512_update_cycle_cannot_hide_unapplied_project_delta():
    """24.08: tg-archive downloaded releases but stayed declared at 5.3."""
    project = base({
        "NOW.md": NOW_OK,
        "CLAUDE.md": "# rules\n\nkb_standard_version: 5.3\n",
    })
    out = run("kb_apply.py", project)
    service = skill_text("references/service-layer.md")
    template = skill_text("assets/templates/CLAUDE.md")
    combined = Vyvod(str(out) + "\n" + service + "\n" + template, out.code)
    check("доставленная, но неприменённая редакция остаётся машинно видимой",
          out.code == 1
          and "NEEDS_APPLICATION" in out
          and "--project <корень-проекта>" in service
          and "--project <корень-проекта>" in template
          and "код 0 означает" in service,
          combined, "one entry command runs update + apply; stale project exits 1")
    shutil.rmtree(project, ignore_errors=True)


def t_512_update_project_option_really_runs_apply():
    """Команда из service-layer должна исполнять второй шаг, не только описывать."""
    source = base({
        "SKILL.md": skill_text("SKILL.md"),
        "references/releases.md": skill_text("references/releases.md"),
        "scripts/kb_apply.py": skill_text("scripts/kb_apply.py"),
        "scripts/kb_paths.py": skill_text("scripts/kb_paths.py"),
        "scripts/test_kb.py": "print('fixture source tests passed')\n",
    })
    project = base({
        "NOW.md": NOW_OK,
        "CLAUDE.md": "# rules\n\nkb_standard_version: 5.3\n",
    })
    local_home = tempfile.mkdtemp(prefix="kbtest-update-project-home-")
    installed = os.path.join(local_home, ".codex", "skills", "kb-architect")
    os.makedirs(os.path.dirname(installed), exist_ok=True)
    shutil.copytree(source, installed)
    env = dict(os.environ)
    env["HOME"] = local_home
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_update.py"),
         "--source", source, "--do", "--project", project],
        capture_output=True, text=True, timeout=180, env=env)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    check("update --project действительно запускает project application",
          out.code == 1
          and "ПРИМЕНЕНИЕ К ПРОЕКТУ" in out
          and "NEEDS_APPLICATION" in out
          and "SESSION_ACTION=APPLY_PROJECT_DELTA_NOW" in out
          and "[6.2]" in out
          and "[5.4]" not in out,
          out, "the single entry command executes kb_apply and propagates exit 1")
    shutil.rmtree(source, ignore_errors=True)
    shutil.rmtree(project, ignore_errors=True)
    shutil.rmtree(local_home, ignore_errors=True)


def t_516_route_growth_creates_optimization_request():
    """27.08 audit: route costs were printed but an increase could never fail."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "kb_cost_fixture", os.path.join(HERE, "kb_cost.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors = module.compare_baseline(
        [{"task": "ordinary", "total_bytes": 101}],
        {"schema": 1, "routes": {"ordinary": 100}})
    out = Vyvod("\n".join(errors), 0)
    check("непринятый рост route становится fail-closed optimization request",
          len(errors) == 1
          and "OPTIMIZATION_REQUIRED" in errors[0]
          and "100 -> 101" in errors[0],
          out, "any route growth needs reduction or an explicit release baseline")


def t_516_hot_context_has_evidence_driven_lifecycle():
    """Official Productivity comparison: a hot cache helps only without a second canon."""
    ref = skill_text("references/measurement.md")
    flat = " ".join(ref.split())
    out = Vyvod(ref, 0)
    check("рабочий кэш не создаёт второй канон и deep scan остаётся явным",
          "Не копируй параллельный «memory»-слой" in flat
          and "после наблюдаемого повторного обращения" in flat
          and "источник и проверка" in flat
          and "Глубокий обзор всех источников запускается отдельным явным trigger" in flat
          and "не право автоматически создавать" in flat,
          out, "promote/demote by evidence; retain one owner and explicit deep scan")


def t_600_role_and_runtime_routes_pay_only_for_their_own_reference():
    """Role guidance and runtime guidance must not load the whole module library."""
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_cost.py"), "--json", "--check"],
        capture_output=True, text=True, timeout=120)
    try:
        data = __import__("json").loads(p.stdout)
    except (ValueError, TypeError):
        data = {}
    routes = data.get("routes", [])
    role = next((x for x in routes if x.get("task", "").startswith(
        "Создать, проверить")), {})
    runtime = next((x for x in routes if x.get("task", "").startswith(
        "Проверить cloud")), {})
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    check("role and runtime routes pay only for their routed reference",
          p.returncode == 0
          and role.get("resources") == ["references/project-roles.md"]
          and role.get("extra_bytes", 99_999) < 10_000
          and runtime.get("sections", {}).get("references/modules.md") == "runtime_capabilities"
          and runtime.get("extra_bytes", 99_999) < 10_000,
          out, "role lifecycle does not re-read unrelated KB guidance")


def t_516_report_router_separates_local_and_remote_delivery():
    """Beta projects confused their own inbox, the lab inbox and GitHub."""
    local = base({
        "NOW.md": NOW_OK,
        "reports/.keep": "",
        "CLAUDE.md": "# rules\n\nentry: NOW.md\n"
                     "report route: local-inbox\nreport inbox: reports\n",
        "report.md": "# repeat lookup\n\nрежим подробности: детальный\n",
    })
    p_local = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_report.py"),
         "--project", local, "--report", os.path.join(local, "report.md"), "--do"],
        capture_output=True, text=True, timeout=30)
    delivered = os.path.join(local, "reports", "report.md")

    remote = base({
        "NOW.md": NOW_OK,
        "CLAUDE.md": "# rules\n\nentry: NOW.md\n"
                     "kb-architect service layer: accepted\n"
                     "report route: github-issue\n",
        "report.md": "# beta miss\n\ndetail mode: anonymised\n",
    })
    p_remote = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_report.py"),
         "--project", remote, "--report", os.path.join(remote, "report.md")],
        capture_output=True, text=True, timeout=30)
    p_unsafe = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_report.py"),
         "--project", remote, "--report", os.path.join(remote, "report.md"),
         "--do"], capture_output=True, text=True, timeout=30)
    check_remote = run("kb_check.py", remote)
    out = Vyvod("\n".join((p_local.stdout, p_local.stderr, p_remote.stdout,
                            p_remote.stderr, p_unsafe.stdout, p_unsafe.stderr,
                            str(check_remote))), 0)
    check("report router delivers local and prepares remote GitHub without guessing",
          p_local.returncode == 0
          and "DELIVERED local" in p_local.stdout
          and os.path.isfile(delivered)
          and p_remote.returncode == 1
          and "PREPARED github" in p_remote.stdout
          and p_unsafe.returncode == 2
          and "--public-safe" in p_unsafe.stdout
          and check_remote.code == 0
          and "GitHub issue (remote)" in check_remote,
          out, "local inbox is direct; remote issue is anonymised and externally gated")
    shutil.rmtree(local, ignore_errors=True)
    shutil.rmtree(remote, ignore_errors=True)


def t_602_private_family_report_defaults_to_detailed_local_route():
    """28.08: an agent anonymised a same-owner local report despite project policy."""
    template = skill_text("assets/templates/defect-report.md")
    out = Vyvod(template, 0)
    check("private family report is detailed by verified route, not agent guess",
          "Private local owner/family group — детальный по умолчанию" in template
          and "External/public — только обезличенный" in template
          and "Обезличенный (по умолчанию)" not in template
          and "сначала preview" in template,
          out, "trusted local delivery preserves diagnostics; public delivery is anonymised")


def t_612_linked_worktree_finds_canonical_private_report_inbox():
    """29.08 Foxio: isolated worktree guessed GitHub although owner lab was local."""
    parent = tempfile.mkdtemp(prefix="kbtest-report-owner-")
    projects = os.path.join(parent, "Documents", "Projects")
    source = os.path.join(projects, "subject")
    lab = os.path.join(projects, "kb-architect")
    worktrees = os.path.join(parent, "runtime-worktrees")
    linked = os.path.join(worktrees, "subject")
    os.makedirs(source)
    os.makedirs(os.path.join(lab, "inbox"))
    os.makedirs(worktrees)
    with open(os.path.join(source, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# local owner project\n")
    subprocess.run(["git", "-C", source, "init", "-q"], check=True)
    subprocess.run(["git", "-C", source, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", source, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", source, "add", "CLAUDE.md"], check=True)
    subprocess.run(["git", "-C", source, "commit", "-qm", "fixture"], check=True)
    subprocess.run(["git", "-C", source, "worktree", "add", "--detach", linked,
                    "HEAD"], capture_output=True, text=True, check=True)
    subprocess.run(["git", "-C", lab, "init", "-q"], check=True)
    subprocess.run(["git", "-C", lab, "remote", "add", "origin",
                    "git@github.com:sugestr/kb-architect-lab.git"], check=True)
    report = os.path.join(linked, "report.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("# private report\n\nрежим подробности: детальный\n")
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_report.py"), "--project", linked,
         "--report", report], capture_output=True, text=True, timeout=30)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    expected = os.path.join(lab, "inbox", "report.md")
    check("linked worktree auto-routes to the canonical private lab inbox",
          p.returncode == 1 and "PREPARED local" in p.stdout and expected in p.stdout
          and "github" not in p.stdout.lower(),
          out, "git-common-dir recovers the source checkout's sibling lab")
    subprocess.run(["git", "-C", source, "worktree", "remove", "--force", linked],
                   capture_output=True, text=True)
    shutil.rmtree(parent, ignore_errors=True)


def t_516_broad_evidence_query_refuses_context_overrun():
    """27.08 audit: evidence mode printed and required an unbounded candidate set."""
    files = {f"sources/f{i:03}.md": "shared support and shared challenge " + "x" * 180
             for i in range(100)}
    project = base(files)
    receipt = os.path.join(project, "receipt.json")
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), project,
         "--claim", "broad claim", "--receipt", receipt,
         "--support", "shared support", "--challenge", "shared challenge"],
        capture_output=True, text=True, timeout=120)
    data = __import__("json").load(open(receipt, encoding="utf-8"))
    finalize = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_lookup.py"), project,
         "--finalize", receipt, "--outcome", "unknown", "--reason", "broad"],
        capture_output=True, text=True, timeout=120)
    out = Vyvod(p.stdout + p.stderr + finalize.stdout + finalize.stderr, 0)
    check("широкий evidence search требует уточнения без тихого обрезания",
          p.returncode == 1
          and data.get("status") == "refine_required"
          and len(data.get("candidates", [])) == 100
          and "OPTIMIZATION_REQUIRED" in p.stdout
          and "c1  " not in p.stdout
          and finalize.returncode == 2
          and "уточнить широкий поиск" in finalize.stderr,
          out, "all candidates remain in receipt, but no conclusion/finalize is allowed")
    shutil.rmtree(project, ignore_errors=True)


def t_620_marker_without_compact_application_is_unproven():
    """A current-line marker still needs one compact owner receipt."""
    d = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 6.2\n"})
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
    out = run("kb_apply.py", d)
    check("marker 6.2 без короткой квитанции не скрывает незавершённую миграцию",
          out.code == 1 and "APPLICATION_UNPROVEN" in out
          and "missing KB_RELEASE_APPLICATION.json" in out,
          out, "the marker is an outcome, but no per-release ledger is required")
    shutil.rmtree(d, ignore_errors=True)


def t_611_git_only_candidate_uses_commit_without_second_shadow():
    """29.08: two 6.1 agents built a second rollback ritual over an exact Git commit."""
    migration = skill_text("references/migration.md")
    service = skill_text("references/service-layer.md")
    roles = skill_text("references/project-roles.md")
    project = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 5.16\n"})
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_apply.py"), project],
        capture_output=True, text=True, timeout=30)
    text = migration + "\n" + service + "\n" + roles + "\n" + p.stdout
    out = Vyvod(text + p.stderr, p.returncode)
    check("Git-only migration uses one candidate and the existing commit rollback",
          "exact pre-change Git commit" in migration
          and "commit уже является rollback" in migration
          and "второй checkout не нужен" in migration
          and "внешнее состояние проходит staged cutover" in service
          and "source commit даёт rollback" in roles
          and "без второй копии" in service
          and "post-results acceptance" in migration
          and "marker contract line" in migration,
          out, "remove duplicate shadow mechanics without weakening marker-last acceptance")
    shutil.rmtree(project, ignore_errors=True)


def t_612_git_root_trailing_space_preserves_tracking():
    """29.08 Foxio: .strip() changed a valid Git root and invented untracked roles."""
    import kb_paths

    details = []
    passed = True
    ordinary, _registry = accepted_role_fixture()
    ordinary_with_space = ordinary + " "
    os.rename(ordinary, ordinary_with_space)
    subprocess.run(["git", "-C", ordinary_with_space, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", ordinary_with_space, "config", "user.name",
                    "Fixture"], check=True)
    subprocess.run(["git", "-C", ordinary_with_space, "commit", "-qm", "fixture"],
                   check=True)
    ordinary_home = tempfile.mkdtemp(prefix="kbtest-role-home-")
    ordinary_out = run_skills(ordinary_with_space, ordinary_home)
    ordinary_passed = (
        ordinary_out.code == 0
        and os.path.samefile(kb_paths.find_git(ordinary_with_space),
                             ordinary_with_space)
        and "not Git-tracked" not in ordinary_out
    )
    passed = passed and ordinary_passed
    details.append("ordinary checkout:\n" + str(ordinary_out))

    source, _registry = accepted_role_fixture()
    subprocess.run(["git", "-C", source, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", source, "config", "user.name", "Fixture"],
                   check=True)
    subprocess.run(["git", "-C", source, "commit", "-qm", "fixture"], check=True)
    worktree_parent = tempfile.mkdtemp(prefix="kbtest-worktree-parent-")
    linked = os.path.join(worktree_parent, "linked ")
    subprocess.run(["git", "-C", source, "worktree", "add", "--detach", linked,
                    "HEAD"], capture_output=True, text=True, check=True)
    linked_home = tempfile.mkdtemp(prefix="kbtest-role-home-")
    linked_out = run_skills(linked, linked_home)
    linked_passed = (
        linked_out.code == 0
        and os.path.samefile(kb_paths.find_git(linked), linked)
        and "not Git-tracked" not in linked_out
    )
    passed = passed and linked_passed
    details.append("linked worktree:\n" + str(linked_out))

    out = Vyvod("\n".join(details), 0 if passed else 1)
    check("Git root ending in a space remains the exact tracked repository",
          passed, out,
          "ordinary checkout and linked worktree preserve path whitespace")
    subprocess.run(["git", "-C", source, "worktree", "remove", "--force", linked],
                   capture_output=True, text=True)
    shutil.rmtree(ordinary_with_space, ignore_errors=True)
    shutil.rmtree(ordinary_home, ignore_errors=True)
    shutil.rmtree(source, ignore_errors=True)
    shutil.rmtree(linked_home, ignore_errors=True)
    shutil.rmtree(worktree_parent, ignore_errors=True)


def t_620_release_application_binds_source_line_and_owner():
    """The compact receipt binds source line and owner without a patch ledger."""
    import json
    d = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 6.1.6\n"})
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "source"], check=True)
    source = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    with open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# rules\n\nkb_standard_version: 6.2\n")
    receipt = {
        "schema": 2,
        "application": {
            "from_line": "6.1", "to_line": "6.2", "status": "finalized",
            "source": {"commit": source, "version_source": "CLAUDE.md"},
            "owner": {"accepted_by": "fixture owner", "accepted_at": "2026-08-29"},
            "finalized_at": "2026-08-29", "open": [],
        },
    }
    with open(os.path.join(d, "KB_RELEASE_APPLICATION.json"), "w",
              encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md",
                    "KB_RELEASE_APPLICATION.json"], check=True)
    out = run("kb_apply.py", d)
    check("release application binds source line and owner without patch ledger",
          out.code == 0 and "APPLICATION_RECEIPT_OK" in out
          and "PROJECT_LINE_OK" in out,
          out, "source commit, old line and post-results owner receipt are bound once")
    shutil.rmtree(d, ignore_errors=True)


def t_621_compact_application_requires_the_actual_candidate_parent():
    """An older ancestor is rejected after another writer advances main."""
    import json
    d = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 6.1.6\n"})
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "session source"], check=True)
    session_source = subprocess.run(
        ["git", "-C", d, "rev-parse", "HEAD"], capture_output=True,
        text=True, check=True).stdout.strip()
    with open(os.path.join(d, "unrelated.txt"), "w", encoding="utf-8") as f:
        f.write("concurrent work\n")
    subprocess.run(["git", "-C", d, "add", "unrelated.txt"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "concurrent"], check=True)
    actual_parent = subprocess.run(
        ["git", "-C", d, "rev-parse", "HEAD"], capture_output=True,
        text=True, check=True).stdout.strip()
    with open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# rules\n\nkb_standard_version: 6.2\n")

    def write_receipt(source):
        with open(os.path.join(d, "KB_RELEASE_APPLICATION.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"schema": 2, "application": {
                "from_line": "6.1", "to_line": "6.2", "status": "finalized",
                "source": {"commit": source, "version_source": "CLAUDE.md"},
                "owner": {"accepted_by": "fixture owner",
                          "accepted_at": "2026-08-29"},
                "finalized_at": "2026-08-29", "open": [],
            }}, f)
        subprocess.run(["git", "-C", d, "add", "CLAUDE.md",
                        "KB_RELEASE_APPLICATION.json"], check=True)

    write_receipt(session_source)
    stale = run("kb_apply.py", d)
    write_receipt(actual_parent)
    exact = run("kb_apply.py", d)
    out = Vyvod("\n--- stale ancestor ---\n" + stale
                + "\n--- actual parent ---\n" + exact, exact.code)
    check("compact application distinguishes session snapshot from candidate parent",
          stale.code == 1
          and "source commit is not the actual candidate parent" in stale
          and actual_parent in stale
          and exact.code == 0 and "APPLICATION_RECEIPT_OK" in exact,
          out, "concurrent commits are inspected; rollback cannot reset over newer work")
    shutil.rmtree(d, ignore_errors=True)


def t_612_release_application_follows_safe_boot_symlink():
    """29.08 Foxio: recommended AGENTS.md -> CLAUDE.md failed source receipt."""
    import json
    d = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 6.1.6\n"})
    os.symlink("CLAUDE.md", os.path.join(d, "AGENTS.md"))
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md", "AGENTS.md"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "source"], check=True)
    source = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    with open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# rules\n\nkb_standard_version: 6.2\n")
    receipt = {
        "schema": 2,
        "application": {
            "from_line": "6.1", "to_line": "6.2", "status": "finalized",
            "source": {"commit": source, "version_source": "AGENTS.md"},
            "owner": {"accepted_by": "fixture owner", "accepted_at": "2026-08-29"},
            "finalized_at": "2026-08-29", "open": [],
        },
    }
    with open(os.path.join(d, "KB_RELEASE_APPLICATION.json"), "w",
              encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md",
                    "KB_RELEASE_APPLICATION.json"], check=True)
    out = run("kb_apply.py", d)
    check("source receipt follows the safe in-repo boot-canon symlink",
          out.code == 0 and "APPLICATION_RECEIPT_OK" in out,
          out, "AGENTS.md locator resolves to CLAUDE.md bytes at the source commit")
    shutil.rmtree(d, ignore_errors=True)


def t_610_scoped_migration_target_survives_newer_installed_skill():
    """Live 28.08 counterexample: newer stable appeared while sk-tax finalized 6.0.1."""
    import json
    d = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 6.0\n",
              "tests/migration.txt": "migration checks passed\n",
              "tests/owner.txt": "owner accepted shown results\n"})
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email",
                    "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "source"], check=True)
    source = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    source_bytes = subprocess.run(["git", "-C", d, "show", source + ":CLAUDE.md"],
                                  capture_output=True, check=True).stdout
    with open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# rules\n\nkb_standard_version: 6.0.1\n")
    receipt = {"schema": 1, "applications": [{
        "kind": "migration", "from_version": "6.0", "to_version": "6.0.1",
        "status": "finalized",
        "source_snapshot": {"ref": source, "commit": source,
                            "version_source": "CLAUDE.md",
                            "version_source_sha256": hashlib.sha256(source_bytes).hexdigest()},
        "release_ledger": [{"version": "6.0.1", "decision": "applied",
                            "evidence": ["tests/migration.txt"]}],
        "owner_acceptance": {"accepted_by": "owner", "accepted_at": "2026-08-28",
                             "evidence": ["tests/owner.txt"]},
        "finalized_at": "2026-08-28",
    }]}
    with open(os.path.join(d, "KB_RELEASE_APPLICATION.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md", "tests",
                    "KB_RELEASE_APPLICATION.json"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "finalize 6.0.1"], check=True)

    latest = run("kb_apply.py", d)
    scoped_run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_apply.py"), d,
         "--target-version", "6.0.1"],
        capture_output=True, text=True, timeout=120)
    scoped = Vyvod(scoped_run.stdout + scoped_run.stderr, scoped_run.returncode)
    combined = Vyvod(str(latest) + str(scoped), 0)
    check("явная цель миграции не расширяется новой installed версией",
          latest.code == 1 and "NEEDS_APPLICATION" in latest
          and scoped.code == 0
          and "TARGET_APPLICATION_OK" in scoped
          and "APPLICATION_UNPROVEN" not in scoped,
          combined, "default reports the new line; scoped legacy acceptance is not reopened")
    shutil.rmtree(d, ignore_errors=True)


def t_620_release_application_template_is_one_compact_receipt():
    """The shipped template must not recreate the per-patch ledger."""
    import json

    template = json.loads(skill_text("assets/templates/release-application.json"))
    application = template["application"]
    out = Vyvod(json.dumps(template, ensure_ascii=False), 0)
    check("release-application template contains one compact line receipt",
          template.get("schema") == 2
          and set(application) == {"from_line", "to_line", "status", "source",
                                   "owner", "finalized_at", "open"}
          and "applications" not in template
          and "release_ledger" not in application,
          out, "the copyable template cannot grow with patch history")


def t_601_initial_adoption_records_source_without_replaying_history():
    """A new project proves initial adoption without pretending to migrate old releases."""
    import json
    d = base({"CLAUDE.md": "# new project rules\n", "tests/proof.txt": "accepted\n"})
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "fixture@example.invalid"],
                   check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "pre-adoption"], check=True)
    source = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    with open(os.path.join(d, "CLAUDE.md"), "a", encoding="utf-8") as f:
        f.write("\nkb_standard_version: 6.2\n")
    receipt = {"schema": 2, "application": {
        "from_line": None, "to_line": "6.2", "status": "finalized",
        "source": {"commit": source, "version_source": "CLAUDE.md"},
        "owner": {"accepted_by": "owner", "accepted_at": "2026-08-29"},
        "finalized_at": "2026-08-29", "open": [],
    }}
    with open(os.path.join(d, "KB_RELEASE_APPLICATION.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md", "tests",
                    "KB_RELEASE_APPLICATION.json"], check=True)
    out = run("kb_apply.py", d)
    check("initial adoption proves pre-marker source without replaying releases",
          out.code == 0 and "APPLICATION_RECEIPT_OK" in out,
          out, "new projects use one current release row, not a fabricated migration history")
    shutil.rmtree(d, ignore_errors=True)


def t_620_direct_migration_does_not_replay_intermediate_releases():
    """A project moves directly from its source line to the current line."""
    import json
    d = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 5.16\n",
              "tests/proof.txt": "proof\n"})
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "fixture@example.invalid"],
                   check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "source"], check=True)
    source = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    with open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# rules\n\nkb_standard_version: 6.2\n")
    receipt = {"schema": 2, "application": {
        "from_line": "5.16", "to_line": "6.2", "status": "finalized",
        "source": {"commit": source, "version_source": "CLAUDE.md"},
        "owner": {"accepted_by": "owner", "accepted_at": "2026-08-29"},
        "finalized_at": "2026-08-29", "open": [],
    }}
    with open(os.path.join(d, "KB_RELEASE_APPLICATION.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md", "tests",
                    "KB_RELEASE_APPLICATION.json"], check=True)
    out = run("kb_apply.py", d)
    check("direct migration does not replay intermediate releases",
          out.code == 0 and "APPLICATION_RECEIPT_OK" in out,
          out, "one source line and one current line replace the patch ledger")
    shutil.rmtree(d, ignore_errors=True)


def t_601_acceptance_gates_cannot_collapse_into_owner_claim():
    """An owner label cannot stand in for discovery and behavior evidence."""
    import json
    d, _registry = accepted_role_fixture()
    path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(path, encoding="utf-8"))
    receipt["outcomes"] = {"OWNER_ACCEPTED": receipt["outcomes"]["OWNER_ACCEPTED"]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    out = run_skills(d)
    check("structural discovery behavior and owner outcomes remain independent",
          out.code == 1
          and "must separate STRUCTURAL_PASS, DISCOVERY_PASS, BEHAVIOR_PASS and OWNER_ACCEPTED" in out
          and "DISCOVERY_PASS: status must be PASS" in out
          and "BEHAVIOR_PASS: status must be PASS" in out,
          out, "an owner declaration cannot self-prove runtime or behavior")
    shutil.rmtree(d, ignore_errors=True)


def t_612_static_behavior_assertion_is_not_an_executed_run():
    """Foxio recurrence: five static PASS rows passed without observed behavior."""
    import json
    d, _registry = accepted_role_fixture()
    path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(path, encoding="utf-8"))
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result.pop("run")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    out = run_skills(d)
    check("static behavior assertions cannot masquerade as executed acceptance",
          out.code == 1 and "BEHAVIOR_EVIDENCE_UNEXECUTED" in out,
          out, "schema 3 binds input, expected, observed and run identity")
    shutil.rmtree(d, ignore_errors=True)


def t_613_nonexistent_harness_cannot_pass_recorded_behavior():
    """Foxio 6.1.2: a hand-written receipt named a harness that did not exist."""
    import json
    d, _registry = accepted_role_fixture()
    path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(path, encoding="utf-8"))
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["harness"] = {
            "path": "role-acceptance/missing.py",
            "sha256": "0" * 64,
            "argv": [],
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    out = run_skills(d)
    check("nonexistent behavior harness cannot receive schema-3 PASS",
          out.code == 1 and "BEHAVIOR_EVIDENCE_UNEXECUTED" in out
          and "harness" in out,
          out, "a formatted receipt is not execution evidence when its harness is absent")
    shutil.rmtree(d, ignore_errors=True)


def t_613_canonical_behavior_runner_records_bound_execution():
    """The explicit runner binds one real process to every declared case artifact."""
    import json
    d, _registry = accepted_role_fixture()
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), d,
         "--execute", "--replace"],
        capture_output=True, text=True, timeout=30)
    execution_path = os.path.join(d, "role-acceptance", "behavior-execution.json")
    execution = json.load(open(execution_path, encoding="utf-8"))
    execution_sha = hashlib.sha256(open(execution_path, "rb").read()).hexdigest()
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["executed_at"] = execution["finished_at"]
        result["run"]["execution_receipt"]["sha256"] = execution_sha
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/behavior-execution.json"], check=True)
    out = run_skills(d)
    combined = Vyvod(run.stdout + run.stderr + str(out), out.code)
    check("canonical behavior runner records a bound execution receipt",
          run.returncode == 0 and "BEHAVIOR_EXECUTION_RECORDED" in run.stdout
          and out.code == 0,
          combined, "the checker validates tracked harness, process exit and all case artifacts")
    shutil.rmtree(d, ignore_errors=True)


def t_614_schema4_requires_negative_control_for_every_case():
    """UK-property: a real harness can still be insensitive to its claimed property."""
    import json
    d, _registry = accepted_role_fixture()
    receipt = upgrade_fixture_to_schema4(d)
    receipt["outcomes"]["BEHAVIOR_PASS"]["cases"]["role-selection"]["run"].pop(
        "negative_control")
    path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json"], check=True)
    out = run_skills(d)
    check("schema-4 PASS requires a negative control per behavior property",
          out.code == 1 and "BEHAVIOR_EVIDENCE_INADEQUATE" in out
          and "negative_control" in out,
          out, "execution provenance without mutation sensitivity remains UNKNOWN")
    shutil.rmtree(d, ignore_errors=True)


def t_614_canonical_runner_records_negative_control_failures():
    """The runner must prove every declared mutation makes its case red."""
    import json
    d, _registry = accepted_role_fixture()
    upgrade_fixture_to_schema4(d)
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), d,
         "--execute", "--replace"], capture_output=True, text=True, timeout=30)
    execution_path = os.path.join(d, "role-acceptance", "behavior-execution.json")
    execution = json.load(open(execution_path, encoding="utf-8"))
    execution_sha = hashlib.sha256(open(execution_path, "rb").read()).hexdigest()
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["executed_at"] = execution["finished_at"]
        result["run"]["execution_receipt"]["sha256"] = execution_sha
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/behavior-execution.json"], check=True)
    out = run_skills(d)
    controls = execution.get("negative_controls", {})
    neutral = execution.get("neutral_controls", {})
    check("canonical behavior runner records mutation sensitivity",
          run.returncode == 0 and len(controls) == 5
          and all(item.get("actual_exit") == 10 for item in controls.values())
          and len(neutral) == 5
          and all(item.get("actual_exit") == 0 for item in neutral.values())
          and out.code == 0,
          Vyvod(run.stdout + run.stderr + str(out), out.code),
          "each declared semantic property has a recorded red negative control")
    shutil.rmtree(d, ignore_errors=True)


def t_615_released_schema4_runner_remains_exactly_readable():
    """The 6.1.6 checker must not retroactively invalidate accepted 6.1.4 evidence."""
    import json
    d, _registry = accepted_role_fixture()
    upgrade_fixture_to_schema4(d)
    run, execution = execute_and_bind_behavior(d)
    execution["protocol"] = "kb-behavior-run/v2"
    execution["runner_version"] = "2"
    execution["runner_sha256"] = (
        "07e880689a46ec742d935375a697ee9f0d0fb7e89a2da6e592c5ace7a9e935f9")
    execution_path = os.path.join(d, "role-acceptance", "behavior-execution.json")
    with open(execution_path, "w", encoding="utf-8") as f:
        json.dump(execution, f)
    execution_sha = hashlib.sha256(open(execution_path, "rb").read()).hexdigest()
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["execution_receipt"]["sha256"] = execution_sha
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/behavior-execution.json"], check=True)
    out = run_skills(d)
    execution["runner_sha256"] = "1" * 64
    with open(execution_path, "w", encoding="utf-8") as f:
        json.dump(execution, f)
    wrong_sha = hashlib.sha256(open(execution_path, "rb").read()).hexdigest()
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["execution_receipt"]["sha256"] = wrong_sha
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/behavior-execution.json"], check=True)
    wrong = run_skills(d)
    check("exact released 6.1.4 runner receipt remains schema-4 readable",
          run.returncode == 0 and out.code == 0
          and "ROLE_ACCEPTANCE_SCHEMA_4_LEGACY" in out,
          Vyvod(str(out) + str(wrong), wrong.code),
          "only the exact published v2 runner hash is grandfathered")
    check("unknown schema-4 runner hash remains rejected",
          wrong.code == 1 and "does not bind the installed runner" in wrong,
          wrong, "legacy readability is an exact allowlist, not arbitrary trust")
    shutil.rmtree(d, ignore_errors=True)


def t_614_flag_only_harness_cannot_pass_negative_controls():
    """Auditor counterexample: a magic red flag is not mutation sensitivity."""
    import json
    d, _registry = accepted_role_fixture()
    receipt = upgrade_fixture_to_schema4(d)
    harness_path = os.path.join(d, "role-acceptance", "fixture_behavior.py")
    with open(harness_path, "w", encoding="utf-8") as f:
        f.write(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--negative-control' in sys.argv:\n"
            "    raise SystemExit(10)\n"
            "raise SystemExit(0)\n")
    harness_hash = hashlib.sha256(open(harness_path, "rb").read()).hexdigest()
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["harness"]["sha256"] = harness_hash
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/fixture_behavior.py"], check=True)
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), d,
         "--execute", "--replace"], capture_output=True, text=True, timeout=30)
    execution = json.load(open(
        os.path.join(d, "role-acceptance", "behavior-execution.json"),
        encoding="utf-8"))
    controls = execution.get("negative_controls", {})
    check("flag-only harness cannot receive schema-4 mutation PASS",
          run.returncode == 1 and execution.get("exit_code") == 4
          and len(controls) == 5
          and all(item.get("actual_exit") == 0 for item in controls.values()),
          Vyvod(run.stdout + run.stderr + json.dumps(execution), run.returncode),
          "runner uses unchanged argv, so a magic exit-10 flag cannot certify sensitivity")
    shutil.rmtree(d, ignore_errors=True)


def t_614_harness_cannot_be_its_own_mutation_target():
    """Auditor counterexample: a harness may not self-mutate into exit 10."""
    import json
    d, _registry = accepted_role_fixture()
    receipt = upgrade_fixture_to_schema4(d)
    harness_path = os.path.join(d, "role-acceptance", "fixture_behavior.py")
    harness_hash = hashlib.sha256(open(harness_path, "rb").read()).hexdigest()
    control = receipt["outcomes"]["BEHAVIOR_PASS"]["cases"][
        "role-selection"]["run"]["negative_control"]
    control["target"] = {
        "path": "role-acceptance/fixture_behavior.py", "sha256": harness_hash}
    control["mutation"] = {
        "kind": "replace-text", "find": "raise SystemExit(10)",
        "replace": "raise SystemExit(11)", "count": 1}
    control["neutral_mutation"] = {
        "kind": "replace-text", "find": "raise SystemExit(0)",
        "replace": "raise SystemExit(2)", "count": 1}
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json"], check=True)
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), d,
         "--execute", "--replace"], capture_output=True, text=True, timeout=30)
    check("behavior harness cannot self-certify by mutating itself",
          run.returncode == 2 and "target cannot be the harness" in run.stderr,
          Vyvod(run.stdout + run.stderr, 0),
          "mutation evidence must target project behavior inputs, never test code")
    shutil.rmtree(d, ignore_errors=True)


def t_614_any_change_detector_fails_neutral_control():
    """Auditor remedy: red on every mutation is not semantic sensitivity."""
    import json
    d, _registry = accepted_role_fixture()
    receipt = upgrade_fixture_to_schema4(d)
    harness_path = os.path.join(d, "role-acceptance", "fixture_behavior.py")
    with open(harness_path, "w", encoding="utf-8") as f:
        f.write(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "text = ''.join(p.read_text(encoding='utf-8') for p in "
            "Path('role-acceptance').glob('*-input.json'))\n"
            "if 'BROKEN fixture input' in text or 'neutral fixture note revised' in text:\n"
            "    raise SystemExit(10)\n"
            "raise SystemExit(0)\n")
    harness_hash = hashlib.sha256(open(harness_path, "rb").read()).hexdigest()
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["harness"]["sha256"] = harness_hash
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/fixture_behavior.py"], check=True)
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), d,
         "--execute", "--replace"], capture_output=True, text=True, timeout=30)
    execution = json.load(open(
        os.path.join(d, "role-acceptance", "behavior-execution.json"),
        encoding="utf-8"))
    neutral = execution.get("neutral_controls", {})
    check("detector of every file change cannot receive semantic PASS",
          run.returncode == 1 and execution.get("exit_code") == 4
          and len(neutral) == 5
          and all(item.get("actual_exit") == 10 for item in neutral.values()),
          Vyvod(run.stdout + run.stderr + json.dumps(execution), run.returncode),
          "harmless same-target mutation must remain green")
    shutil.rmtree(d, ignore_errors=True)


def t_615_schema5_binds_failure_to_exact_case():
    """UK-property: exit 10 alone did not prove which claimed property failed."""
    import json
    d, _registry = accepted_role_fixture()
    upgrade_fixture_to_schema5(d)
    run, execution = execute_and_bind_behavior(d)
    out = run_skills(d)
    expected_cases = {"role-selection", "knowledge-recall", "authority-stop",
                      "source-conflict", "context-cost"}
    controls = execution.get("negative_controls", {})
    check("schema-5 canonical runner attributes every harmful mutation to its case",
          run.returncode == 0 and out.code == 0
          and set(controls) == expected_cases
          and all(item.get("reported_results", {}).get(case) == "FAIL"
                  and sum(value == "FAIL" for value in
                          item.get("reported_results", {}).values()) == 1
                  for case, item in controls.items()),
          Vyvod(run.stdout + run.stderr + str(out), out.code),
          "a suite-wide red exit cannot masquerade as five independently proven properties")
    shutil.rmtree(d, ignore_errors=True)


def t_615_cross_case_failure_is_rejected():
    """A mutation of one property must not be credited to another red property."""
    import json
    d, _registry = accepted_role_fixture()
    receipt = upgrade_fixture_to_schema5(d)
    harness_path = os.path.join(d, "role-acceptance", "fixture_behavior.py")
    with open(harness_path, "w", encoding="utf-8") as f:
        f.write(
            "#!/usr/bin/env python3\nimport json\nfrom pathlib import Path\n"
            "cases=('role-selection','knowledge-recall','authority-stop',"
            "'source-conflict','context-cost')\n"
            "broken=any(json.loads(p.read_text()).get('prompt') != "
            "'synthetic fixture input' for p in Path('role-acceptance').glob('*-input.json'))\n"
            "results={case: ('FAIL' if broken and case == 'source-conflict' else 'PASS') "
            "for case in cases}\n"
            "print('KB_BEHAVIOR_RESULT ' + json.dumps({"
            "'protocol':'kb-behavior-result/v1','results':results},sort_keys=True))\n"
            "raise SystemExit(10 if broken else 0)\n")
    harness_hash = hashlib.sha256(open(harness_path, "rb").read()).hexdigest()
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["harness"]["sha256"] = harness_hash
    with open(os.path.join(d, "ROLE_ACCEPTANCE.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json",
                    "role-acceptance/fixture_behavior.py"], check=True)
    run, execution = execute_and_bind_behavior(d)
    check("cross-case red result cannot receive schema-5 PASS",
          run.returncode == 1 and execution.get("exit_code") == 4
          and execution["negative_controls"]["role-selection"][
              "reported_results"].get("source-conflict") == "FAIL",
          Vyvod(run.stdout + run.stderr + json.dumps(execution), run.returncode),
          "the declared case itself, and only it, must fail")
    shutil.rmtree(d, ignore_errors=True)


def t_615_schema5_rejects_host_absolute_harness_argv():
    """Tracked acceptance evidence must survive a different host and checkout."""
    import json
    d, _registry = accepted_role_fixture()
    receipt = upgrade_fixture_to_schema5(d)
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["harness"]["argv"] = ["/opt/example/private/helper.py"]
    with open(os.path.join(d, "ROLE_ACCEPTANCE.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json"], check=True)
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), d,
         "--execute", "--replace"], capture_output=True, text=True, timeout=30)
    out = run_skills(d)
    posix_passed = (run.returncode == 2 and "host-absolute" in run.stderr
                    and out.code == 1 and "host-absolute" in out)
    receipt = json.load(open(os.path.join(d, "ROLE_ACCEPTANCE.json"), encoding="utf-8"))
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result["run"]["harness"]["argv"] = ["\\\\server\\share\\helper.py"]
    with open(os.path.join(d, "ROLE_ACCEPTANCE.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json"], check=True)
    unc_run = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_behavior.py"), d,
         "--execute", "--replace"], capture_output=True, text=True, timeout=30)
    unc_out = run_skills(d)
    check("schema-5 rejects POSIX and Windows host-absolute harness argv",
          posix_passed and unc_run.returncode == 2
          and "host-absolute" in unc_run.stderr
          and unc_out.code == 1 and "host-absolute" in unc_out,
          Vyvod(run.stdout + run.stderr + str(out) + unc_run.stdout
                + unc_run.stderr + str(unc_out), unc_out.code),
          "project evidence uses relative paths or runner-provided KB_ARCHITECT_SCRIPTS")
    shutil.rmtree(d, ignore_errors=True)


def t_615_complete_cost_and_unknown_usage_are_truthful():
    """UK-property omitted manifests from static cost and labelled UNKNOWN as receipt."""
    import json
    d, _registry = accepted_role_fixture()
    upgrade_fixture_to_schema5(d)
    run, _execution = execute_and_bind_behavior(d)
    out = run_skills(d)
    registry_bytes = os.path.getsize(os.path.join(d, "PROJECT_ROLES.json"))
    index_bytes = os.path.getsize(os.path.join(d, "KNOWLEDGE_INDEX.json"))
    check("schema-5 reports control plane, complete static cost and actual UNKNOWN",
          run.returncode == 0 and out.code == 0
          and f"control-plane={registry_bytes + index_bytes}" in out
          and "static-route=" in out and "static-end-to-end=" in out
          and "actual-usage=UNKNOWN" in out
          and "actual-usage=receipt" not in out,
          out, "static bytes and measured model tokens stay separate")
    shutil.rmtree(d, ignore_errors=True)


def t_615_control_plane_and_end_to_end_budgets_fail_closed():
    """New cost fields are gates, not decorative output labels."""
    import json
    d, _registry = accepted_role_fixture()
    upgrade_fixture_to_schema5(d)
    run, _execution = execute_and_bind_behavior(d)
    registry_path = os.path.join(d, "PROJECT_ROLES.json")
    registry = json.load(open(registry_path, encoding="utf-8"))
    scenario = registry["cost_policy"]["scenarios"][0]
    scenario["accepted_control_plane_bytes"] = 1
    scenario["accepted_end_to_end_bytes"] = 1
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f)
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    baseline = receipt["scenario_baselines"][scenario["id"]]
    baseline["accepted_control_plane_bytes"] = 1
    baseline["accepted_end_to_end_bytes"] = 1
    receipt["project_roles_sha256"] = hashlib.sha256(
        open(registry_path, "rb").read()).hexdigest()
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json"], check=True)
    out = run_skills(d)
    check("schema-5 blocks control-plane and complete-static budget overruns",
          run.returncode == 0 and out.code == 1
          and "accepted_control_plane_bytes grew 1 ->" in out
          and "accepted_end_to_end_bytes grew 1 ->" in out,
          out, "a complete cost field must constrain growth, not merely describe it")
    shutil.rmtree(d, ignore_errors=True)


def t_616_candidate_receipt_is_validated_before_owner_acceptance():
    """UK-property: the owner cannot accept evidence the stock checker never read."""
    import json
    d, _registry = accepted_role_fixture()
    upgrade_fixture_to_schema5(d)
    run, _execution = execute_and_bind_behavior(d)
    registry_path = os.path.join(d, "PROJECT_ROLES.json")
    registry = json.load(open(registry_path, encoding="utf-8"))
    registry["acceptance"]["status"] = "candidate"
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f)
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    receipt["project_roles_sha256"] = hashlib.sha256(
        open(registry_path, "rb").read()).hexdigest()
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json"], check=True)
    valid = run_skills(d)

    receipt["project_roles_sha256"] = "0" * 64
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json"], check=True)
    corrupt = run_skills(d)
    check("valid candidate evidence is checked independently of owner gate",
          run.returncode == 0 and valid.code == 1 and "errors=1" in valid
          and "ROLE_ACCEPTANCE_REQUIRED" in valid
          and "pre-owner receipt checked independently" in valid,
          valid, "owner acceptance stays red while prior evidence is mechanically checked")
    check("corrupt candidate receipt is diagnosed before owner acceptance",
          corrupt.code == 1 and "errors=2" in corrupt
          and "ROLE_ACCEPTANCE_REQUIRED" in corrupt
          and "does not match PROJECT_ROLES.json" in corrupt,
          corrupt, "candidate status cannot hide a damaged receipt")
    shutil.rmtree(d, ignore_errors=True)


def t_616_new_candidate_cannot_downgrade_to_legacy_schema():
    """Accepted legacy stays readable; new evidence cannot opt out of current gates."""
    import json
    d, _registry = accepted_role_fixture()
    registry_path = os.path.join(d, "PROJECT_ROLES.json")
    registry = json.load(open(registry_path, encoding="utf-8"))
    registry["acceptance"]["status"] = "candidate"
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f)
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    receipt["schema"] = 2
    for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
        result.pop("run", None)
    receipt["project_roles_sha256"] = hashlib.sha256(
        open(registry_path, "rb").read()).hexdigest()
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json"], check=True)
    out = run_skills(d)
    check("new candidate cannot downgrade to schema-2 evidence",
          out.code == 1
          and "ROLE_ACCEPTANCE_CANDIDATE_SCHEMA_5_REQUIRED" in out
          and "accepted_control_plane_bytes must be" in out
          and "accepted_end_to_end_bytes must be" in out,
          out, "legacy compatibility is not an opt-out for new candidate work")
    shutil.rmtree(d, ignore_errors=True)


def t_616_candidate_pending_and_unknown_outcomes_are_visible():
    """Unchecked gates must not disappear behind a generic validated note."""
    import json
    d, _registry = accepted_role_fixture()
    upgrade_fixture_to_schema5(d)
    run, _execution = execute_and_bind_behavior(d)
    registry_path = os.path.join(d, "PROJECT_ROLES.json")
    registry = json.load(open(registry_path, encoding="utf-8"))
    registry["acceptance"]["status"] = "candidate"
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f)
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    receipt["outcomes"]["DISCOVERY_PASS"]["status"] = "UNKNOWN"
    receipt["outcomes"]["OWNER_ACCEPTED"]["status"] = "PENDING"
    receipt["project_roles_sha256"] = hashlib.sha256(
        open(registry_path, "rb").read()).hexdigest()
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                    "ROLE_ACCEPTANCE.json"], check=True)
    out = run_skills(d)
    check("candidate PENDING and UNKNOWN outcomes stay visible",
          run.returncode == 0 and out.code == 1 and "errors=1" in out
          and "candidate outcome DISCOVERY_PASS=UNKNOWN" in out
          and "candidate outcome OWNER_ACCEPTED=PENDING" in out,
          out, "checked PASS evidence does not imply every candidate outcome passed")
    shutil.rmtree(d, ignore_errors=True)


def t_616_invalid_manifest_status_cannot_hide_corrupt_receipt():
    """Typos and draft labels must neither look valid nor suppress receipt checks."""
    import json
    for status in ("PENDING", "UNKNOWN", "candidate ", "draft", [], {}):
        d, _registry = accepted_role_fixture()
        upgrade_fixture_to_schema5(d)
        run, _execution = execute_and_bind_behavior(d)
        registry_path = os.path.join(d, "PROJECT_ROLES.json")
        registry = json.load(open(registry_path, encoding="utf-8"))
        registry["acceptance"]["status"] = status
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f)
        acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
        receipt = json.load(open(acceptance_path, encoding="utf-8"))
        receipt["project_roles_sha256"] = "0" * 64
        receipt["outcomes"]["STRUCTURAL_PASS"]["validators"] = {}
        with open(acceptance_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f)
        subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                        "ROLE_ACCEPTANCE.json"], check=True)
        out = run_skills(d)
        check(f"invalid acceptance status {status!r} cannot hide corrupt receipt",
              run.returncode == 0 and out.code == 1
              and "ROLE_ACCEPTANCE_REQUIRED" in out
              and "ROLE_ACCEPTANCE_STATUS_INVALID" in out
              and "does not match PROJECT_ROLES.json" in out
              and "STRUCTURAL_PASS." in out,
              out, "invalid manifest state remains visible and its supplied receipt is checked")
        shutil.rmtree(d, ignore_errors=True)


def t_616_non_object_candidate_receipt_fails_closed_without_traceback():
    """Valid JSON of the wrong shape is a diagnostic, not an agent crash."""
    import json
    for payload in ([], None, "not-an-object"):
        d, _registry = accepted_role_fixture()
        registry_path = os.path.join(d, "PROJECT_ROLES.json")
        registry = json.load(open(registry_path, encoding="utf-8"))
        registry["acceptance"]["status"] = "candidate"
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f)
        acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
        with open(acceptance_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                        "ROLE_ACCEPTANCE.json"], check=True)
        out = run_skills(d)
        check(f"non-object candidate receipt {payload!r} fails closed",
              out.code == 1 and "ROLE_ACCEPTANCE_REQUIRED" in out
              and "role acceptance receipt must be an object" in out
              and "ROLE_ACCEPTANCE_SCHEMA_2_3_4_OR_5_REQUIRED" in out
              and "Traceback" not in out,
              out, "malformed receipt shape is reported without crashing the agent")
        shutil.rmtree(d, ignore_errors=True)


def t_616_non_object_accepted_receipt_fails_closed_without_traceback():
    """Compatibility schema probing must not crash before the main diagnostic."""
    import json
    for payload in ([], None, "not-an-object"):
        d, _registry = accepted_role_fixture()
        acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
        with open(acceptance_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json"], check=True)
        out = run_skills(d)
        check(f"non-object accepted receipt {payload!r} fails closed",
              out.code == 1 and "ROLE_ACCEPTANCE_REQUIRED" not in out
              and "role acceptance receipt must be an object" in out
              and "ROLE_ACCEPTANCE_SCHEMA_2_3_4_OR_5_REQUIRED" in out
              and "Traceback" not in out,
              out, "schema hint cannot pre-empt the stable receipt diagnostic")
        shutil.rmtree(d, ignore_errors=True)


def t_616_non_object_skill_binding_fails_closed_without_traceback():
    """A malformed nested skill binding is rejected without agent failure."""
    import json
    d, _registry = accepted_role_fixture()
    acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(acceptance_path, encoding="utf-8"))
    receipt["skills"]["domain-auditor"] = []
    with open(acceptance_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    subprocess.run(["git", "-C", d, "add", "ROLE_ACCEPTANCE.json"], check=True)
    out = run_skills(d)
    check("non-object accepted skill binding fails closed",
          out.code == 1 and "accepted skill binding must be an object" in out
          and "Traceback" not in out,
          out, "nested receipt corruption remains a normal validation error")
    shutil.rmtree(d, ignore_errors=True)


def t_616_non_object_nested_candidate_fields_fail_closed():
    """Malformed nested candidate evidence never crashes stock validation."""
    import json

    def discovery_agent(receipt):
        receipt["outcomes"]["DISCOVERY_PASS"]["agents"]["codex"] = []

    def behavior_case(receipt):
        receipt["outcomes"]["BEHAVIOR_PASS"]["cases"]["role-selection"] = []

    def private_proof(receipt):
        receipt["outcomes"]["BEHAVIOR_PASS"]["private_real_data"] = []

    def behavior_run(receipt):
        receipt["outcomes"]["BEHAVIOR_PASS"]["cases"]["role-selection"]["run"] = []

    def receipt_schema(receipt):
        receipt["schema"] = []

    def gate_status(receipt):
        receipt["outcomes"]["DISCOVERY_PASS"]["status"] = []

    def usage_status(receipt):
        receipt["actual_usage"]["status"] = []

    def control_id(receipt):
        receipt["outcomes"]["BEHAVIOR_PASS"]["cases"]["role-selection"]["run"][
            "negative_control"]["id"] = []

    probes = (
        ("discovery agent", discovery_agent, "agent result must be an object"),
        ("behavior case", behavior_case, "case must be an object"),
        ("private proof", private_proof, "private_real_data must be an object"),
        ("behavior run", behavior_run, "BEHAVIOR_EVIDENCE_UNEXECUTED"),
        ("receipt schema", receipt_schema, "ROLE_ACCEPTANCE_SCHEMA_2_3_4_OR_5_REQUIRED"),
        ("gate status", gate_status, "candidate status must be PASS"),
        ("usage status", usage_status, "actual_usage must be separate PASS or UNKNOWN"),
        ("negative control id", control_id, "negative_control.id is required"),
    )
    for label, mutate, expected in probes:
        d, _registry = accepted_role_fixture()
        upgrade_fixture_to_schema5(d)
        run, _execution = execute_and_bind_behavior(d)
        registry_path = os.path.join(d, "PROJECT_ROLES.json")
        registry = json.load(open(registry_path, encoding="utf-8"))
        registry["acceptance"]["status"] = "candidate"
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f)
        acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
        receipt = json.load(open(acceptance_path, encoding="utf-8"))
        receipt["project_roles_sha256"] = hashlib.sha256(
            open(registry_path, "rb").read()).hexdigest()
        mutate(receipt)
        with open(acceptance_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f)
        subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                        "ROLE_ACCEPTANCE.json"], check=True)
        out = run_skills(d)
        check(f"non-object nested candidate {label} fails closed",
              run.returncode == 0 and out.code == 1 and expected in out
              and "Traceback" not in out,
              out, "nested malformed evidence remains a validation result")
        shutil.rmtree(d, ignore_errors=True)


def t_616_non_string_role_posture_status_fails_closed():
    """The outer role registry has the same no-traceback status invariant."""
    import json
    for status in ([], {}):
        d, _registry = accepted_role_fixture()
        registry_path = os.path.join(d, "PROJECT_ROLES.json")
        registry = json.load(open(registry_path, encoding="utf-8"))
        registry["role_posture"]["status"] = status
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f)
        subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json"], check=True)
        out = run_skills(d)
        check(f"non-string role posture {status!r} fails closed",
              out.code == 1 and "role_posture.status must be" in out
              and "Traceback" not in out,
              out, "malformed outer status is a normal validation result")
        shutil.rmtree(d, ignore_errors=True)


def t_616_malformed_execution_receipt_fields_fail_closed():
    """Unhashable protocol and run-id fields stay inside normal diagnostics."""
    import json

    def protocol(execution):
        execution["protocol"] = []

    def runner_version(execution):
        execution["runner_version"] = {}

    def case_run_ids_list(execution):
        execution["case_run_ids"] = [[]]

    def case_run_ids_null(execution):
        execution["case_run_ids"] = None

    probes = (
        ("protocol", protocol, "canonical behavior-run receipt is required"),
        ("runner version", runner_version, "canonical behavior-run receipt is required"),
        ("case ids list", case_run_ids_list, "does not bind case run_id"),
        ("case ids null", case_run_ids_null, "does not bind case run_id"),
    )
    for label, mutate, expected in probes:
        d, _registry = accepted_role_fixture()
        upgrade_fixture_to_schema5(d)
        run, execution = execute_and_bind_behavior(d)
        execution_path = os.path.join(d, "role-acceptance", "behavior-execution.json")
        mutate(execution)
        with open(execution_path, "w", encoding="utf-8") as f:
            json.dump(execution, f)
        execution_sha = hashlib.sha256(open(execution_path, "rb").read()).hexdigest()
        registry_path = os.path.join(d, "PROJECT_ROLES.json")
        registry = json.load(open(registry_path, encoding="utf-8"))
        registry["acceptance"]["status"] = "candidate"
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f)
        acceptance_path = os.path.join(d, "ROLE_ACCEPTANCE.json")
        receipt = json.load(open(acceptance_path, encoding="utf-8"))
        receipt["project_roles_sha256"] = hashlib.sha256(
            open(registry_path, "rb").read()).hexdigest()
        for result in receipt["outcomes"]["BEHAVIOR_PASS"]["cases"].values():
            result["run"]["execution_receipt"]["sha256"] = execution_sha
        with open(acceptance_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f)
        subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json",
                        "ROLE_ACCEPTANCE.json", "role-acceptance/behavior-execution.json"],
                       check=True)
        out = run_skills(d)
        check(f"malformed execution receipt {label} fails closed",
              run.returncode == 0 and out.code == 1 and expected in out
              and "Traceback" not in out,
              out, "execution receipt shape cannot crash candidate validation")
        shutil.rmtree(d, ignore_errors=True)


def t_612_packaging_review_cannot_claim_professional_method_pass():
    """Foxio review moved files but was reported as professional role quality PASS."""
    import json
    d, _registry = accepted_role_fixture()
    review = os.path.join(d, "skills", "domain-auditor", "ROLE_QUALITY_REVIEW.json")
    data = json.load(open(review, encoding="utf-8"))
    data["review_scope"] = "packaging-only"
    with open(review, "w", encoding="utf-8") as f:
        json.dump(data, f)
    out = run_skills(d)
    check("packaging-only role review is not professional-method acceptance",
          out.code == 1
          and "packaging-only review cannot be professional-method PASS" in out,
          out, "review_scope keeps structural cleanup narrower than method quality")
    shutil.rmtree(d, ignore_errors=True)


def t_601_common_validator_rejects_top_level_role_version():
    """The project validator cannot waive the portable Agent Skills schema."""
    d, _registry = accepted_role_fixture(
        "---\nname: domain-auditor\ndescription: Fixture role\nversion: 1.0.0\n---\n")
    out = run_skills(d)
    check("project role проходит общий и проектный validator раздельно",
          out.code == 1 and "platform validator rejects top-level version" in out
          and "platform validator requires metadata.version" in out,
          out, "a green project test does not overrule the portable skill schema")
    shutil.rmtree(d, ignore_errors=True)


def t_601_active_global_role_collision_is_fail_closed():
    """A same-name user-global role must not silently preempt project bytes."""
    d, _registry = accepted_role_fixture()
    home = tempfile.mkdtemp(prefix="kbtest-role-home-")
    global_role = os.path.join(home, ".codex", "skills", "domain-auditor")
    os.makedirs(global_role)
    with open(os.path.join(global_role, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: domain-auditor\ndescription: Other copy\n"
                "metadata:\n  version: 9.9.9\n---\ndifferent\n")
    out = run_skills(d, home)
    check("same-name active global role cannot hide project candidate",
          out.code == 1 and "ACTIVE_RUNTIME_COLLISION" in out
          and global_role in out and "version=9.9.9" in out,
          out, "bounded active roots expose id/path/hash/version collisions")
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)


def t_601_discovery_requires_unforced_fresh_new_session_inventory():
    """Static links prove structure, not runtime selection in a fresh context."""
    import json
    d, _registry = accepted_role_fixture()
    path = os.path.join(d, "ROLE_ACCEPTANCE.json")
    receipt = json.load(open(path, encoding="utf-8"))
    receipt["outcomes"]["DISCOVERY_PASS"]["agents"]["codex"]["unforced"] = False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    out = run_skills(d)
    check("runtime discovery needs inventory and an unforced fresh new session",
          out.code == 1
          and "DISCOVERY_PASS.codex: fresh_context and unforced are required" in out,
          out, "a symlink or forced prompt is STRUCTURAL_PASS, not DISCOVERY_PASS")
    shutil.rmtree(d, ignore_errors=True)


def t_601_local_report_route_never_falls_back_public():
    """Lack of local write authority is not authority to publish privately routed data."""
    project = base({
        "CLAUDE.md": "# rules\n\nreport route: local-inbox\nreport inbox: missing-inbox\n",
        "report.md": "# private report\n\nрежим подробности: детальный\n",
    })
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_report.py"), "--project", project,
         "--report", os.path.join(project, "report.md"), "--public-safe", "--do"],
        capture_output=True, text=True, timeout=30)
    # Code 2 is the expected fail-closed outcome being asserted, not a broken
    # test process; keep the harness infrastructure oracle separate here.
    out = Vyvod(p.stdout + p.stderr, 0)
    check("недоступный local inbox даёт BLOCKED_LOCAL без public fallback",
          p.returncode == 2 and "BLOCKED_LOCAL" in p.stdout
          and os.path.join(project, "missing-inbox") in p.stdout
          and "github" not in p.stdout.lower(),
          out, "recipient identity and current write authority remain separate")
    shutil.rmtree(project, ignore_errors=True)


def t_601_report_addendum_preserves_payload_and_bidirectional_link():
    """Corrections append relationships without rewriting the original report bytes."""
    import json
    project = base({
        "CLAUDE.md": "# rules\n\nreport route: local-inbox\nreport inbox: reports\n",
        "reports/.keep": "",
        "parent.md": "# parent\n\noriginal observation\n",
        "child.md": "# child\n\nadditional evidence\n",
    })
    parent_source = os.path.join(project, "parent.md")
    child_source = os.path.join(project, "child.md")
    original = open(parent_source, "rb").read()
    parent = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_report.py"), "--project", project,
         "--report", parent_source, "--do"], capture_output=True, text=True, timeout=30)
    child = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_report.py"), "--project", project,
         "--report", child_source, "--amends", "parent.md", "--do"],
        capture_output=True, text=True, timeout=30)
    index = json.load(open(os.path.join(project, "reports", "REPORT_INDEX.json"),
                           encoding="utf-8"))
    parent_id = "sha256:" + hashlib.sha256(original).hexdigest()
    child_id = "sha256:" + hashlib.sha256(open(child_source, "rb").read()).hexdigest()
    out = Vyvod(parent.stdout + parent.stderr + child.stdout + child.stderr, child.returncode)
    check("report addendum keeps immutable payload and bidirectional linkage",
          parent.returncode == 0 and child.returncode == 0
          and open(os.path.join(project, "reports", "parent.md"), "rb").read() == original
          and index["reports"][child_id]["relations"]["amends"] == parent_id
          and child_id in index["reports"][parent_id]["relations"]["amended_by"],
          out, "content-derived ids and a mutable index preserve both history and navigation")
    shutil.rmtree(project, ignore_errors=True)


def t_620_owner_transition_does_not_invalidate_role_behavior():
    """Owner acceptance must not change the bytes used to bind role behavior."""
    import json
    d = compact_role_fixture(accepted=False)
    candidate = run_skills(d)
    path = os.path.join(d, "PROJECT_ROLES.json")
    registry = json.load(open(path, encoding="utf-8"))
    registry["acceptance"]["status"] = "accepted"
    registry["acceptance"]["owner"] = {
        "status": "PASS", "accepted_by": "fixture owner",
        "accepted_at": "2026-08-29",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json"], check=True)
    accepted = run_skills(d, execute_project_check=True)
    out = Vyvod(candidate + "\n--- accepted ---\n" + accepted, accepted.code)
    check("candidate to accepted does not rerun or invalidate role behavior",
          candidate.code == 1 and "ROLE_ACCEPTANCE_REQUIRED" in candidate
          and "compact acceptance does not match" not in candidate
          and accepted.code == 0 and "errors=0" in accepted,
          out, "acceptance state is outside the hash-bound SKILL.md bytes")
    shutil.rmtree(d, ignore_errors=True)


def t_621_compact_acceptance_executes_the_declared_check_before_commit():
    """A typed PASS previously hid a project command that actually failed."""
    import json
    d = compact_role_fixture(accepted=True)
    declared_only = run_skills(d)
    executed = run_skills(d, execute_project_check=True)
    with open(os.path.join(d, "tests.py"), "w", encoding="utf-8") as f:
        f.write("raise SystemExit(2)\n")
    subprocess.run(["git", "-C", d, "add", "tests.py"], check=True)
    failed = run_skills(d, execute_project_check=True)
    out = Vyvod("\n--- declared ---\n" + declared_only
                + "\n--- executed ---\n" + executed
                + "\n--- failing command ---\n" + failed, failed.code)
    check("compact acceptance cannot turn a declared PASS into execution proof",
          declared_only.code == 1
          and "PROJECT_CHECK_EXECUTION_REQUIRED" in declared_only
          and executed.code == 0
          and "PROJECT_CHECK_EXECUTED_PASS" in executed
          and failed.code == 1
          and "PROJECT_CHECK_EXECUTION_FAILED: exit 2" in failed,
          out, "one explicit pre-commit runner replaces a self-asserted command result")
    shutil.rmtree(d, ignore_errors=True)


def t_621_untracked_compact_manifest_still_requires_execution():
    """A first-adoption manifest is new, so Git diff alone cannot see its bytes."""
    d = compact_role_fixture(accepted=True)
    subprocess.run(["git", "-C", d, "reset", "-q", "--", "PROJECT_ROLES.json"],
                   check=True)
    out = run_skills(d)
    check("untracked compact manifest still requires explicit project execution",
          out.code == 1 and "PROJECT_CHECK_EXECUTION_REQUIRED" in out,
          out, "first adoption cannot bypass the v2 execution gate")
    shutil.rmtree(d, ignore_errors=True)


def t_621_accepted_v1_compact_receipt_remains_legacy_readable():
    """Patch 6.2.1 must not reopen projects already accepted on contract line 6.2."""
    import json
    d = compact_role_fixture(accepted=True)
    path = os.path.join(d, "PROJECT_ROLES.json")
    registry = json.load(open(path, encoding="utf-8"))
    registry["acceptance"]["protocol"] = "kb-role-acceptance/v1"
    registry["acceptance"]["project_check"].pop("execution")
    registry["acceptance"]["live_test"].pop("observation")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "add", "PROJECT_ROLES.json"], check=True)
    out = run_skills(d)
    check("accepted compact v1 stays readable without patch remigration",
          out.code == 0 and "ROLE_ACCEPTANCE_V1_LEGACY_ATTESTED" in out,
          out, "new candidates use v2; accepted v1 remains an explicit legacy attestation")
    shutil.rmtree(d, ignore_errors=True)


def t_620_compact_application_uses_contract_line_not_patch_build():
    """A 6.2 project stays accepted when the installed exact build is 6.2.1."""
    import json
    d = base({"CLAUDE.md": "# rules\n\nkb_standard_version: 6.1.6\n"})
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
    subprocess.run(["git", "-C", d, "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "commit", "-qm", "before"],
                   check=True)
    source = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    with open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# rules\n\nkb_standard_version: 6.2\n")
    with open(os.path.join(d, "KB_RELEASE_APPLICATION.json"), "w", encoding="utf-8") as f:
        json.dump({
            "schema": 2,
            "application": {
                "from_line": "6.1", "to_line": "6.2", "status": "finalized",
                "source": {"commit": source, "version_source": "CLAUDE.md"},
                "owner": {"accepted_by": "fixture owner", "accepted_at": "2026-08-29"},
                "finalized_at": "2026-08-29", "open": [],
            },
        }, f)
    subprocess.run(["git", "-C", d, "add", "CLAUDE.md",
                    "KB_RELEASE_APPLICATION.json"], check=True)
    subprocess.run(["git", "-C", d, "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "commit", "-qm", "accepted"],
                   check=True)
    p = subprocess.run([sys.executable, os.path.join(HERE, "kb_apply.py"), d],
                       capture_output=True, text=True, timeout=30)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    check("contract line 6.2 accepts exact installed build 6.2.1 without remigration",
          p.returncode == 0 and "APPLICATION_RECEIPT_OK" in p.stdout
          and "PROJECT_LINE_OK" in p.stdout,
          out, "patch build is delivery, not a new project migration")
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
