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
              "delivery_target:", "delivery_state:", "collector:")
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


def t_thin_router_preserves_frozen_contract_by_reference():
    """Ночной замер: полный entry 40 955 Б читался даже для простой маршрутизации."""
    router = skill_text("SKILL.md")
    contract = skill_text("references/contract.md")
    rules = (
        "Ни один класс текущего состояния не обслуживается двумя",
        "Не утверждать поведение внешней системы из памяти",
        "Производное представление правят в источнике",
        "Реорганизация — только с предварительного согласия",
    )
    out = Vyvod(router + "\n" + contract, 0)
    check("тонкий entry маршрутизирует к неизменному обязательному контракту",
          len(router.encode("utf-8")) <= 10_000
          and "references/contract.md" in router
          and "## Три поля" not in router
          and all(rule in contract for rule in rules)
          and "CORRECTIONS.md" in contract
          and "один сменный слот" in contract,
          out, "router <=10KB; four rules, corrections and control test stay in contract")


def t_project_entry_is_two_layer_and_keeps_stop_gates():
    """Шесть проектов: entry rules достигали 52 КБ; authority нельзя потерять."""
    tpl = skill_text("assets/templates/CLAUDE.md")
    out = Vyvod(tpl, 0)
    check("project boot entry короткий, routed и fail-closed",
          len(tpl.encode("utf-8")) <= 8_000
          and "короткий boot canon" in tpl
          and "подробные правила" in tpl
          and "Authority и stop-gates" in tpl
          and "обязательный domain skill" in tpl
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
          and "задерживать первый низкорисковый полезный ответ" in service
          and "один раз на новую task/session" in template,
          out, "one boot per task; answer-only, mixed and risky paths stay distinct")


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
        "schema": 1,
        "supported_agents": ["codex", "claude"],
        "skills": [{
            "name": name,
            "purpose": "fixture procedure",
            "required": True,
            "required_when": "subject work",
            "modality": "evidence-led professional adviser",
            "authority_ladder": ["applicable primary authority", "case evidence", "secondary analysis", "community lead"],
            "conflict_resolution": "higher applicable authority wins; preserve the conflict",
            "evidence_threshold": "cite sufficient project evidence before a conclusion",
            "stop_conditions": ["applicability unresolved", "required source unavailable"],
            "prohibited_actions": ["invent missing facts", "act beyond owner authority"],
            "canonical": canonical,
            "owner": "project owner",
            "scope": "procedure only; project facts stay in KB",
            "project_precedence": "PROJECT_RULES.md",
            "version": "fixture-1",
            "validation": {"command": "python3 tests.py", "environment": "python 3"},
            "failure_policy": "fail-closed",
            "recovery_cost": "fresh clone plus declared dependencies",
            "discovery": {"codex": codex, "claude": claude},
        }],
    }


def run_skills(root, home=None):
    env = dict(os.environ)
    if home:
        env["HOME"] = home
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_skills.py"), root],
        capture_output=True, text=True, timeout=120, env=env)
    return Vyvod(p.stdout + p.stderr, p.returncode)


def t_required_global_only_skill_blocks_recovery():
    """11.08: fresh clone kept the KB but lost a required user-global procedure."""
    d = base({})
    home = os.path.join(d, "home")
    canonical = os.path.join(home, ".codex", "skills", "domain-auditor")
    os.makedirs(canonical)
    with open(os.path.join(canonical, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: domain-auditor\n---\n")
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


def t_broken_project_skill_discovery_is_visible():
    """11.08: a declared discovery link must not fail open after a move."""
    d = base({"skills/domain-auditor/SKILL.md": "---\nname: domain-auditor\n---\n"})
    os.makedirs(os.path.join(d, ".agents", "skills"))
    os.makedirs(os.path.join(d, ".claude", "skills"))
    os.symlink("../../skills/missing", os.path.join(d, ".agents", "skills", "domain-auditor"))
    os.symlink("../../skills/domain-auditor", os.path.join(d, ".claude", "skills", "domain-auditor"))
    registry = skill_registry("domain-auditor", "skills/domain-auditor",
                              ".agents/skills/domain-auditor",
                              ".claude/skills/domain-auditor")
    import json
    with open(os.path.join(d, ".kb-skills.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "add", ".kb-skills.json", "skills",
                    ".agents", ".claude"], check=True)
    out = run_skills(d)
    check("битая discovery-ссылка называется ошибкой",
          out.code == 1 and "broken codex discovery symlink" in out,
          out, "missing link cannot look like agent acceptance")
    shutil.rmtree(d, ignore_errors=True)


def t_project_without_specialized_skill_is_valid():
    """11.08: no domain skill is not itself a defect."""
    d = base({"README.md": "ordinary project\n"})
    out = run_skills(d)
    check("проект без specialized skill не получает пустой реестр и ошибку",
          out.code == 0 and "not declared (valid)" in out and "errors=0" in out,
          out, "registry exists only when the project really has project skills")
    shutil.rmtree(d, ignore_errors=True)


def t_capability_registry_expresses_role_not_only_location():
    """Дополнение владельца 11.08: discovery alone does not define a profession."""
    import json
    data = json.loads(skill_text("assets/templates/kb-skills.json"))
    entry = data["skills"][0]
    fields = ("modality", "authority_ladder", "conflict_resolution",
              "evidence_threshold", "stop_conditions", "prohibited_actions")
    out = Vyvod(str(entry), 0)
    check("реестр задаёт профессиональную модальность и границы",
          all(entry.get(field) for field in fields)
          and "project facts" in entry["scope"].lower()
          and "community" in " ".join(entry["authority_ladder"]).lower(),
          out, "role, source ladder, evidence, conflict, stop and prohibited actions")


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


def t_54_apply_requests_safe_credential_cleanup():
    """14.08: every updating project must see the owner's one-time cleanup duty."""
    d = base({"NOW.md": NOW_OK,
              "CLAUDE.md": "# правила\n\nkb_standard_version: 5.3\n"})
    out = run("kb_apply.py", d)
    check("5.4 application names safe Keychain cleanup",
          "[5.4]" in out
          and "credential cleanup" in out
          and "не выводя значения" in out
          and "точными locator-ами" in out
          and "поставь на ротацию" in out
          and "явно разреши Claude/Codex" in out,
          out, "migration verifies Keychain before deleting plaintext duplicates")
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
          "--public --fast --сделать" in ref
          and "GitHub public https://github.com/sugestr/kb-architect" in tpl
          and "не каналом установки" in ref
          and "git ls-remote" in ref
          and "PUBLIC_REPOSITORY" in updater,
          out, "public stable distribution, private development authority")


def t_fast_update_uses_fresh_receipt_without_network():
    """Ночной замер: полный public clone/test стоил 12.94 с при каждом входе."""
    import importlib.util
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
    env = dict(os.environ)
    env["HOME"] = home
    env["KB_ARCHITECT_UPDATE_CACHE"] = cache
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "kb_update.py"),
         "--public", "--fast", "--do"],
        capture_output=True, text=True, timeout=30, env=env)
    out = Vyvod(p.stdout + p.stderr, p.returncode)
    check("fresh receipt skips GitHub clone and full test gate",
          out.code == 0
          and "GitHub не опрашивался" in out
          and "полный gate" not in out
          and "Источник:" not in out,
          out, "fresh local receipt + installed fingerprint is enough inside TTL")
    shutil.rmtree(home, ignore_errors=True)


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
          and "[5.0] при следующем обновлении" in out
          and "ТРЕБУЮТ ДЕЙСТВИЯ" in out, out,
          "парсер пропускает placeholder-маркеры и сохраняет реальное дело 5.0")
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
