#!/usr/bin/env python3
"""Observed 6.x failures and 7.0 heterogeneous-project contracts, in isolation."""

import contextlib
import os
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import kb_due
import kb_check
import kb_index
import kb_lookup
import kb_paths
import kb_skills

HERE = Path(__file__).resolve().parent


class RedesignTests(unittest.TestCase):

    def test_prepare_preserves_visible_candidate_and_observed_acceptance(self):
        from test_kb import compact_role_fixture
        root = Path(compact_role_fixture(accepted=False)).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        registry = root / "PROJECT_ROLES.json"
        source = json.loads(registry.read_text())
        before = registry.read_bytes()
        first = kb_skills.prepare_candidate(root)
        self.assertEqual(first, kb_skills.prepare_candidate(root))
        self.assertEqual(first["templates"]["PROJECT_ROLES.json"], source)
        self.assertEqual(first["prefill_source"], "visible-registry")
        self.assertEqual(first["legacy_prefill"]["role_selectors"], source["roles"])
        self.assertEqual(first["legacy_prefill"]["role_policy"], source["role_posture"])
        self.assertEqual(first["legacy_prefill"]["implicit_required_skills"], [])
        self.assertEqual(registry.read_bytes(), before)
        source["role_posture"] = "invalid declaration"
        source["skills"][0]["version"] = "1.0.0 descriptive legacy version"
        skill = root / source["skills"][0]["canonical"] / "SKILL.md"
        skill.write_text(re.sub(r'^  version:.*\n', '', skill.read_text(), flags=re.MULTILINE))
        kb_skills.write_registry_atomic(registry, source)
        result = kb_skills.prepare_candidate(root)
        self.assertEqual(result["templates"]["PROJECT_ROLES.json"], source)
        self.assertNotEqual(result["action"], "none")
        self.assertEqual(result["mechanical_preflight"]["status"], "needs-action")

    def pin_fixture(self):
        from test_kb import compact_role_fixture
        root = Path(compact_role_fixture(accepted=False)).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        registry = root / "PROJECT_ROLES.json"
        data = json.loads(registry.read_text())
        data["acceptance"]["accepted_skill_sha256"] = {}
        data["acceptance"]["live_test"]["status"] = "PENDING"
        data["acceptance"]["project_check"].update(status="PENDING", execution=None)
        (root / "tests.py").write_text(
            "import json, hashlib\nfrom pathlib import Path\n"
            "r=json.loads(Path('PROJECT_ROLES.json').read_text())\n"
            "p=Path('calls.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
            "for s in r['skills']:\n"
            " assert r['acceptance']['accepted_skill_sha256'].get(s['name']) == "
            "hashlib.sha256((Path(s['canonical'])/'SKILL.md').read_bytes()).hexdigest()\n")
        kb_skills.write_registry_atomic(registry, data)
        subprocess.run(["git", "-C", str(root), "add", "tests.py", "PROJECT_ROLES.json"], check=True)
        return root, registry, data

    def test_runner_pins_missing_hashes_before_one_run_without_accepting_project(self):
        from test_kb import run_skills
        root, registry, data = self.pin_fixture()
        result = run_skills(str(root), execute_project_check=True)
        written = json.loads(registry.read_text())
        self.assertIn("PROJECT_CHECK_EXECUTED_PASS", result)
        self.assertEqual((root / "calls.txt").read_text(), "1")
        for key in ("status", "owner", "live_test", "agents", "open"):
            self.assertEqual(written["acceptance"][key], data["acceptance"][key])
        before_binding = written["acceptance"]["project_check"]["execution"]["input_sha256"]
        written["acceptance"]["status"] = "accepted"
        written["acceptance"]["live_test"]["status"] = "PASS"
        written["acceptance"]["owner"] = {"status": "PASS", "accepted_by": "fixture", "accepted_at": "2026-09-08"}
        kb_skills.write_registry_atomic(registry, written)
        final = run_skills(str(root))
        self.assertEqual(final.code, 0, str(final))
        self.assertEqual(kb_skills.compact_project_check_input_sha256(root, written), before_binding)
        self.assertEqual((root / "calls.txt").read_text(), "1")

    def test_transition_candidate_can_run_check_without_becoming_ready(self):
        from test_kb import run_skills
        for mode in ("valid", "validator-fail", "missing-transition", "invalid-registry",
                     "string-targets", "boolean-covered", "string-gaps", "boolean-gaps",
                     "empty-item"):
            with self.subTest(mode=mode):
                root, registry, data = self.pin_fixture()
                data["role_posture"].update(status="transitioning", transition={
                    "target_roles": [data["roles"][0]["id"]],
                    "covered_work": ["Evidence-grounded draft analysis"],
                    "open_gaps": ["Specialist scope not yet accepted"],
                })
                if mode == "missing-transition":
                    del data["role_posture"]["transition"]["covered_work"]
                elif mode == "invalid-registry":
                    data["roles"][0]["skill"] = "undeclared-method"
                elif mode == "validator-fail":
                    validator = root / "tests.py"
                    validator.write_text(validator.read_text() + "raise SystemExit(2)\n")
                elif mode == "string-targets":
                    data["role_posture"]["transition"]["target_roles"] = "role"
                elif mode == "boolean-covered":
                    data["role_posture"]["transition"]["covered_work"] = True
                elif mode == "string-gaps":
                    data["role_posture"]["transition"]["open_gaps"] = "gap"
                elif mode == "boolean-gaps":
                    data["role_posture"]["transition"]["open_gaps"] = True
                elif mode == "empty-item":
                    data["role_posture"]["transition"]["open_gaps"] = [" "]
                kb_skills.write_registry_atomic(registry, data)
                before = registry.read_bytes()
                result = run_skills(str(root), execute_project_check=True)
                self.assertNotEqual(result.code, 0, str(result))
                if mode not in ("valid", "validator-fail"):
                    self.assertIn("PROJECT_CHECK_EXECUTION_BLOCKED", result)
                    self.assertFalse((root / "calls.txt").exists())
                    self.assertEqual(registry.read_bytes(), before)
                    continue
                outcome = "FAIL" if mode == "validator-fail" else "PASS"
                self.assertIn("PROJECT_CHECK_EXECUTION_FAILED" if outcome == "FAIL"
                              else "PROJECT_CHECK_EXECUTED_PASS", result)
                self.assertIn("role posture is transitioning", result)
                self.assertIn("ROLE_ACCEPTANCE_REQUIRED", result)
                self.assertEqual((root / "calls.txt").read_text(), "1")
                written = json.loads(registry.read_text())
                self.assertEqual(written["acceptance"]["project_check"]["status"], outcome)
                self.assertEqual(written["role_posture"], data["role_posture"])
                for key in ("status", "owner", "live_test", "agents", "open"):
                    self.assertEqual(written["acceptance"][key], data["acceptance"][key])
                # A check receipt cannot close the declared coverage gap, even
                # if a later caller claims owner/live acceptance.
                written["acceptance"].update(status="accepted")
                written["acceptance"]["live_test"]["status"] = "PASS"
                written["acceptance"]["owner"] = {
                    "status": "PASS", "accepted_by": "fixture", "accepted_at": "2026-09-08"}
                kb_skills.write_registry_atomic(registry, written)
                final = run_skills(str(root))
                self.assertNotEqual(final.code, 0, str(final))
                self.assertIn("role posture is transitioning", final)
                self.assertEqual((root / "calls.txt").read_text(), "1")

    def test_runner_does_not_overwrite_wrong_hash_or_run_on_pin_failure(self):
        for mode in ("mismatch", "malformed", "live-pass", "accepted", "write-failure", "budget"):
            with self.subTest(mode=mode):
                root, registry, data = self.pin_fixture()
                if mode == "mismatch":
                    data["acceptance"]["accepted_skill_sha256"] = {"domain-auditor": "0" * 64}
                elif mode == "malformed":
                    data["acceptance"]["accepted_skill_sha256"] = []
                elif mode == "live-pass":
                    data["acceptance"]["live_test"]["status"] = "PASS"
                elif mode == "accepted":
                    data["acceptance"]["status"] = "accepted"
                elif mode == "budget":
                    # Allow the empty-map registry but no headroom for the pin.
                    from test_kb import run_skills
                    output = run_skills(str(root))
                    size = int(re.search(r"static-end-to-end=(\d+)", output).group(1))
                    data["cost_policy"]["scenarios"][0]["accepted_end_to_end_bytes"] = size + 30
                kb_skills.write_registry_atomic(registry, data)
                before = registry.read_bytes()
                cm = patch.object(kb_skills, "write_registry_atomic", side_effect=OSError("fixture pin write failed")) if mode == "write-failure" else contextlib.nullcontext()
                with cm:
                    errors, notes, _ = kb_skills.validate(root, registry, execute_project_check=True)
                self.assertTrue(errors)
                self.assertFalse((root / "calls.txt").exists(), str(errors))
                if mode != "budget":
                    self.assertEqual(registry.read_bytes(), before)
                else:
                    self.assertTrue(any("OPTIMIZATION_REQUIRED" in x for x in errors))
                    self.assertEqual(json.loads(registry.read_text())["acceptance"]["project_check"]["status"], "PENDING")

    def test_runner_checks_written_receipt_cost_and_executes_validator_only_once(self):
        from test_kb import compact_role_fixture, run_skills
        for tight in (False, True):
            with self.subTest(tight_budget=tight):
                root = Path(compact_role_fixture(accepted=True))
                self.addCleanup(shutil.rmtree, root, ignore_errors=True)
                (root / "tests.py").write_text(
                    "from pathlib import Path\n"
                    "p = Path('calls.txt')\n"
                    "p.write_text(str(int(p.read_text()) + 1) if p.exists() else '1')\n")
                registry = root / "PROJECT_ROLES.json"
                data = json.loads(registry.read_text())
                data["acceptance"]["project_check"].update(status="PENDING", execution=None)
                kb_skills.write_registry_atomic(registry, data)
                subprocess.run(["git", "-C", str(root), "add", "tests.py", "PROJECT_ROLES.json"],
                               check=True)
                def costs(output):
                    return [int(x) for x in re.findall(r"static-end-to-end=(\d+)", output)]
                before = costs(run_skills(str(root)))
                self.assertTrue(before)
                if tight:
                    data["cost_policy"]["scenarios"][0]["accepted_end_to_end_bytes"] = before[0] + 64
                    kb_skills.write_registry_atomic(registry, data)
                executed = run_skills(str(root), execute_project_check=True)
                written = run_skills(str(root))
                self.assertEqual((root / "calls.txt").read_text(), "1")
                self.assertEqual(costs(executed), costs(written))
                self.assertEqual(executed.code, written.code)
                self.assertEqual(executed.code, 1 if tight else 0)
                self.assertEqual("OPTIMIZATION_REQUIRED" in executed, tight)

    def test_live_observation_binds_the_tested_agent_without_erasing_other_evidence(self):
        data = kb_skills.neutral_project_roles_template({"supported_agents": ["codex", "claude"]})
        acceptance = data["acceptance"]
        acceptance["live_test"].update(
            status="PASS", agent="codex", fresh_context=True, unforced=True,
            summary="Observed answer", observation={"observed_at": "2026-09-08T00:00:00Z",
                                                     "run_id": "fixture-observation"})
        def errors():
            return kb_skills.light_acceptance_errors(self.root, data, {}, ["codex", "claude"], [])
        acceptance["agents"]["claude"] = {"status": "TESTED", "basis": "live_test"}
        self.assertIn("live_test PASS requires its observed agent to be TESTED", errors())
        self.assertIn("acceptance.agents.claude cannot claim another agent's live_test", errors())
        acceptance["agents"]["codex"] = {"status": "TESTED"}
        self.assertIn("acceptance.agents.codex TESTED needs observed basis", errors())
        acceptance["agents"]["codex"]["basis"] = "live_test"
        acceptance["agents"]["claude"]["basis"] = "Separate historical native observation"
        self.assertFalse(any("TESTED" in e or "another agent" in e for e in errors()))

    def test_unobserved_candidate_cannot_claim_live_pass_by_status_alone(self):
        candidates = [
            kb_skills.neutral_project_roles_template({"supported_agents": ["codex"]}),
            json.loads((HERE.parent / "assets/templates/project-roles.json").read_text()),
        ]
        for data in candidates:
            with self.subTest(source=data["acceptance"]["live_test"].get("agent")):
                acceptance = data["acceptance"]
                live = acceptance["live_test"]
                self.assertIsNone(live["fresh_context"])
                self.assertIsNone(live["unforced"])
                self.assertTrue(all(x["status"] == "UNKNOWN"
                                    for x in acceptance["agents"].values()))
                live.update(status="PASS", agent="codex", summary="Observed answer",
                            observation={"observed_at": "2026-09-08T00:00:00Z",
                                         "run_id": "external-fixture-run"})
                errors = kb_skills.light_acceptance_errors(
                    self.root, data, {}, ["codex"], [])
                self.assertIn("live_test PASS requires fresh_context and unforced", errors)
                live.update(fresh_context=True, unforced=True)
                errors = kb_skills.light_acceptance_errors(
                    self.root, data, {}, ["codex"], [])
                self.assertNotIn("live_test PASS requires fresh_context and unforced", errors)

    def test_relative_current_alias_is_one_owner_but_copies_and_unsafe_links_are_not(self):
        self.save("NOW.md", "The only source.\n")
        self.save("CLAUDE.md", "entry: NOW.md\n")
        alias = self.root / "ops" / "STATUS.md"
        alias.parent.mkdir()
        alias.symlink_to("../NOW.md")
        self.assertEqual(kb_paths.locate(str(self.root), "entry").others, [])
        self.assertEqual(self.run_tool("kb_check.py").returncode, 0)
        (self.root / "CLAUDE.md").unlink()
        self.assertEqual(kb_paths.locate(str(self.root), "entry").others, [])
        for target in (str(self.root / "NOW.md"), "STATUS.md", "missing.md", "../../outside.md"):
            with self.subTest(target=target):
                alias.unlink()
                alias.symlink_to(target)
                self.assertEqual(kb_paths.locate(str(self.root), "entry").others, [str(alias)])
        alias.unlink()
        alias.write_bytes((self.root / "NOW.md").read_bytes())
        self.assertEqual(kb_paths.locate(str(self.root), "entry").others, [str(alias)])
        self.assertEqual(self.run_tool("kb_check.py").returncode, 1)

    def test_existing_file_line_locators_resolve_without_false_missing_links(self):
        self.save("NOW.md", "Current source.\n")
        self.save("src/module.py", "# source\n" * 200)
        self.save("literal:141", "A filename containing a colon.\n")
        links = [f"[source {line}](../src/module.py:{line})" for line in range(141, 173)]
        links.extend([
            "[root path](src/module.py:1)",
            "[root anchored](/src/module.py:4)",
            "[fragment](../src/module.py:2#context)",
            "[query](../src/module.py:3?view=source)",
            "[positive with leading zeros](../src/module.py:001)",
            "[literal filename](../literal:141)",
            "[external](https://example.invalid/module.py:141)",
        ])
        self.save("notes/review.md", "\n".join(links))
        result = self.run_tool("kb_check.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("БИТЫЕ ССЫЛКИ", result.stdout)

    def test_invalid_line_suffixes_and_directory_locators_remain_findings(self):
        self.save("NOW.md", "Current source.\n")
        self.save("src/module.py", "# source\n")
        targets = ("src/module.py:0", "src/module.py:-1", "src/module.py:1:2", "src:1")
        self.save("review.md", "\n".join(f"[source]({target})" for target in targets))
        result = self.run_tool("kb_check.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for target in targets:
            self.assertIn(f"review.md → {target}", result.stdout)

    def test_missing_file_locator_is_a_finding_without_claiming_lost_knowledge(self):
        self.save("NOW.md", "Current source.\n")
        self.save("review.md", "[source](missing.py:141)\n[plain](absent.md)\n")
        result = self.run_tool("kb_check.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("review.md → missing.py:141", result.stdout)
        self.assertIn("review.md → absent.md", result.stdout)
        self.assertNotIn("уже потеряно", result.stdout)

    def test_unknown_inbox_recipient_does_not_prove_the_recipient_never_saw_it(self):
        self.save("NOW.md", "Current source.\n")
        self.save("_inbox/incoming.md", "---\ntype: agent-message\nmessage_id: m1\n"
                  "from_project: collector\nto_project: old-project\n"
                  "delivery_state: delivered\n---\nIncoming.\n")
        self.save("_inbox/INDEX.md", "m1: accepted by this project.\n")
        result = self.run_tool("kb_check.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("incoming.md", result.stdout)
        self.assertNotIn("адресат этого не видел", result.stdout)
        self.assertNotIn("не доставлено", result.stdout)
        self.save("CLAUDE.md", "project_aliases: old-project\n")
        resolved = self.run_tool("kb_check.py")
        self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)

    def test_outgoing_inbox_copy_does_not_establish_delivery_outcome(self):
        self.save("NOW.md", "Current source.\n")
        self.save("_inbox/outgoing.md", "---\ntype: agent-message\nmessage_id: m1\n"
                  "from_project: project\nto_project: another-project\n"
                  "delivery_state: delivered\n---\nOutgoing copy.\n")
        result = self.run_tool("kb_check.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("outgoing.md", result.stdout)
        self.assertNotIn("не доставлено", result.stdout)
        self.assertNotIn("До этого состояние — prepared", result.stdout)

    def test_inbox_identity_does_not_confuse_related_project_names(self):
        self.init_git()
        self.git('remote', 'add', 'origin', 'https://example.invalid/owner/shop.git')
        self.save('CLAUDE.md', 'project_aliases: family-alias, "Old Shop"\n')
        self.save('NOW.md', 'Current source.\n')
        names = kb_check.imena_proekta(str(self.root))
        self.assertTrue(kb_check.nash(' `SHOP` ', names))
        self.assertTrue(kb_check.nash('old shop', names))
        self.assertTrue(kb_check.nash('family-alias', names))
        for value in ('shop-sl', 'shop-odoo', 'other-shop', ''):
            self.assertFalse(kb_check.nash(value, names), value)
        self.save('_inbox/incoming.md', '---\ntype: agent-message\nfrom_project: shop-sl\nto_project: shop\ndelivery_state: delivered\n---\nIncoming.\n')
        self.save('_inbox/outgoing.md', '---\ntype: agent-message\nfrom_project: old shop\nto_project: shop-sl\ndelivery_state: delivered\n---\nOutgoing.\n')
        result = self.run_tool('kb_check.py')
        self.assertIn('outgoing.md', result.stdout)
        # Addressing only; an untraced inbound is a separate knowledge debt below.
        self.assertNotIn('incoming.md', result.stdout.split('ДОЛГИ ЗНАНИЯ')[0])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kb7-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "project"
        self.root.mkdir()

    def run_tool(self, script, *args):
        return subprocess.run([sys.executable, str(HERE / script), str(self.root), *map(str, args)],
                              capture_output=True, text=True, timeout=30)

    def git(self, *args, root=None):
        return subprocess.run(["git", "-C", str(root or self.root), *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def init_git(self, root=None):
        self.git("init", "-q", "-b", "main", root=root)
        self.git("config", "user.name", "Fixture", root=root)
        self.git("config", "user.email", "fixture@example.invalid", root=root)

    def save(self, name, value, root=None):
        path = (root or self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path

    def commit(self, *paths, root=None):
        self.git("add", "--", *paths, root=root)
        self.git("commit", "-qm", "fixture", root=root)

    def route(self, key, targets):
        return {"id": key, "description": "Fixture knowledge", "load_when": ["fixture task"],
                "aliases": [key], "targets": targets}

    def index(self, routes, current=None, root=None):
        value = {"schema": 1, "routes": routes}
        if current is not None:
            value["current"] = current
        self.save("KNOWLEDGE_INDEX.json", value, root)
        self.git("add", "--", "KNOWLEDGE_INDEX.json", root=root)
        return (root or self.root) / "KNOWLEDGE_INDEX.json"

    def begin(self, support="PROJECT", challenge="DENIED"):
        receipt = self.base / "evidence.json"
        result = self.run_tool("kb_lookup.py", "--claim", "Project is approved", "--receipt", receipt,
                               "--support", support, "--challenge", challenge)
        self.assertEqual(result.returncode, 1, result.stderr)
        return receipt, json.loads(receipt.read_text()), result

    def test_changed_branch_path_is_not_lost_or_declared_canonical(self):
        self.init_git()
        self.save("state.md", "Payment is awaiting confirmation.\n")
        self.commit("state.md")
        self.git("checkout", "-qb", "case")
        self.save("state.md", "Payment PAID receipt R123.\n")
        self.commit("state.md")
        self.git("checkout", "-q", "main")
        receipt, data, _ = self.begin("awaiting", "PAID")
        self.assertEqual({(c["ref"], c["path"]) for c in data["candidates"]},
                         {(None, "state.md"), ("case", "state.md")})
        output = self.run_tool("kb_check.py")
        self.assertIn("РАЗЛИЧАЮТСЯ ВЕРСИИ В ВЕТКАХ", output.stdout)
        self.assertNotIn("СОДЕРЖИМОЕ УЖЕ В КАНОНЕ", output.stdout)
        self.assertNotIn("работа доставлена во второй контур", output.stdout)
        self.assertNotIn("поиск по базе честно врёт", output.stdout)
        result = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "supported",
                               "--supports", "c1", "--reason", "old state only")
        self.assertEqual(result.returncode, 2)

    def test_cherry_pick_then_edit_is_not_reported_as_proven_missing_work(self):
        self.init_git()
        self.save("NOW.md", "Current.\n")
        self.save("state.md", "Initial evidence.\n")
        self.commit("NOW.md", "state.md")
        self.git("checkout", "-qb", "case")
        self.save("state.md", "Retained evidence.\n")
        self.commit("state.md")
        tip = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        self.save("other.md", "Independent work.\n")
        self.commit("other.md")
        self.git("cherry-pick", tip)
        self.save("state.md", "Retained evidence.\nLater clarification.\n")
        self.commit("state.md")
        self.assertTrue(self.git("cherry", "HEAD", "case").startswith("-"))
        for tool in ("kb_check.py", "kb_due.py"):
            result = self.run_tool(tool)
            self.assertIn("case", result.stdout)
            self.assertNotIn("НЕ СЛИТО В КАНОН", result.stdout)
            self.assertNotIn("этой работы не существует", result.stdout)
        # Reversal stays visible: patch equivalence must not suppress a loss.
        self.save("state.md", "Initial evidence.\n")
        self.commit("state.md")
        refs, why = kb_paths.unmerged_refs(str(self.root))
        self.assertIsNone(why)
        self.assertIn("state.md", refs[0].outside_name)
        # A new branch-only addition must remain discoverable as evidence.
        self.git("checkout", "-q", "case")
        self.save("new.md", "Unique source receipt.\n")
        self.commit("new.md")
        self.git("checkout", "-q", "main")
        refs, why = kb_paths.unmerged_refs(str(self.root))
        self.assertIsNone(why)
        self.assertIn("new.md", refs[0].outside_name)

    def test_role_selection_follows_legacy_pointer_and_rejects_cycles(self):
        self.save('.kb-skills.json', {'status': 'superseded', 'superseded_by': 'PROJECT_ROLES.json'})
        self.save('PROJECT_ROLES.json', {'skills': [
            {'name': 'method', 'canonical': 'skills/method'},
            {'name': 'specialist', 'canonical': 'skills/specialist'}], 'roles': [
            {'id': 'base', 'skill': 'method', 'knowledge_routes': ['evidence']},
            {'id': 'case', 'extends': 'base', 'skill': 'specialist', 'knowledge_routes': ['case']}]})
        result = self.run_tool('kb_skills.py', '--select', 'case')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['registry'].endswith('PROJECT_ROLES.json'))
        self.assertTrue(data['notes'][0].startswith('ROLE_REGISTRY_MOVED'))
        self.save('PROJECT_ROLES.json', {'status': 'superseded', 'superseded_by': '.kb-skills.json'})
        result = self.run_tool('kb_skills.py', '--select', 'case')
        self.assertEqual(result.returncode, 1)
        self.assertIn('registry cycle', result.stdout)
        self.save('.kb-skills.json', {'status': 'superseded', 'superseded_by': '../elsewhere.json'})
        result = self.run_tool('kb_skills.py', '--select', 'case')
        self.assertEqual(result.returncode, 1)
        self.assertIn('leaves project root', result.stdout)

    def test_identical_blob_at_same_path_is_deduplicated(self):
        self.init_git()
        self.save("state.md", "PROJECT initial\n")
        self.commit("state.md")
        self.git("checkout", "-qb", "case")
        self.save("state.md", "PROJECT current\n")
        self.commit("state.md")
        self.git("checkout", "-q", "main")
        self.save("state.md", "PROJECT current\n")
        self.commit("state.md")
        _, data, _ = self.begin()
        self.assertEqual(len(data["candidates"]), 1)

    def test_branch_search_keeps_subproject_scope_and_literal_topics(self):
        self.init_git()
        self.save("child/state.md", "pending\n")
        self.save("other.md", "pending\n")
        self.commit("child/state.md", "other.md")
        self.git("checkout", "-qb", "case")
        self.save("child/state.md", "PROJECT [approved]\n")
        self.save("other.md", "PROJECT [approved]\n")
        self.commit("child/state.md", "other.md")
        self.git("checkout", "-q", "main")
        errors = []
        hits = kb_lookup.search_refs(str(self.root / "child"), ["case"], ["[approved]"], errors)
        self.assertEqual([(ref, path) for ref, path, _ in hits], [("case", "state.md")])
        self.assertEqual(errors, [])

    def test_ref_read_error_is_reported(self):
        self.init_git()
        self.save("a.md", "PROJECT\n")
        self.commit("a.md")
        errors = []
        self.assertEqual(kb_lookup.search_refs(str(self.root), ["missing-ref"], ["PROJECT"], errors), [])
        self.assertTrue(errors)

    def test_assessment_is_independent_of_discovery_query(self):
        self.save("a.md", "PROJECT approved\n")
        self.save("b.md", "PROJECT approval revoked\n")
        receipt, _, _ = self.begin()
        result = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "qualified",
                               "--supports", "c1", "--limits", "c2", "--reason", "revocation limits earlier approval")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_document_can_support_and_limit(self):
        self.save("a.md", "PROJECT approved in January, revoked in February\n")
        receipt, _, _ = self.begin()
        result = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "qualified",
                               "--supports", "c1", "--limits", "c1", "--reason", "different dated sections")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_large_candidate_set_pages_and_resumes_without_narrowing(self):
        for i in range(220):
            self.save(f"{i:03}.md", f"PROJECT evidence {i}\n")
        receipt, data, output = self.begin()
        self.assertEqual(len(data["candidates"]), 220)
        self.assertEqual(data["status"], "review_required")
        self.assertLess(len(output.stdout.encode()), 14000)
        offset = int(output.stdout.split("NEXT_OFFSET=")[1].splitlines()[0])
        page = self.run_tool("kb_lookup.py", "--page", receipt, "--offset", offset)
        self.assertIn("c220", page.stdout)
        self.assertIn("NEXT_OFFSET=END", page.stdout)
        reviewed = self.run_tool("kb_lookup.py", "--review", receipt, "--supports", "c1", "--reason", "read first")
        self.assertEqual(reviewed.returncode, 1)
        blocked = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "supported", "--reason", "not enough")
        self.assertEqual(blocked.returncode, 2)
        tail = [arg for i in range(2, 221) for arg in ("--irrelevant", f"c{i}")]
        self.assertEqual(self.run_tool("kb_lookup.py", "--review", receipt, *tail, "--reason", "reviewed remaining documents").returncode, 1)
        final = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "supported", "--reason", "full review")
        self.assertEqual(final.returncode, 0, final.stderr)

    def test_unknown_records_unreviewed_without_promoting_fact(self):
        self.save("a.md", "PROJECT evidence\n")
        receipt, _, _ = self.begin()
        result = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "unknown", "--reason", "interrupted")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(receipt.read_text())["review"]["unreviewed_ids"], ["c1"])

    def test_changed_source_invalidates_partial_review(self):
        self.save("a.md", "PROJECT evidence\n")
        receipt, _, _ = self.begin()
        self.run_tool("kb_lookup.py", "--review", receipt, "--supports", "c1", "--reason", "read")
        self.save("a.md", "PROJECT now revoked\n")
        result = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "supported", "--reason", "stale")
        self.assertEqual(result.returncode, 2)

    def test_negated_or_quoted_correction_is_not_closed(self):
        for value in ("- NOW.md: не учтено, не закрыт", "- example: closed", "> ✔ закрыто", "- `✔ закрыто` is an example"):
            with self.subTest(value=value):
                self.assertEqual(kb_due.correction_status(value), "unknown")
        self.assertEqual(kb_due.correction_status("- defect\n  ✔ закрыто 2026-09-05"), "closed")
        self.assertEqual(kb_due.correction_status("- defect\n  status: closed\n  status: open"), "open")

    def test_custom_init_and_invalid_path_preflight(self):
        result = self.run_tool("kb_init.py", "--knowledge-dir", "kb")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "kb").is_dir())
        self.assertEqual((self.root / "AGENTS.md").resolve(), self.root / "CLAUDE.md")
        missing = self.base / "not-created"
        result = subprocess.run([sys.executable, str(HERE / "kb_init.py"), str(missing), "--knowledge-dir", "../escape"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(missing.exists())

    def test_current_section_resolves_without_now_file(self):
        self.init_git()
        self.save("PROJECT.md", "# Project\n\n## Current\nOne open task\n")
        self.git("add", "--", "PROJECT.md")
        self.index([self.route("attention", [{"kind": "section", "path": "PROJECT.md", "section": "Current"}])], "attention")
        result = self.run_tool("kb_index.py", "--current", "--json")
        self.assertEqual(result.returncode, 0, result.stdout)
        endpoint = json.loads(result.stdout)["resolved"][0]
        self.assertEqual(endpoint["section"], "Current")
        self.assertEqual(endpoint["execution"], "NOT_READ")

    def test_init_extended_has_one_resolvable_current_and_preserves_it_on_repeat(self):
        self.init_git()
        result = self.run_tool("kb_init.py", "--extended")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "NOW.md").is_file())
        self.assertFalse((self.root / "STATUS.md").exists())
        self.git("add", "--", "CLAUDE.md", "AGENTS.md", "NOW.md", "KNOWLEDGE_INDEX.json")
        result = self.run_tool("kb_index.py", "--require-now", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([x["path"] for x in json.loads(result.stdout)["resolved"]],
                         [str(self.root / "NOW.md")])
        self.save("NOW.md", "Important owner decision remains open.\n")
        before = (self.root / "NOW.md").read_bytes()
        index_before = (self.root / "KNOWLEDGE_INDEX.json").read_bytes()
        self.assertEqual(self.run_tool("kb_init.py", "--extended").returncode, 0)
        self.assertEqual((self.root / "NOW.md").read_bytes(), before)
        self.assertEqual((self.root / "KNOWLEDGE_INDEX.json").read_bytes(), index_before)

    def test_existing_current_requires_adoption_before_init_writes_anything(self):
        self.save("CURRENT.md", "Only original state.\n")
        result = self.run_tool("kb_init.py", "--force", "--extended")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([x.name for x in self.root.iterdir()], ["CURRENT.md"])
        self.assertEqual((self.root / "CURRENT.md").read_text(), "Only original state.\n")
        self.assertIn("CURRENT_ADOPTION_REQUIRED", result.stdout)

    def test_current_standard_accepts_only_now_and_keeps_legacy_reader(self):
        self.init_git()
        self.save("NOW.md", "The current owner.\n")
        self.save("CURRENT.md", "Legacy state.\n")
        self.git("add", "--", "NOW.md", "CURRENT.md")
        self.index([self.route("attention", [{"kind": "file", "path": "CURRENT.md"}])], "attention")
        self.assertEqual(self.run_tool("kb_index.py", "--current").returncode, 0)
        self.assertEqual(self.run_tool("kb_index.py", "--require-now").returncode, 1)
        self.index([self.route("attention", [{"kind": "file", "path": "NOW.md"},
                                              {"kind": "file", "path": "CURRENT.md"}])], "attention")
        self.assertEqual(self.run_tool("kb_index.py", "--require-now").returncode, 1)
        self.index([self.route("attention", [{"kind": "file", "path": "NOW.md"}])], "attention")
        self.assertEqual(self.run_tool("kb_index.py", "--require-now").returncode, 0)
        (self.root / "NOW.md").unlink()
        (self.root / "NOW.md").symlink_to("CURRENT.md")
        self.git("add", "--", "NOW.md")
        self.assertEqual(self.run_tool("kb_index.py", "--require-now").returncode, 1)
        (self.root / "NOW.md").unlink()
        (self.root / "CURRENT.md").rename(self.root / "NOW.md")
        (self.root / "CURRENT.md").symlink_to("NOW.md")
        self.git("add", "--", "NOW.md", "CURRENT.md")
        result = self.run_tool("kb_index.py", "--require-now")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("legacy current alias remains: CURRENT.md", result.stdout)
        (self.root / "CURRENT.md").unlink()
        self.assertEqual(self.run_tool("kb_index.py", "--require-now").returncode, 0)
        (self.root / "ops").mkdir()
        (self.root / "ops" / "STATUS.md").symlink_to("../NOW.md")
        result = self.run_tool("kb_index.py", "--require-now")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("legacy current alias remains: ops/STATUS.md", result.stdout)
        (self.root / "ops" / "STATUS.md").unlink()
        self.assertEqual(self.run_tool("kb_index.py", "--require-now").returncode, 0)

    def test_database_route_is_a_recipe_not_automatic_execution(self):
        self.init_git()
        self.save("query.md", "Read-only SELECT with source_id, never update.\n")
        self.git("add", "--", "query.md")
        db = sqlite3.connect(self.root / "facts.db")
        db.execute("CREATE TABLE facts(value TEXT, source_id TEXT)")
        db.execute("INSERT INTO facts VALUES('42', 'original:row-1')")
        db.commit()
        db.close()
        query = {"kind": "query", "path": "query.md", "command": ["sqlite3", "-readonly", "facts.db", "SELECT * FROM facts"],
                 "read_only": True, "coverage": "one imported fixture record", "provenance": "source_id from original row"}
        self.index([self.route("facts", [query])])
        before = (self.root / "facts.db").read_bytes()
        result = self.run_tool("kb_index.py", "--require", "facts", "--json")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["resolved"][0]["execution"], "NOT_RUN")
        self.assertEqual((self.root / "facts.db").read_bytes(), before)
        with sqlite3.connect((self.root / "facts.db").as_uri() + "?mode=ro", uri=True) as connection:
            self.assertEqual(connection.execute("SELECT * FROM facts").fetchall(), [("42", "original:row-1")])

    def test_project_target_is_explicit_and_cycle_is_visible(self):
        self.init_git()
        other = self.base / "case"
        other.mkdir()
        self.init_git(other)
        self.save("STATUS.md", "# Current\nA pending case\n", other)
        self.git("add", "--", "STATUS.md", root=other)
        self.index([self.route("current", [{"kind": "file", "path": "STATUS.md"}])], "current", other)
        pointer = {"kind": "project", "path": "../case/KNOWLEDGE_INDEX.json", "route": "current",
                   "relation": "contains", "access": "read-only", "scope": "current summary only"}
        path = self.index([self.route("case", [pointer])])
        found, errors = kb_index.resolve(self.root, path, "case")
        self.assertEqual(errors, [])
        self.assertEqual(found[0]["path"], str(other / "STATUS.md"))
        self.assertEqual(found[0]["via"][0]["scope"], "current summary only")
        self.index([self.route("current", [{**pointer, "path": "../project/KNOWLEDGE_INDEX.json", "route": "case"}])], "current", other)
        _, errors = kb_index.resolve(self.root, path, "case")
        self.assertTrue(any("cycle" in error for error in errors), errors)

    def test_unknown_current_is_not_empty_life(self):
        self.init_git()
        self.index([])
        result = self.run_tool("kb_index.py", "--current", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNKNOWN", result.stdout)

    def test_broken_unrelated_route_does_not_block_selected_work(self):
        self.init_git()
        self.save("ok.md", "Available evidence")
        self.git("add", "--", "ok.md")
        self.index([self.route("ok", [{"kind": "file", "path": "ok.md"}]),
                    self.route("bad", [{"kind": "file", "path": "missing.md"}])])
        result = self.run_tool("kb_index.py", "--require", "ok", "--json")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.run_tool("kb_index.py").returncode, 1)

    def test_diagnostics_do_not_update_the_executing_skill(self):
        self.save("CLAUDE.md", "# Project\n\n## Сейчас\nОбновлено: 2026-09-05\nPending\n")
        with patch.object(kb_paths, "published_version", side_effect=AssertionError("network probe")), \
                patch.object(kb_paths, "pull_skill", side_effect=AssertionError("mutation")), \
                patch.object(sys, "argv", ["kb_due.py", str(self.root)]), \
                contextlib.redirect_stdout(io.StringIO()):
            kb_due.main()

    def test_due_migration_command_uses_relocated_skill_and_exact_project(self):
        # Range Rover: the consumer has no scripts/kb_apply.py. The printed
        # command must survive spaces/quotes and a different caller cwd.
        project = self.base / "vehicle's dossier"
        self.root.rename(project)
        self.root = project
        self.init_git()
        self.save("CLAUDE.md", "# Project\nkb_standard_version: 6.2\n")
        self.save("NOW.md", "# Current\nPending evidence\n")
        self.commit("CLAUDE.md", "NOW.md")
        installed = self.base / "installed skill's copy"
        shutil.copytree(HERE.parent, installed,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        due = subprocess.run([sys.executable, str(installed / "scripts/kb_due.py"),
                              str(self.root)], cwd=self.base, capture_output=True,
                             text=True, check=True)
        command = re.search(r"`([^`]*kb_apply\.py[^`]*)`", due.stdout)
        self.assertIsNotNone(command, due.stdout)
        argv = shlex.split(command.group(1))
        self.assertEqual(Path(argv[1]), installed / "scripts/kb_apply.py")
        self.assertEqual(Path(argv[2]), self.root)
        result = subprocess.run(argv, cwd=self.base, capture_output=True, text=True)
        self.assertIn("NEEDS_APPLICATION", result.stdout, result.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_role_specialization_deduplicates_and_keeps_siblings_out(self):
        roles = {"adviser": {"skill": "general", "knowledge_routes": ["sources"]},
                 "specialist": {"extends": "adviser", "skill": "special", "knowledge_routes": ["case"]},
                 "unrelated": {"skill": "other", "knowledge_routes": ["other"]}}
        data = {"roles": [{"id": key, **value} for key, value in roles.items()],
                "skills": [{"name": name, "canonical": "skills/" + name} for name in ("general", "special", "other")]}
        result = kb_skills.selection_plan(data, ["specialist", "adviser"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["roles"], ["adviser", "specialist"])
        self.assertEqual(result["knowledge_routes"], ["sources", "case"])
        roles["adviser"]["extends"] = "specialist"
        self.assertTrue(kb_skills.role_closure(roles, ["specialist"])[1])
        roles["adviser"]["extends"] = "absent"
        self.assertTrue(kb_skills.role_closure(roles, ["specialist"])[1])


class ReadSetTests(unittest.TestCase):
    def fixture(self):
        from test_kb import compact_role_fixture
        root = Path(compact_role_fixture(accepted=True)).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root, json.loads((root / "PROJECT_ROLES.json").read_text())

    def measure(self, root, data):
        import hashlib
        role = root / "skills/domain-auditor/SKILL.md"
        data["acceptance"]["accepted_skill_sha256"]["domain-auditor"] = \
            hashlib.sha256(role.read_bytes()).hexdigest()
        subprocess.run(["git", "-C", str(root), "add", "--", "knowledge", "skills",
                        "KNOWLEDGE_INDEX.json"], check=True, capture_output=True)
        validator, error = kb_skills.project_validator_binding(root, "python3 tests.py")
        self.assertIsNone(error)
        data["acceptance"]["project_check"]["execution"]["input_sha256"] = \
            kb_skills.compact_project_check_input_sha256(root, data, validator)
        registry = root / "PROJECT_ROLES.json"
        registry.write_text(json.dumps(data))
        errors, notes, _ = kb_skills.validate_visible(root, data, registry, runtime_roots=[])
        self.assertEqual(errors, [])
        cost = next(note for note in notes if "static-route=" in note)
        return int(re.search(r"static-route=(\d+)", cost)[1]), notes

    def test_alias_and_category_overlap_count_once(self):
        root, data = self.fixture()
        before, _ = self.measure(root, data)
        (root / "knowledge/alias.md").symlink_to("case.md")
        data["cost_policy"]["scenarios"][0]["route_files"].extend(
            ["knowledge/alias.md", "skills/domain-auditor/SKILL.md"])
        self.assertEqual(before, self.measure(root, data)[0])
        support = root / "skills/domain-auditor/references/support.md"
        support.parent.mkdir()
        support.write_text("Support" * 100)
        role = support.parent.parent / "SKILL.md"
        role.write_text(role.read_text() + "\nRead [support](references/support.md).\n")
        before, _ = self.measure(root, data)
        data["cost_policy"]["scenarios"][0]["route_files"].append(
            "skills/domain-auditor/references/support.md")
        self.assertEqual(before, self.measure(root, data)[0])

    def test_section_growth_and_full_file_union(self):
        root, data = self.fixture()
        index_path = root / "KNOWLEDGE_INDEX.json"
        index = json.loads(index_path.read_text())
        route = index["routes"][0]
        route.pop("paths")
        route["targets"] = [{"kind": "section", "path": "knowledge/case.md", "section": "Selected"}]
        index_path.write_text(json.dumps(index))
        source = root / "knowledge/case.md"
        selected = "# Selected\nФакт\n## Child\nIncluded\n"
        source.write_text(selected + "# Other\nSmall\n")
        before, _ = self.measure(root, data)
        source.write_text(selected + "# Other\n" + "x" * 100000)
        self.assertEqual(before, self.measure(root, data)[0])
        data["cost_policy"]["scenarios"][0]["accepted_end_to_end_bytes"] = 50000
        self.measure(root, data)  # Unrelated growth must not trip the selected budget.
        route["targets"].append({"kind": "section", "path": "knowledge/case.md", "section": "Child"})
        index_path.write_text(json.dumps(index))
        self.assertEqual(before, self.measure(root, data)[0])
        route["targets"].append({"kind": "file", "path": "knowledge/case.md"})
        index_path.write_text(json.dumps(index))
        data["cost_policy"]["scenarios"][0]["accepted_end_to_end_bytes"] = 300000
        self.assertEqual(self.measure(root, data)[0], before - len(selected.encode()) + source.stat().st_size)

    def test_shared_method_selectors_keep_unrelated_routes_out(self):
        import copy
        root, data = self.fixture()
        first_role = data["roles"][0]["id"]
        second = copy.deepcopy(data["roles"][0])
        second.update(id="other-selector", load_when=["A different business question"],
                      knowledge_routes=["other-state"])
        data["roles"].append(second)
        index_path = root / "KNOWLEDGE_INDEX.json"
        index = json.loads(index_path.read_text())
        route = copy.deepcopy(index["routes"][0])
        route.update(id="other-state", paths=["knowledge/other.md"])
        index["routes"].append(route)
        index_path.write_text(json.dumps(index))
        other = root / "knowledge/other.md"
        other.write_text("Small")
        scenario = copy.deepcopy(data["cost_policy"]["scenarios"][0])
        scenario.update(id="all-selectors", roles=[first_role, "other-selector"])
        scenario["route_files"].append("knowledge/other.md")
        data["cost_policy"]["scenarios"].append(scenario)
        data["cost_policy"]["all_roles_scenario"] = "all-selectors"
        before, notes = self.measure(root, data)
        other.write_text("x" * 100000)
        after, newer = self.measure(root, data)
        self.assertEqual(before, after)
        combined = lambda rows: int(re.search(r"static-route=(\d+)",
            next(row for row in rows if row.startswith("route-cost all-selectors:")))[1])
        self.assertEqual(combined(newer) - combined(notes), 100000 - len("Small"))

    def test_invalid_target_is_structured_failure(self):
        root, data = self.fixture()
        index_path = root / "KNOWLEDGE_INDEX.json"
        index = json.loads(index_path.read_text())
        route = index["routes"][0]
        route.pop("paths")
        for invalid in (42, [], None):
            route["targets"] = [{"kind": "section", "path": invalid, "section": "Selected"}]
            index_path.write_text(json.dumps(index))
            errors, _, _ = kb_skills.validate_visible(root, data, root / "PROJECT_ROLES.json", runtime_roots=[])
            self.assertTrue(any("path must be" in error for error in errors), errors)

    def test_extra_alias_is_an_explicit_whole_file_read(self):
        root, data = self.fixture()
        source = root / "knowledge/case.md"
        source.write_text("# Selected\nFact\n# Other\n" + "x" * 10000)
        index_path = root / "KNOWLEDGE_INDEX.json"
        index = json.loads(index_path.read_text())
        index["routes"][0].pop("paths")
        index["routes"][0]["targets"] = [{"kind": "section", "path": "knowledge/case.md", "section": "Selected"}]
        index_path.write_text(json.dumps(index))
        before, _ = self.measure(root, data)
        (root / "knowledge/whole.md").symlink_to("case.md")
        data["cost_policy"]["scenarios"][0]["route_files"].append("knowledge/whole.md")
        self.assertEqual(self.measure(root, data)[0], before - len("# Selected\nFact\n") + source.stat().st_size)

    def test_support_closure_scope_is_explicit(self):
        root, data = self.fixture()
        support = root / "skills/domain-auditor/references/first.md"
        support.parent.mkdir()
        support.write_text("Before answering read [detail](second.md).\n")
        deep = support.with_name("second.md")
        deep.write_text("x" * 100)
        role = support.parent.parent / "SKILL.md"
        role.write_text(role.read_text() + "\nRead [support](references/first.md).\n")
        before, notes = self.measure(root, data)
        self.assertTrue(any("COST_SCOPE_PARTIAL" in note for note in notes))
        deep.write_text("x" * 100000)
        after, notes = self.measure(root, data)
        self.assertEqual(before, after)
        self.assertTrue(any("COST_SCOPE_PARTIAL" in note for note in notes))
        data["cost_policy"]["scenarios"][0]["route_files"].append(
            "skills/domain-auditor/references/second.md")
        self.assertEqual(self.measure(root, data)[0], after + 100000)

    def test_section_parser_ignores_code_and_rejects_ambiguous_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sections.md"
            path.write_text("# Selected\n```md\n# Selected\n```\n## Child\nyes\n# Other\nno\n")
            start, end = kb_index.section_span(path, "Selected")
            self.assertEqual(path.read_bytes()[start:end], path.read_bytes().split(b"# Other")[0])
            selected = "# Selected\n```md\n```not-a-close\n# Other\n" + "x" * 10000 + "\n```\n"
            path.write_text(selected + "   # Real sibling\noutside\n")
            self.assertEqual(kb_index.section_span(path, "Selected"), (0, len(selected.encode())))
            self.assertEqual(kb_index.section_span(path, "Real sibling")[0], len(selected.encode()))
            path.write_text(path.read_text() + "# Selected\nagain\n")
            with self.assertRaises(ValueError):
                kb_index.section_span(path, "Selected")


class CoverageTests(unittest.TestCase):
    """UAD 14.09/12.09.2026: knowledge without a road and derived files without a source."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit = RedesignTests.commit
    index = RedesignTests.index

    def seed(self):
        self.init_git()
        self.save("CLAUDE.md", "# Project\nвход: NOW.md\n")
        self.save("NOW.md", "# Current\nSee [area A](knowledge/a/00-entry.md).\n")
        self.save("knowledge/a/00-entry.md", "# A\nDetails in `knowledge/a/01-linked.md`.\n")
        self.save("knowledge/a/01-linked.md", "# Linked\nreachable through the entry\n")
        self.save("knowledge/b/01-orphan.md", "# Orphan\nno route, no link\n")
        self.index([{"id": "project-current", "description": "current", "load_when": ["orientation"],
                     "aliases": ["now"], "paths": ["NOW.md"]},
                    {"id": "area-a", "description": "area a", "load_when": ["question about a"],
                     "aliases": ["a"], "paths": ["knowledge/a/00-entry.md"]}], current="project-current")
        self.commit("CLAUDE.md", "NOW.md", "knowledge", "KNOWLEDGE_INDEX.json")

    def test_unreachable_knowledge_is_a_finding_and_links_count_as_roads(self):
        self.seed()
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["status"], "FINDING")
        self.assertEqual(report["files"], 3)
        self.assertEqual(report["routed"], 1)
        self.assertEqual(report["unreachable"], ["knowledge/b/01-orphan.md"])
        self.assertEqual(report["by_area"], {"knowledge/b": 1})
        result = self.run_tool("kb_index.py", "--coverage")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("knowledge/b/01-orphan.md", result.stdout)
        check = self.run_tool("kb_check.py")
        self.assertEqual(check.returncode, 1, check.stdout)
        self.assertIn("ЗНАНИЕ БЕЗ ДОРОГИ ОТ ИНДЕКСА — 1 из 3", check.stdout)
        self.assertIn("достижимость знания — FINDING (2/3 в knowledge)", check.stdout)

    def test_route_or_link_to_the_orphan_clears_the_finding(self):
        self.seed()
        self.save("knowledge/a/00-entry.md", "# A\n`knowledge/a/01-linked.md` and [b](../b/01-orphan.md)\n")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["unreachable"], [])
        self.assertEqual(self.run_tool("kb_index.py", "--coverage").returncode, 0)

    def test_untracked_files_and_declared_allowance_do_not_hide_or_inflate(self):
        self.seed()
        self.save("knowledge/b/02-untracked.md", "# Not in git\n")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["files"], 3, "only Git-tracked knowledge is measured")
        self.save("CLAUDE.md", "# Project\nвход: NOW.md\nдопустимо без дороги: 1\n")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["allowed"], 1)
        self.assertEqual(report["unreachable"], ["knowledge/b/01-orphan.md"], "still listed, not hidden")

    def test_missing_knowledge_root_is_not_checked_rather_than_clean(self):
        self.init_git()
        self.save("NOW.md", "# Current\n")
        self.save("kb/01-note.md", "# Note\n")
        self.index([{"id": "project-current", "description": "current", "load_when": ["orientation"],
                     "aliases": ["now"], "paths": ["NOW.md"]}], current="project-current")
        self.commit("NOW.md", "kb", "KNOWLEDGE_INDEX.json")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["status"], "NOT_CHECKED")
        check = self.run_tool("kb_check.py")
        self.assertIn("достижимость знания — NOT_CHECKED", check.stdout)
        self.assertNotIn("достижимость знания — PASS", check.stdout)
        self.save("CLAUDE.md", "# Project\nкорень знания: kb\n")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["status"], "FINDING")
        self.assertEqual(report["roots"], ["kb"])
        self.assertEqual(report["unreachable"], ["kb/01-note.md"])

    def test_ephemeral_generated_from_is_a_finding_but_named_canons_are_not(self):
        self.init_git()
        self.save("NOW.md", "# Current\n")
        self.save("report.md", "---\ngenerated: true\ngenerated_from: scratchpad/rerun\n---\n# Report\n")
        self.save("daily.md", "---\ngenerated_from: живая база (скрипт scratchpad an9.py)\n---\n# Daily\n")
        self.save("tmp.md", "---\ngenerated_from: /tmp/kb-run/build.py\n---\n# Tmp\n")
        for name, value in (("db.md", "живая база; повторяется скриптом §7"),
                            ("sheet.md", "Google Sheet «2017 анализ SEO по pr»"),
                            ("sql.md", "confident.pays / ap_members (ok=1)"),
                            ("git.md", "git CPPJ (flow_*.rpx), читано через tools/git_file.py")):
            self.save(name, f"---\ngenerated_from: {value}\n---\n# {name}\n")
        self.save("tools/git_file.py", "# tracked helper\n")
        self.commit("NOW.md", "report.md", "daily.md", "tmp.md", "db.md", "sheet.md", "sql.md", "git.md", "tools")
        result = self.run_tool("kb_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("ПРОИЗВОДНЫЙ ФАЙЛ БЕЗ ПРОВЕРЯЕМОГО ИСТОЧНИКА — 3:", result.stdout)
        for name in ("report.md", "daily.md", "tmp.md"):
            self.assertIn(f"{name} → generated_from", result.stdout)
        for name in ("db.md", "sheet.md", "sql.md", "git.md"):
            self.assertNotIn(f"{name} → generated_from", result.stdout)

    def test_project_path_outside_git_is_a_finding_and_tracked_path_is_not(self):
        self.init_git()
        self.save("NOW.md", "# Current\n")
        self.save("tools/out/run.txt", "raw output\n")
        self.save("tools/keep/run.txt", "kept output\n")
        self.save("a.md", "---\ngenerated_from: tools/out/run.txt + tools/keep/run.txt\n---\n# A\n")
        self.save("b.md", "---\ngenerated_from: tools/keep/run.txt\n---\n# B\n")
        self.commit("NOW.md", "a.md", "b.md", "tools/keep")
        result = self.run_tool("kb_check.py")
        self.assertIn("ПРОИЗВОДНЫЙ ФАЙЛ БЕЗ ПРОВЕРЯЕМОГО ИСТОЧНИКА — 1:", result.stdout)
        self.assertIn("a.md → generated_from", result.stdout)
        self.assertIn("не в Git", result.stdout)
        self.assertNotIn("b.md → generated_from", result.stdout)

    def test_json_paths_generated_views_and_declared_outputs(self):
        """Medical project 18.09.2026: a profile JSON addresses notes relative to people/;
        rendered views carry generated_from; exports for clinicians are outputs."""
        self.init_git()
        self.save("CLAUDE.md", "# Project\nвход: NOW.md\nкорень знания: people\nвне знания: people/*/exports/*\n")
        self.save("NOW.md", "# Current\n")
        self.save("people/ann/HEALTH_PROFILE.json", {"documents": [
            {"title": "MRI", "note": "ann/notes/2021-12-23_mri.md"},
            {"title": "Labs", "note": "people/ann/notes/2022-01-26_labs.md"}]})
        self.save("people/ann/notes/2021-12-23_mri.md", "# MRI\n")
        self.save("people/ann/notes/2022-01-26_labs.md", "# Labs\n")
        self.save("people/ann/notes/2023-05-05_orphan.md", "# Not registered anywhere\n")
        self.save("people/ann/HEALTH_HOME.md", "<!-- generated_from: HEALTH_PROFILE.json -->\n# Home\n")
        self.save("people/ann/START_HERE.md", "---\ngenerated: true\ngenerated_from: profile\n---\n# Hi\n")
        self.save("people/ann/exports/DOCTOR_PAGE_en.md", "# Clinical summary\n")
        self.save("people/ann/SOURCES.md", "# hand-written list, no road\n")
        self.index([{"id": "project-current", "description": "current", "load_when": ["orientation"],
                     "aliases": ["now"], "paths": ["NOW.md"]},
                    {"id": "person-ann", "description": "Ann", "load_when": ["question about Ann"],
                     "aliases": ["Ann"], "paths": ["people/ann/HEALTH_HOME.md", "people/ann/HEALTH_PROFILE.json"]}],
                   current="project-current")
        self.commit("CLAUDE.md", "NOW.md", "people", "KNOWLEDGE_INDEX.json")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["generated_views_excluded"], 2)
        self.assertEqual(report["excluded_by_declaration"], 1)
        self.assertEqual(report["declared_exclusions"], ["people/*/exports/*"])
        self.assertEqual(report["files"], 4, "two notes reached via JSON, one orphan note, one hand list")
        self.assertEqual(report["unreachable"], ["people/ann/SOURCES.md", "people/ann/notes/2023-05-05_orphan.md"])
        self.assertEqual(report["status"], "FINDING")
        check = self.run_tool("kb_check.py")
        self.assertIn("ЗНАНИЕ БЕЗ ДОРОГИ ОТ ИНДЕКСА — 2 из 4", check.stdout)


class SignalPrecision2509Tests(unittest.TestCase):
    """accounting project 25.09.2026: directory links, closure items, stale locks, cost CLI."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit = RedesignTests.commit
    index = RedesignTests.index

    def test_directory_link_reaches_its_readme_but_not_an_empty_directory(self):
        self.init_git()
        self.save("NOW.md", "# Current\n")
        self.save("knowledge/README.md", "# Areas\n`tax/` — declarations; [bank](bank/); `empty/`\n")
        self.save("knowledge/tax/README.md", "# Tax\n")
        self.save("knowledge/bank/README.md", "# Bank\n")
        self.save("knowledge/empty/note.md", "# No README beside me\n")
        self.index([{"id": "project-current", "description": "current", "load_when": ["orientation"],
                     "aliases": ["now"], "paths": ["NOW.md"]},
                    {"id": "areas", "description": "areas", "load_when": ["area question"],
                     "aliases": ["areas"], "paths": ["knowledge/README.md"]}], current="project-current")
        self.commit("NOW.md", "knowledge", "KNOWLEDGE_INDEX.json")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["unreachable"], ["knowledge/empty/note.md"])
        self.assertEqual(report["reachable"], 3)

    def test_bold_and_separate_closure_items_close_the_entry_above(self):
        for value in ("- **✔ Закрыто 2026-09-25 · тема:** внесено в `a.md`",
                      "- __✔ закрыто 2026-09-25__", "- *✔ closed*"):
            with self.subTest(value=value):
                self.assertEqual(kb_due.correction_status(value), "closed")
        self.assertEqual(kb_due.correction_status("- **пример:** ✔ закрыто"), "unknown")
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-25\n\n## ГДЕ МЫ\ntext\n")
        corr = "# Правки\n\n"
        for i in range(1, 5):
            corr += f"- 2026-09-0{i} · `NOW.md` — запись {i}\n"
            if i <= 3:
                corr += f"- **✔ Закрыто 2026-09-2{i} · запись {i}:** внесено в `NOW.md`\n"
        corr += "\n## Другое\n\n- ✔ закрыто 2026-09-24 без записи\n"
        self.save("CORRECTIONS.md", corr)
        out = self.run_tool("kb_due.py").stdout
        self.assertNotIn("записей, отметку о разборе", out, "3 of 4 closed is above the threshold")
        self.assertIn("пунктов «✔ …» без записи над ними — 1", out)
        self.assertIn("неразобранных записей про сам вход: 1", out)

    def test_stale_git_lock_is_named_and_fresh_lock_is_not(self):
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-25\n")
        self.commit("CLAUDE.md", "NOW.md")
        fresh = self.root / ".git" / "HEAD.lock"
        fresh.write_text("")
        self.assertNotIn("lock-файлы", self.run_tool("kb_due.py").stdout)
        stale = self.root / ".git" / "index.lock"
        stale.write_text("")
        old = time.time() - 3600
        os.utime(stale, (old, old))
        out = self.run_tool("kb_due.py").stdout
        self.assertIn("lock-файлы старше 10 минут: index.lock", out)
        self.assertNotIn("HEAD.lock", out)

    def test_cost_accepts_a_project_path_and_says_it_is_ignored(self):
        result = subprocess.run([sys.executable, str(HERE / "kb_cost.py"), "--check", str(self.root)],
                                capture_output=True, text=True, timeout=60)
        self.assertNotIn("unrecognized arguments", result.stderr)
        self.assertIn("ignored", result.stderr)
        self.assertIn("entry:", result.stdout)


class WorktreeSignals2609Tests(unittest.TestCase):
    """Odoo product 26.09.2026: linked worktree and role suffix false alarms."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit = RedesignTests.commit

    def test_sibling_report_inbox_resolves_from_the_main_checkout_of_a_worktree(self):
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nинбокс отчётов: ../lab/inbox\n")
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.commit("CLAUDE.md", "NOW.md")
        (self.base / "lab" / "inbox").mkdir(parents=True)
        worktree = self.base / "elsewhere" / "wt"
        worktree.parent.mkdir()
        self.git("worktree", "add", "-q", "-b", "audit", str(worktree))
        result = subprocess.run([sys.executable, str(HERE / "kb_check.py"), str(worktree)],
                                capture_output=True, text=True, timeout=30)
        self.assertNotIn("ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН", result.stdout)
        self.assertIn("от основного checkout", result.stdout)
        shutil.rmtree(self.base / "lab")
        missing = subprocess.run([sys.executable, str(HERE / "kb_check.py"), str(worktree)],
                                 capture_output=True, text=True, timeout=30)
        self.assertIn("ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН", missing.stdout)

    def test_role_suffix_after_slash_keeps_the_project_as_recipient(self):
        self.save("CLAUDE.md", "project_aliases: shop, shop-agent\n")
        names = kb_check.imena_proekta(str(self.root))
        self.assertTrue(kb_check.nash("shop / next Claude supervisor", names))
        self.assertTrue(kb_check.nash("Shop-Agent / receiving supervisor", names))
        for value in ("shop-sl / supervisor", "shop/sub", "other / shop"):
            self.assertFalse(kb_check.nash(value, names), value)


class KnowledgeDebts2609Tests(unittest.TestCase):
    """UAD, the Odoo product and the project sweep of 26.09.2026: work that never reached the base."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    index = RedesignTests.index
    TODAY = __import__("datetime").date(2026, 9, 26)

    def commit_at(self, day, *paths, root=None):
        env = dict(os.environ, GIT_AUTHOR_DATE=f"{day}T12:00:00", GIT_COMMITTER_DATE=f"{day}T12:00:00")
        self.git("add", "--", *paths, root=root)
        subprocess.run(["git", "-C", str(root or self.root), "commit", "-qm", f"at {day}"],
                       check=True, capture_output=True, env=env)

    def debts(self):
        import kb_debts
        return kb_debts.debts(str(self.root), today=self.TODAY)

    def envelope(self, name, mid, created, sender="specialist"):
        self.save(f"_inbox/{name}.md", f"---\ntype: agent-message\nmessage_id: {mid}\n"
                  f"created_at: {created}T10:00:00Z\nfrom_project: {sender}\nto_project: project\n"
                  f"delivery_state: delivered\n---\nFact: bans come after 24h of zero.\n")

    def test_inbound_without_trace_is_a_debt_until_cited_or_dispositioned(self):
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.envelope("a", "flow:msg-0001", "2026-09-19")
        self.envelope("b", "flow:msg-0002", "2026-09-20")
        self.envelope("c", "flow:msg-0003", "2026-09-25")
        self.commit_at("2026-09-25", "CLAUDE.md", "NOW.md", "_inbox")
        inbound = self.debts()["inbound"]
        self.assertEqual(inbound["status"], "DEBT")
        self.assertEqual([e["message_id"] for e in inbound["open"]],
                         ["flow:msg-0001", "flow:msg-0002"], "within grace is not yet a debt")
        self.save("knowledge/flow.md", "Ban mechanics (source: flow:msg-0001).\n")
        self.save("_inbox/INDEX.md", "- flow:msg-0002 — без дельты: уже есть в knowledge/flow.md\n")
        self.commit_at("2026-09-26", "knowledge", "_inbox/INDEX.md")
        inbound = self.debts()["inbound"]
        self.assertEqual(inbound["status"], "PASS")
        self.assertEqual(inbound["traced"], 2)

    def code_fixture(self):
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-01\n")
        for mod in ("shop_pos", "shop_care"):
            self.save(f"addons/{mod}/__manifest__.py", "{'name': '%s'}\n" % mod)
            self.save(f"addons/{mod}/models.py", "x = 1\n")
        self.save("CHANGELOG.md", "## shop_care\n- touched shop_care and shop_pos\n")
        self.save("kb/system.md", "# System\nModules: `shop_pos`, `shop_care`.\n")
        self.commit_at("2026-09-01", "CLAUDE.md", "NOW.md", "addons", "CHANGELOG.md", "kb")

    def test_code_modules_need_a_description_not_a_mention_or_a_journal(self):
        self.code_fixture()
        code = self.debts()["code"]
        self.assertEqual(code["units"], 2)
        self.assertEqual(sorted(u["unit"] for u in code["missing"]),
                         ["addons/shop_care", "addons/shop_pos"],
                         "a list line and a changelog heading are not descriptions")
        self.save("kb/system.md", "# System\n\n## shop_pos — till and receipts\nHow it works.\n")
        self.commit_at("2026-09-02", "kb/system.md")
        code = self.debts()["code"]
        self.assertEqual([u["unit"] for u in code["missing"]], ["addons/shop_care"])
        self.assertEqual(code["described"], 1)

    def test_description_lagging_behind_its_module_is_a_debt(self):
        self.code_fixture()
        self.save("addons/shop_pos/README.md", "# shop_pos\nPurpose and flows.\n")
        self.save("addons/shop_care/README.md", "# shop_care\nPurpose.\n")
        self.commit_at("2026-09-02", "addons")
        for i in range(10):
            self.save("addons/shop_pos/models.py", f"x = {i + 2}\n")
            self.commit_at(f"2026-09-{i + 10}", "addons/shop_pos/models.py")
        code = self.debts()["code"]
        self.assertEqual([u["unit"] for u in code["lagging"]], ["addons/shop_pos"])
        self.assertEqual(code["lagging"][0]["lag_commits"], 10)
        self.assertEqual(code["missing"], [])
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nкод без описания допустим: addons/shop_pos\n")
        self.assertEqual(self.debts()["code"]["excused"], ["addons/shop_pos"])

    def test_only_product_code_is_a_module(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-01\n")
        files = {"knowledge/mirror/a.py": "", "knowledge/mirror/b.py": "", "knowledge/mirror/c.py": "",
                 "skills/role/x.py": "", "skills/role/y.py": "", "skills/role/z.py": "",
                 "_reports/site/package.json": "{}", "_reports/site/a.js": "",
                 "tests/t1.py": "", "tests/t2.py": "", "tests/t3.py": "",
                 "nested/CLAUDE.md": "# nested\n", "nested/n1.py": "", "nested/n2.py": "", "nested/n3.py": "",
                 "vendor/lib/package.json": "{}", "vendor/lib/v.js": "",
                 "cloud_mcp/package.json": "{}", "cloud_mcp/index.js": "",
                 "tools/a.py": "", "tools/b.py": "", "tools/c.py": ""}
        for name, text in files.items():
            self.save(name, text)
        self.save("docs/ops.md", "# Useful tools and habits\nNothing about the code.\n")
        self.commit_at("2026-09-01", "NOW.md", *sorted({n.split("/")[0] for n in files}), "docs")
        code = self.debts()["code"]
        self.assertEqual(sorted(u["unit"] for u in code["missing"]), ["cloud_mcp", "tools"],
                         "a nested manifest must not hide top-level code; «tools» in a heading is no description")
        self.save("docs/ops.md", "# Code map\n\n## tools/ — importers\nHow they run.\n")
        self.commit_at("2026-09-02", "docs")
        self.assertEqual([u["unit"] for u in self.debts()["code"]["missing"]], ["cloud_mcp"])

    def test_same_day_uncommitted_shared_files_in_another_worktree(self):
        """UAD 26.09: a supervisor committed its zone and left shared files dirty the same day."""
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.commit_at("2026-09-26", "NOW.md")
        seo = self.base / "seo"
        self.git("worktree", "add", "-q", "-b", "seo", str(seo))
        (seo / "NOW.md").write_text("next step\n", encoding="utf-8")
        work = self.debts()["work"]
        self.assertEqual(work["worktrees"], [], "live work of a neighbour is not a debt")
        self.assertEqual([w["branch"] for w in work["fresh"]], ["seo"])
        hours_ago = time.time() - 8 * 3600
        os.utime(seo / "NOW.md", (hours_ago, hours_ago))
        work = self.debts()["work"]
        self.assertEqual([w["branch"] for w in work["worktrees"]], ["seo"])

    def test_non_code_project_has_no_code_debt(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("knowledge/a.md", "# A\n")
        self.commit_at("2026-09-26", "NOW.md", "knowledge")
        self.assertEqual(self.debts()["code"]["status"], "NOT_APPLICABLE")

    def test_stranded_work_ignores_cherry_picked_branches(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-01\n")
        self.commit_at("2026-09-01", "NOW.md")
        self.git("checkout", "-qb", "audit")
        self.save("knowledge/zone.md", "# Zone audit\n")
        self.commit_at("2026-09-10", "knowledge")
        self.git("checkout", "-qb", "ported", "main")
        self.save("knowledge/other.md", "# Other\n")
        self.commit_at("2026-09-11", "knowledge")
        self.git("checkout", "-q", "main")
        tip = self.git("rev-parse", "ported")
        subprocess.run(["git", "-C", str(self.root), "cherry-pick", tip], check=True, capture_output=True)
        work = self.debts()["work"]
        self.assertEqual([b["branch"] for b in work["branches"]], ["audit"])
        self.save("NOW.md", "Обновлено: 2026-09-02\nhalf-done\n")
        self.git("stash")
        self.assertEqual(len(self.debts()["work"]["stashes"]), 1)

    def test_dirty_linked_worktree_is_named(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-01\n")
        self.commit_at("2026-09-01", "NOW.md")
        wt = self.base / "wt"
        self.git("worktree", "add", "-q", "-b", "zone", str(wt))
        (wt / "NOW.md").write_text("Обновлено: 2026-09-02\nunfinished\n", encoding="utf-8")
        old = time.mktime((2026, 9, 10, 12, 0, 0, 0, 0, -1))
        os.utime(wt / "NOW.md", (old, old))
        work = self.debts()["work"]
        self.assertEqual([w["branch"] for w in work["worktrees"]], ["zone"])
        self.assertEqual(work["worktrees"][0]["dirty"], 1)

    def test_dates_after_the_update_line_that_already_passed(self):
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-05\n\n## ЧТО ДАЛЬШЕ\n1. Pay GBP 350 до 15.09.\n"
                  "2. Hearing 2026-10-02.\n3. Letter sent 2026-09-01.\n\n## ЧТО ОТВЕРГЛИ\n"
                  "- plan for 2026-09-20 — rejected\n")
        self.commit_at("2026-09-05", "CLAUDE.md", "NOW.md")
        current = self.debts()["current"]
        self.assertEqual(current["status"], "DEBT")
        self.assertEqual([p["date"] for p in current["passed"]], ["2026-09-15"])
        self.save("NOW.md", "Обновлено: 2026-09-26\n\n## ЧТО ДАЛЬШЕ\n1. Hearing 2026-10-02.\n")
        self.assertEqual(self.debts()["current"]["status"], "PASS")
        import kb_debts
        self.save("NOW.md", "Обновлено: 2026-12-20\n\n## ЧТО ДАЛЬШЕ\n1. Файл до 10.01.\n")
        current = kb_debts.current(str(self.root), __import__("datetime").date(2027, 1, 15))
        self.assertEqual([p["date"] for p in current["passed"]], ["2027-01-10"])

    def test_method_only_role_holding_dated_state(self):
        self.init_git()
        self.save("PROJECT_ROLES.json", {"skills": [{"name": "ga", "canonical": "skills/ga",
                                                     "quality": {"knowledge_boundary": "method-only"}}]})
        self.save("skills/ga/SKILL.md", "# GA\nMethod: compare windows.\nPurchase сломан с 11.08.2026.\n")
        self.commit_at("2026-09-01", "PROJECT_ROLES.json", "skills")
        roles = self.debts()["roles"]
        self.assertEqual(roles["status"], "DEBT")
        self.assertEqual(roles["lines"][0]["path"], "skills/ga/SKILL.md:3")

    def test_authored_synthesis_with_provenance_stays_knowledge(self):
        self.init_git()
        self.save("CLAUDE.md", "# Project\nвход: NOW.md\n")
        self.save("NOW.md", "# Current\n")
        self.save("knowledge/pays/22-map.md", "---\ngenerated_from: живая база; knowledge/pays/19.md\n"
                  "---\n# Zone map\n")
        self.save("knowledge/pays/home.md", "<!-- generated_from: PROFILE.json + metrics.db -->\n# Home\n")
        self.index([{"id": "project-current", "description": "current", "load_when": ["orientation"],
                     "aliases": ["now"], "paths": ["NOW.md"]}], current="project-current")
        self.commit_at("2026-09-01", "CLAUDE.md", "NOW.md", "knowledge", "KNOWLEDGE_INDEX.json")
        report = kb_index.coverage(self.root, self.root / "KNOWLEDGE_INDEX.json")
        self.assertEqual(report["generated_views_excluded"], 1)
        self.assertEqual(report["unreachable"], ["knowledge/pays/22-map.md"])

    def test_check_names_debts_without_changing_the_exit_code(self):
        self.code_fixture()
        result = self.run_tool("kb_check.py")
        self.assertIn("ДОЛГИ ЗНАНИЯ", result.stdout)
        self.assertIn("модулей кода без описания: 2 из 2", result.stdout)
        self.assertIn("целостность: чисто, но работа не дошла до базы", result.stdout)
        self.assertEqual(result.returncode, 0)
        due = self.run_tool("kb_due.py")
        self.assertIn("долг знания: модулей кода без описания", due.stdout)

    def test_sweep_lists_every_kb_project_once(self):
        import kb_debts
        for name in ("alpha", "beta"):
            root = self.base / "projects" / name
            root.mkdir(parents=True)
            self.init_git(root=root)
            self.save("CLAUDE.md", "kb_standard_version: 7.2.0\nвход: NOW.md\n", root=root)
            self.save("NOW.md", "Обновлено: 2026-09-20\n", root=root)
            self.commit_at("2026-09-20", "CLAUDE.md", "NOW.md", root=root)
        (self.base / "projects" / "not-kb").mkdir()
        rows = kb_debts.sweep(str(self.base / "projects"))
        self.assertEqual([r["project"] for r in rows], ["alpha", "beta"])
        self.assertEqual(rows[0]["version"], "7.2.0")


class ProjectSweepPrecision2609Tests(unittest.TestCase):
    """False alarms and blind spots found by the project sweep of 26.09.2026."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save

    def test_closure_mark_at_the_end_of_the_entry_as_the_template_prescribes(self):
        entry = ("- 2026-08-14 · знание · `NOW.md` — claimed two chats. Источник: list. "
                 "✔ закрыто 2026-08-14, внесено в `NOW.md` и `knowledge/a.md`.")
        self.assertEqual(kb_due.correction_status(entry), "closed")
        self.assertEqual(kb_due.correction_status(
            "- 2026-08-10 · знание · x. ✔ закрыто 2026-08-10, обе версии внесены в `k.md`."), "closed")
        for value in ("- 2026-08-14 · x — пример: ✔ закрыто", "- `✔ закрыто, внесено в a.md` is an example",
                      "> ✔ закрыто, внесено в a.md"):
            with self.subTest(value=value):
                self.assertEqual(kb_due.correction_status(value), "unknown")

    def test_declared_refusal_of_a_report_route_is_not_a_finding(self):
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nмаршрут отчётов: не принят\n")
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        result = self.run_tool("kb_check.py")
        self.assertNotIn("ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН", result.stdout)
        self.assertIn("неприменимо (объявлено: «не принят»)", result.stdout)
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nмаршрут отчётов: не принят\n"
                  "сервисный контур kb-architect: принят\n")
        self.assertIn("ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН", self.run_tool("kb_check.py").stdout)

    def test_link_to_a_file_with_parentheses_resolves(self):
        self.save("NOW.md", "See [scan](docs/scan (2).md) and [gone](docs/none (1).md).\n")
        self.save("docs/scan (2).md", "# Scan\n")
        out = self.run_tool("kb_check.py").stdout
        self.assertNotIn("scan (2).md", out)
        self.assertIn("docs/none (1).md", out)

    def test_receipt_field_is_the_verify_of_a_sent_letter(self):
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("letters/a.md", "---\nstatus: sent\nsent_message_id: 18f2a\n---\nLetter.\n")
        self.save("letters/b.md", "---\nstatus: sent\nsent_message_id: TBD\n---\nLetter.\n")
        out = self.run_tool("kb_check.py").stdout
        self.assertNotIn("letters/a.md", out)
        self.assertIn("letters/b.md", out)

    def test_own_megamozg_profiles_and_alias_patterns_are_the_project(self):
        self.save("CLAUDE.md", "project_aliases: uad-*\n")
        self.save("_megamozg/flow-zone/profile.json", {"id": "flow-zone"})
        names = kb_check.imena_proekta(str(self.root))
        self.assertTrue(kb_check.nash("flow-zone", names))
        self.assertTrue(kb_check.nash("uad-payments", names))
        self.assertFalse(kb_check.nash("other-uad", names))
        self.assertFalse(kb_check.nash("flow", names))

    def test_nested_project_is_not_a_second_entry(self):
        self.save("CLAUDE.md", "# Rules\n")
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("agent-config/CLAUDE.md", "# Nested project\nkb_standard_version: 7.0.0\n")
        self.save("agent-config/NOW.md", "Обновлено: 2026-09-24\n")
        entry = kb_paths.locate(str(self.root), "entry")
        self.assertEqual(entry.others, [])
        self.assertNotIn("ВХОД НАЙДЕН В НЕСКОЛЬКИХ МЕСТАХ", self.run_tool("kb_check.py").stdout)

    def test_plain_folder_instructions_do_not_hide_the_entry(self):
        self.save("kb/CLAUDE.md", "# How to edit this folder\n")
        self.save("kb/NOW.md", "Обновлено: 2026-09-26\n")
        entry = kb_paths.locate(str(self.root), "entry")
        self.assertTrue(entry.path and entry.path.endswith("kb/NOW.md"), entry.path)


class Review73Tests(unittest.TestCase):
    """Fresh-context review of the 7.3.0 candidate, 26.09.2026: every item was reproduced first."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    TODAY = KnowledgeDebts2609Tests.TODAY

    def debts(self, root=None, **kw):
        import kb_debts
        return kb_debts.debts(str(root or self.root), today=kw.pop("today", self.TODAY), **kw)

    def lagging_fixture(self, prefix="", code_name="f.py"):
        root = self.root / prefix if prefix else self.root
        self.save(f"{prefix}NOW.md", "Обновлено: 2026-09-01\n")
        self.save(f"{prefix}src/README.md", "# src\nPurpose.\n")
        self.save(f"{prefix}src/a.py", "a\n")
        self.save(f"{prefix}src/b.py", "b\n")
        self.commit_at("2026-09-01", ".")
        for i in range(12):
            self.save(f"{prefix}src/{code_name}", f"x = {i}\n")
            self.commit_at(f"2026-09-{i + 5:02d}", ".")
        return root

    def test_non_ascii_module_paths_are_counted(self):
        self.init_git()
        self.lagging_fixture(code_name="модуль.py")
        code = self.debts()["code"]
        self.assertEqual([u["lag_commits"] for u in code["lagging"]], [12])

    def test_project_inside_a_larger_repository(self):
        self.init_git()
        proj = self.lagging_fixture(prefix="proj/")
        self.assertEqual([u["lag_commits"] for u in self.debts(proj)["code"]["lagging"]], [12])

    def test_other_worktree_is_checked_inside_a_git_hook(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-01\n")
        self.commit_at("2026-09-01", "NOW.md")
        side = self.base / "side"
        self.git("worktree", "add", "-q", "-b", "side", str(side))
        (side / "NOW.md").write_text("changed\n", encoding="utf-8")
        old = time.mktime((2026, 9, 10, 12, 0, 0, 0, 0, -1))
        os.utime(side / "NOW.md", (old, old))
        # Hooks export a relative index path; inside another worktree `.git` is a file.
        env = dict(os.environ, GIT_INDEX_FILE=".git/index")
        out = subprocess.run([sys.executable, str(HERE / "kb_debts.py"), str(self.root), "--json"],
                             capture_output=True, text=True, env=env, timeout=60)
        data = json.loads(out.stdout)
        self.assertEqual([w["branch"] for w in data["work"]["worktrees"]], ["side"])

    def test_substring_of_a_file_name_is_not_a_description(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-01\n")
        for mod in ("shop", "core"):
            for f in ("a.py", "b.py", "c.py"):
                self.save(f"{mod}/{f}", "x\n")
        self.save("docs/WORKSHOP.md", "# Workshop\n")
        self.save("docs/SCORECARD.md", "# Score\n")
        self.save("docs/shop-flows.md", "# Flows\n")
        self.commit_at("2026-09-01", ".")
        code = self.debts()["code"]
        self.assertEqual([u["unit"] for u in code["missing"]], ["core"])

    def test_short_message_id_is_not_traced_by_a_number(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("_inbox/m.md", "---\ntype: agent-message\nmessage_id: 42\ncreated_at: 2026-09-01T00:00:00Z\n"
                  "from_project: other\nto_project: project\n---\nx\n")
        self.save("BUDGET.md", "Paid 1420 EUR.\n")
        self.commit_at("2026-09-01", ".")
        self.assertEqual(self.debts()["inbound"]["status"], "DEBT")

    def test_packet_from_own_megamozg_profile_is_inbound(self):
        self.init_git()
        self.save("CLAUDE.md", "project_aliases: uad, uad-*\n")
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("_megamozg/uad-flow/profile.json", {"id": "uad-flow"})
        self.save("_inbox/p.md", "---\ntype: agent-message\nmessage_id: flow-packet-001\n"
                  "created_at: 2026-09-01T00:00:00Z\nfrom_project: uad-flow\nto_project: uad\n---\nx\n")
        self.commit_at("2026-09-01", ".")
        self.assertEqual(self.debts()["inbound"]["total"], 1)
        self.assertNotIn("ИСХОДЯЩЕЕ В СОБСТВЕННОМ ИНБОКСЕ", self.run_tool("kb_check.py").stdout)

    def test_empty_or_placeholder_receipt_is_not_a_verify(self):
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("a.md", "---\nstatus: sent\nsent_message_id:\nto: bob\n---\n")
        self.save("b.md", "---\nstatus: sent\nevidence_receipt: <путь/id receipt либо none>\n---\n")
        self.save("c.md", "---\nstatus: sent\nmessage_id: m-123456\n---\n")
        out = self.run_tool("kb_check.py").stdout
        for name in ("a.md", "b.md", "c.md"):
            self.assertIn(name, out)

    def test_area_filter_outside_stale_file_does_not_crash(self):
        import kb_debts
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("STATE.md", "observed_at: 2026-08-01\n")
        self.save("src/a.py", "x\n")
        self.commit_at("2026-09-01", ".")
        d = self.debts(area="src")
        self.assertEqual(d["freshness"]["status"], "PASS")
        kb_debts.summary_lines(d)

    def test_squash_merged_remote_branch_is_not_a_debt(self):
        remote = self.base / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        self.init_git()
        self.git("remote", "add", "origin", str(remote))
        self.save("NOW.md", "Обновлено: 2026-09-01\n")
        self.commit_at("2026-09-01", "NOW.md")
        self.git("checkout", "-qb", "feat")
        self.save("knowledge/a.md", "# A\n")
        self.commit_at("2026-09-02", "knowledge")
        self.save("knowledge/b.md", "# B\n")
        self.commit_at("2026-09-03", "knowledge")
        self.git("push", "-q", "origin", "feat")
        self.git("checkout", "-q", "main")
        subprocess.run(["git", "-C", str(self.root), "merge", "-q", "--squash", "feat"], check=True,
                       capture_output=True)
        self.commit_at("2026-09-04", ".")
        self.git("branch", "-D", "feat")
        self.assertEqual(self.debts()["work"]["branches"], [])

    def test_day_first_observed_at_is_read(self):
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        self.save("knowledge/state.md", "---\nobserved_at: 01.08.2026\n---\nTariff Team.\n")
        self.commit_at("2026-09-01", ".")
        fresh = self.debts()["freshness"]
        self.assertEqual([x["observed_at"] for x in fresh["stale"]], ["2026-08-01"])

    def test_version_number_is_not_a_deadline(self):
        import kb_debts
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-05\n\n## ЧТО ДАЛЬШЕ\n1. Обновить Python до 3.11.\n")
        current = kb_debts.current(str(self.root), __import__("datetime").date(2026, 11, 10))
        self.assertEqual(current["passed"], [])

    def test_main_checkout_through_a_symlinked_temp_path(self):
        self.init_git()
        self.save("NOW.md", "x\n")
        self.commit_at("2026-09-01", "NOW.md")
        wt = self.base / "wt"
        self.git("worktree", "add", "-q", "-b", "w", str(wt))
        alias = str(wt).replace("/private/var/", "/var/", 1)
        if alias == str(wt) or not os.path.isdir(alias):
            self.skipTest("no symlinked temp prefix on this platform")
        self.assertEqual(os.path.realpath(kb_paths.canonical_checkout(alias)),
                         os.path.realpath(self.root))

    def test_sweep_accepts_flags_and_survives_a_broken_project(self):
        import kb_debts
        parent = self.base / "projects"
        good = parent / "good"
        good.mkdir(parents=True)
        self.init_git(root=good)
        self.save("CLAUDE.md", "kb_standard_version: 7.2.0\n", root=good)
        self.commit_at("2026-09-01", "CLAUDE.md", root=good)
        out = subprocess.run([sys.executable, str(HERE / "kb_debts.py"), "--sweep", "--json", str(parent)],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual([r["project"] for r in json.loads(out.stdout)], ["good"])
        with patch.object(kb_debts, "debts", side_effect=RuntimeError("boom")):
            rows = kb_debts.sweep(str(parent))
        self.assertIn("boom", rows[0]["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
