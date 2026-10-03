#!/usr/bin/env python3
"""Observed 6.x failures and 7.0 heterogeneous-project contracts, in isolation."""

import contextlib
import hashlib
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
        self.assertTrue(kb_check.nash("shop (супервизор направления Flow)", names))
        self.assertTrue(kb_check.nash("shop — сессия Claude на Mac владельца", names))
        self.assertFalse(kb_check.nash("shop(x)", names))
        self.assertFalse(kb_check.nash("other (shop)", names))
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


class UpdateClosesDebts2609Tests(unittest.TestCase):
    """Owner 26.09.2026: «why must I say more than 'update'?» — the update now carries the debts."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at

    def project(self, with_debt):
        self.init_git()
        self.save("CLAUDE.md", "# rules\nkb_standard_version: 7.2.0\n")
        self.save("NOW.md", "Обновлено: 2026-09-26\n")
        if with_debt:
            self.save("_inbox/p.md", "---\ntype: agent-message\nmessage_id: packet-000001\n"
                      "created_at: 2026-09-01T00:00:00Z\nfrom_project: specialist\nto_project: project\n"
                      "---\nfact\n")
        self.commit_at("2026-09-02", ".")

    def run_apply(self, action):
        import kb_update
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kb_update.debts_of_project(str(HERE.parent), str(self.root), action)
        return out.getvalue()

    def test_owner_update_command_leads_to_the_debts(self):
        self.project(with_debt=True)
        out = self.run_apply(True)
        self.assertIn("входящие без следа внесения: 1 из 1", out)
        self.assertIn("SESSION_ACTION=CLOSE_KNOWLEDGE_DEBTS", out)
        self.assertIn("долги своей области", out)
        self.assertIn("SESSION_STATE=KNOWLEDGE_DEBTS_OPEN", self.run_apply(False))

    def test_no_debts_is_said_not_silent(self):
        self.project(with_debt=False)
        out = self.run_apply(True)
        self.assertIn("ДОЛГИ ЗНАНИЯ: нет в проверенном охвате.", out)
        self.assertNotIn("CLOSE_KNOWLEDGE_DEBTS", out)


class AgentMemory2909Tests(unittest.TestCase):
    """tg-archive 29.09.2026: five days of host changes went to the agent's own memory."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at

    def test_project_fact_without_a_canon_address_is_a_debt(self):
        import kb_debts
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-29\n")
        self.save("docs/operator.md", "# Operator\n")
        self.commit_at("2026-09-29", ".")
        projects = self.base / "claude-projects"
        mem = projects / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(self.root)) / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- index\n", encoding="utf-8")
        (mem / "slice-limits.md").write_text("---\nname: slice-limits\nmetadata:\n  type: project\n---\n"
                                             "MemoryMax 6G on the host.\n", encoding="utf-8")
        (mem / "pointer.md").write_text("---\nname: pointer\ntype: project\n---\n"
                                        "See docs/operator.md for the unit layout.\n", encoding="utf-8")
        (mem / "style.md").write_text("---\nname: style\ntype: feedback\n---\nShort answers.\n",
                                      encoding="utf-8")
        with patch.dict(os.environ, {"KB_AGENT_MEMORY_ROOT": str(projects)}):
            got = kb_debts.memory(str(self.root), kb_debts.tracked(str(self.root)))
        self.assertEqual(got["status"], "DEBT")
        self.assertEqual(got["facts"], 2)
        self.assertEqual([m["memory"] for m in got["loose"]], ["slice-limits.md"])

    def test_no_memory_is_not_applicable(self):
        import kb_debts
        self.init_git()
        with patch.dict(os.environ, {"KB_AGENT_MEMORY_ROOT": str(self.base / "none")}):
            self.assertEqual(kb_debts.memory(str(self.root), [])["status"], "NOT_APPLICABLE")


class ReportsAndEntry2909Tests(unittest.TestCase):
    """Prime 20–29.09.2026: reports stranded in a lookalike folder, stale checkout, false
    alarms at entry, a half-read entry at handoff, decisions left in a plan file."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at

    def fake_gh(self, private=True):
        bin_dir = self.base / "bin"
        bin_dir.mkdir(exist_ok=True)
        log = self.base / "gh.log"
        script = bin_dir / "gh"
        script.write_text("#!/bin/sh\n"
                          f"echo \"$@\" >> '{log}'\n"
                          'case "$1 $2" in\n'
                          f'  "repo view") {"echo PRIVATE" if private else "echo nope >&2; exit 1"} ;;\n'
                          '  "issue list") echo "" ;;\n'
                          '  "issue create") echo https://github.com/sugestr/kb-architect-lab/issues/7 ;;\n'
                          "esac\n", encoding="utf-8")
        script.chmod(0o755)
        return dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"), log

    def lookalike_project(self):
        projects = self.base / "projects"
        project = projects / "shop"
        (projects / "kb-architect" / "inbox").mkdir(parents=True)
        project.mkdir(parents=True)
        (project / "CLAUDE.md").write_text("# rules\nмаршрут отчётов: local-inbox\n"
                                           "инбокс отчётов: ../kb-architect/inbox\n", encoding="utf-8")
        (project / "report.md").write_text("# Defect\n\nрежим подробности: детальный\n", encoding="utf-8")
        return project, projects / "kb-architect" / "inbox"

    def report(self, project, env, *extra):
        return subprocess.run([sys.executable, str(HERE / "kb_report.py"), "--project", str(project),
                               "--report", str(project / "report.md"), *extra],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_lookalike_lab_folder_is_not_a_delivery_target(self):
        project, lookalike = self.lookalike_project()
        env, log = self.fake_gh()
        preview = self.report(project, env)
        self.assertIn("PREPARED lab-issue", preview.stdout)
        done = self.report(project, env, "--do")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("DELIVERED lab-issue: https://github.com/sugestr/kb-architect-lab/issues/7",
                      done.stdout)
        self.assertEqual(list(lookalike.iterdir()), [], "nothing is written into the lookalike")
        self.assertIn("issue create --repo sugestr/kb-architect-lab", log.read_text())
        self.assertNotIn("sugestr/kb-architect ", log.read_text(), "never the public repository")

    def test_without_private_lab_access_the_report_stays_at_the_source(self):
        project, lookalike = self.lookalike_project()
        env, _ = self.fake_gh(private=False)
        done = self.report(project, env, "--do")
        self.assertEqual(done.returncode, 2)
        self.assertIn("BLOCKED_LOCAL", done.stdout)
        self.assertNotIn("DELIVERED", done.stdout)
        self.assertEqual(list(lookalike.iterdir()), [])

    def test_check_names_the_issue_route_instead_of_trusting_the_lookalike(self):
        project, _ = self.lookalike_project()
        out = subprocess.run([sys.executable, str(HERE / "kb_check.py"), str(project)],
                             capture_output=True, text=True, timeout=60).stdout
        self.assertIn("не checkout лаборатории", out)
        self.assertNotIn("ИНБОКС ОТЧЁТОВ НЕ ПРОВЕРЕН", out)

    def test_checkout_behind_origin_is_named_with_the_fetch_moment(self):
        remote = self.base / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-29\n")
        self.commit_at("2026-09-29", ".")
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "-u", "origin", "main")
        other = self.base / "other"
        subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
        self.init_git(root=other)
        (other / "x.md").write_text("x\n", encoding="utf-8")
        self.commit_at("2026-09-29", "x.md", root=other)
        subprocess.run(["git", "-C", str(other), "push", "-q"], check=True)
        self.git("fetch", "-q")
        out = self.run_tool("kb_due.py").stdout
        self.assertIn("checkout отстаёт от origin на 1 коммитов", out)
        self.assertNotIn("всё закоммичено и запушено", out)

    def test_waiting_table_header_and_yearless_dates(self):
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-29\n\n## ЧЕГО ЖДЁМ\n| Вопрос | Кто / когда |\n"
                  "|---|---|\n| Ответ банка | банк, с 07.07 |\n| Подпись | нотариус, с 2026-09-20 |\n")
        out = self.run_tool("kb_due.py").stdout
        self.assertNotIn("ожиданий без даты начала", out)
        self.assertRegex(out, r"ожиданий: 2, самое давнее ждём с 20\d\d-07-07")

    def test_handoff_to_the_next_session_of_the_same_project_is_inbound(self):
        import kb_debts
        self.init_git()
        self.save("CLAUDE.md", "project_aliases: shop\n")
        self.save("NOW.md", "Обновлено: 2026-09-29\n")
        self.save("_inbox/handoff.md", "---\ntype: agent-message\nmessage_id: handoff-000001\n"
                  "created_at: 2026-09-20T00:00:00Z\nfrom_project: shop (супервизор, Claude)\n"
                  "to_project: shop\ndelivery_state: delivered\n---\nnext steps\n")
        self.commit_at("2026-09-20", ".")
        self.assertNotIn("ИСХОДЯЩЕЕ В СОБСТВЕННОМ ИНБОКСЕ", self.run_tool("kb_check.py").stdout)
        inbound = kb_debts.debts(str(self.root), today=__import__("datetime").date(2026, 9, 29))["inbound"]
        self.assertEqual(inbound["total"], 1)

    def test_plan_with_owner_decisions_outside_git_is_a_debt(self):
        import kb_debts
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-29\n")
        self.save("kb/05_catalog.md", "# Catalog\n")
        self.commit_at("2026-09-29", ".")
        plans_dir = self.base / "plans"
        plans_dir.mkdir()
        plan = plans_dir / "cuddly-plan.md"
        plan.write_text(f"# Consumables\nWork in {self.root}. Owner: four kinds, weekly order.\n",
                        encoding="utf-8")
        other = plans_dir / "other.md"
        other.write_text("# Unrelated project plan\n", encoding="utf-8")
        today = __import__("datetime").date.today()
        with patch.dict(os.environ, {"KB_AGENT_PLANS_ROOT": str(plans_dir)}):
            got = kb_debts.plans(str(self.root), kb_debts.tracked(str(self.root)), today)
            self.assertEqual([x["plan"] for x in got["loose"]], ["cuddly-plan.md"])
            plan.write_text(plan.read_text() + "\nВнесено в kb/05_catalog.md §1.7.\n", encoding="utf-8")
            self.assertEqual(kb_debts.plans(str(self.root), [], today)["status"], "PASS")

    def entry_fixture(self):
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-29\n")
        self.save("kb/99_invariants.md", "# Invariants\nNever overwrite a card code.\n")
        self.save("kb/05_catalog.md", "# Catalog\nNew consumables: series C00001.\n")
        self.save("skills/dev/SKILL.md", "# Dev method\n")
        self.save("KNOWLEDGE_INDEX.json", {"schema": 1, "current": "now", "routes": [
            {"id": "now", "load_when": ["any task start"], "paths": ["NOW.md"]},
            {"id": "invariants", "load_when": ["before any write to Odoo"], "paths": ["kb/99_invariants.md"]},
            {"id": "catalog", "load_when": ["creating product cards"], "paths": ["kb/05_catalog.md"]}]})
        self.save("PROJECT_ROLES.json", {"roles": [{"id": "dev", "skill": "dev", "load_when": ["any write"],
                                                    "knowledge_routes": ["invariants", "catalog"]}],
                                         "skills": [{"name": "dev", "canonical": "skills/dev"}]})
        self.commit_at("2026-09-29", ".")

    def test_full_entry_is_one_command_with_a_receipt(self):
        self.entry_fixture()
        bundle = self.base / "ENTRY.md"
        out = self.run_tool("kb_entry.py", "--role", "dev", "--out", bundle)
        text = bundle.read_text(encoding="utf-8")
        self.assertIn("Never overwrite a card code.", text)
        self.assertIn("# Dev method", text)
        self.assertNotIn("series C00001", text, "task routes are addresses, not entry reads")
        self.assertIn("- catalog: creating product cards", out.stdout)
        self.assertIn("ENTRY_RECEIPT: kb-architect", out.stdout)
        self.assertIn("SESSION_ACTION=READ_ENTRY_BUNDLE_WHOLE", out.stdout)
        with_route = self.run_tool("kb_entry.py", "--role", "dev", "--route", "catalog", "--out", bundle)
        self.assertIn("series C00001", bundle.read_text(encoding="utf-8"))
        self.assertEqual(with_route.returncode, 0, with_route.stdout)
        unknown = self.run_tool("kb_entry.py", "--role", "nobody", "--out", bundle)
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("роль «nobody» не найдена", unknown.stdout)


class Review733Tests(unittest.TestCase):
    """Fresh-context review of the 7.3.3 candidate, 29.09.2026."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    lookalike_project = ReportsAndEntry2909Tests.lookalike_project
    report = ReportsAndEntry2909Tests.report
    entry_fixture = ReportsAndEntry2909Tests.entry_fixture

    def test_an_issue_that_only_links_the_report_is_not_its_delivery(self):
        project, _ = self.lookalike_project()
        report_id = "sha256:" + hashlib.sha256((project / "report.md").read_bytes()).hexdigest()
        child = json.dumps([{"url": "https://x/issues/2", "title":
                             f"[kb-report] Child · shop · sha256:{'b' * 16} · amends {report_id[:23]}"}])
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        (self.base / "list.json").write_text(child, encoding="utf-8")
        gh = bin_dir / "gh"
        gh.write_text("#!/bin/sh\n"
                      'case "$1 $2" in\n'
                      '  "repo view") echo PRIVATE ;;\n'
                      f'  "issue list") cat \'{self.base / "list.json"}\' ;;\n'
                      '  "issue create") echo https://x/issues/3 ;;\n'
                      "esac\n", encoding="utf-8")
        gh.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        done = self.report(project, env, "--do")
        self.assertIn("DELIVERED lab-issue: https://x/issues/3", done.stdout)
        self.assertNotIn("already present", done.stdout)

    def waits(self, rows, today):
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-09-29\n\n## ЧЕГО ЖДЁМ\n| Что | Кто |\n|---|---|\n" + rows)
        with patch.object(kb_due.datetime, "date", wraps=__import__("datetime").date) as fake:
            fake.today.return_value = today
            out = io.StringIO()
            with patch.object(sys, "argv", ["kb_due.py", str(self.root)]), \
                    contextlib.redirect_stdout(out):
                kb_due.main()
        return out.getvalue()

    def test_waits_survive_leap_days_versions_times_and_empty_rows(self):
        date = __import__("datetime").date
        out = self.waits("| Ответ | банк, с 29.02 |\n", date(2027, 1, 15))
        self.assertIn("ожиданий: 1", out)
        out = self.waits("| Ответ по релизу 7.3 | звонок в 12.05 |\n", date(2026, 9, 29))
        self.assertIn("ожиданий без даты начала: 1", out)
        out = self.waits("| A | с 2026-08-01 |\n|  |  |\n| B | с 2026-09-01 |\n", date(2026, 9, 29))
        self.assertIn("ожиданий: 2, самое давнее ждём с 2026-08-01", out)

    def test_entry_reads_a_section_caps_big_files_and_never_writes_the_tree(self):
        self.entry_fixture()
        self.save("kb/big.md", "# Big\n\n## Invariants\nOnly this.\n\n## Other\n" + "x" * 500_000 + "\n")
        index = json.loads((self.root / "KNOWLEDGE_INDEX.json").read_text())
        index["routes"].append({"id": "sec", "load_when": ["always"],
                                "targets": [{"kind": "section", "path": "kb/big.md", "section": "Invariants"}]})
        index["routes"].append({"id": "huge", "load_when": ["huge data"], "paths": ["kb/big.md"]})
        self.save("KNOWLEDGE_INDEX.json", index)
        bundle = self.base / "E.md"
        out = self.run_tool("kb_entry.py", "--route", "huge", "--out", bundle)
        text = bundle.read_text(encoding="utf-8")
        self.assertIn("Only this.", text)
        self.assertNotIn("x" * 1000, text)
        self.assertIn("больше предела", out.stdout)
        blocked = self.run_tool("kb_entry.py", "--out", self.root / "ENTRY.md")
        self.assertEqual(blocked.returncode, 2)
        self.assertFalse((self.root / "ENTRY.md").exists())

    def test_entry_falls_back_when_the_git_dir_is_read_only(self):
        self.entry_fixture()
        git_dir = self.root / ".git"
        git_dir.chmod(0o555)
        try:
            out = self.run_tool("kb_entry.py")
        finally:
            git_dir.chmod(0o755)
        self.assertIn("ENTRY_BUNDLE=", out.stdout, out.stderr)
        self.assertNotIn("Traceback", out.stderr)

    def test_sibling_project_plan_is_not_this_projects_debt(self):
        import kb_debts
        self.init_git()
        self.save("NOW.md", "Обновлено: 2026-09-29\n")
        self.commit_at("2026-09-29", ".")
        plans_dir = self.base / "plans"
        plans_dir.mkdir()
        (plans_dir / "p.md").write_text(f"# Plan\nWork in {self.root}-odoo/addons.\n", encoding="utf-8")
        with patch.dict(os.environ, {"KB_AGENT_PLANS_ROOT": str(plans_dir)}):
            got = kb_debts.plans(str(self.root), [], __import__("datetime").date.today())
        self.assertEqual(got["loose"], [])


class OwnerGateClaudeSession2909Tests(unittest.TestCase):
    """Owner 29.09.2026: the desktop Code tab needed a manual root export for every
    maintenance commit. The gate now reads Claude Code's own session record, and a
    forged or foreign record never passes (queued since 18.09 «with the owner present»)."""

    def setUp(self):
        import kb_owner_gate
        self.gate = kb_owner_gate
        self.temp = tempfile.TemporaryDirectory(prefix="kb-gate-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.owner, self.consumer = base / "owner", base / "consumer"
        for root, remote in ((self.owner, "git@github.com:sugestr/kb-architect-lab.git"),
                             (self.consumer, "https://github.com/example/consumer.git")):
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin", remote], check=True)
        self.projects = base / "claude-projects"

    def record(self, sid, rows, folder="-slug"):
        path = self.projects / folder / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def evaluate(self, sid):
        env = {"CLAUDE_CODE_SESSION_ID": sid} if sid else {}
        return self.gate.evaluate(self.owner, True, env, Path(self.temp.name) / "none",
                                  claude_projects_root=self.projects)

    def test_session_started_in_the_lab_passes(self):
        self.record("s-owner", [{"type": "queue-operation", "sessionId": "s-owner"},
                                {"type": "user", "sessionId": "s-owner", "cwd": str(self.owner)}])
        result = self.evaluate("s-owner")
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["evidence"], "claude-session:s-owner")

    def test_session_started_elsewhere_is_blocked_even_after_cd_into_the_lab(self):
        self.record("s-uad", [{"type": "user", "sessionId": "s-uad", "cwd": str(self.consumer)},
                              {"type": "user", "sessionId": "s-uad", "cwd": str(self.owner)}])
        self.assertEqual(self.evaluate("s-uad")["state"], "BLOCKED_WRONG_EXECUTOR")

    def test_forged_or_missing_record_stays_unknown(self):
        self.record("s-forged", [{"type": "user", "sessionId": "someone-else", "cwd": str(self.owner)}])
        forged = self.evaluate("s-forged")
        self.assertEqual(forged["state"], "OWNER_CONTEXT_UNKNOWN")
        self.assertEqual(forged["evidence"], "claude-session-record-missing:s-forged")
        self.assertEqual(self.evaluate("s-none")["state"], "OWNER_CONTEXT_UNKNOWN")
        self.assertEqual(self.evaluate("../escape")["state"], "OWNER_CONTEXT_UNKNOWN")
        self.assertEqual(self.evaluate(None)["state"], "OWNER_CONTEXT_UNKNOWN")

    def test_codex_and_explicit_root_keep_priority(self):
        self.record("s-owner", [{"type": "user", "sessionId": "s-owner", "cwd": str(self.owner)}])
        env = {"CLAUDE_CODE_SESSION_ID": "s-owner", "CLAUDE_PROJECT_DIR": str(self.consumer)}
        result = self.gate.evaluate(self.owner, True, env, Path(self.temp.name) / "none",
                                    claude_projects_root=self.projects)
        self.assertEqual(result["state"], "BLOCKED_WRONG_EXECUTOR")


class ExecutableEntry0110Tests(unittest.TestCase):
    """01.10.2026: a new chat of the Odoo product worked six hours without its role; the entry
    steps written as prose were skipped, the step with a command ran. 7.4.0 makes the entry run
    itself (session hook), locks writes until the entry file is read and confirmed by its part
    marks, and stays silent outside KB projects."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at

    def project(self, big_now=False, seed_due=True):
        ReportsAndEntry2909Tests.entry_fixture(self)
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 7.2.0\n")
        if seed_due:   # дневной кэш kb_due: старт не платит его в каждом тесте
            import datetime as _dt
            import kb_start
            cache = self.base / "state" / "due" / (
                f"{kb_start.root_key(self.root)}-{_dt.date.today().isoformat()}.txt")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text("  • fixture due line", encoding="utf-8")
        if big_now:
            self.save("NOW.md", "Обновлено: 2026-09-29\n" + "Строка состояния проекта.\n" * 900
                      + "ПОСЛЕДНЯЯ СТРОКА NOW\n")
        roles = json.loads((self.root / "PROJECT_ROLES.json").read_text())
        roles["roles"].append({"id": "ops", "skill": "dev", "load_when": ["shop operations"]})
        roles["entry_role"] = "dev"
        self.save("PROJECT_ROLES.json", roles)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
        env["KB_ENTRY_STATE"] = str(self.base / "state")
        env["KB_ENTRY_UPDATE"] = "off"     # тест не ставит скилл в настоящий HOME
        env.update(extra)
        return env

    def hook(self, event, agent="claude", cwd=None, **env):
        event = dict({"session_id": "s1", "cwd": str(cwd or self.root)}, **event)
        out = subprocess.run([sys.executable, str(HERE / "kb_start.py"), "hook", "--agent", agent],
                             input=json.dumps(event), capture_output=True, text=True, timeout=90,
                             env=self.env(**env))
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def start(self, source="startup", **kw):
        return self.hook({"hook_event_name": "SessionStart", "source": source}, **kw)

    def tool(self, name, **tool_input):
        got = self.hook({"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input})
        return (got or {}).get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def marks(self, bundle):
        return re.findall(r"\[kb-entry · часть \d+/\d+ · метка ([0-9a-f]{4})\]",
                          Path(bundle).read_text(encoding="utf-8"))

    def confirm(self, token, *extra):
        return subprocess.run([sys.executable, str(HERE / "kb_start.py"), "confirm", str(self.root),
                               "--token", token, *extra], capture_output=True, text=True,
                              timeout=60, env=self.env())

    def bundle_of(self, context):
        return re.search(r"(/\S+ENTRY-\S+\.md)", context).group(1)

    def test_outside_a_kb_project_the_hook_is_silent(self):
        plain = self.base / "plain"
        plain.mkdir()
        (plain / "CLAUDE.md").write_text("# Not a KB project\n", encoding="utf-8")
        self.assertIsNone(self.start(cwd=plain))
        got = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {}},
                        cwd=plain)
        self.assertIsNone(got)
        self.project()
        profile = self.root / "_bot" / "profile"
        profile.mkdir(parents=True)
        (profile / "CLAUDE.md").write_text("# Bot profile\n", encoding="utf-8")
        self.assertIsNone(self.start(cwd=profile), "the nearest non-KB rules file is a boundary")
        deep = self.root / "kb" / "sub"
        deep.mkdir(parents=True)
        self.assertIsNotNone(self.start(cwd=deep, session_id="deep"))

    def test_start_puts_a_short_entry_in_context_and_locks_writes(self):
        self.project(big_now=True, seed_due=False)
        got = self.start()
        context = got["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ПОРА (kb_due, раз в день):", context)
        self.assertLessEqual(len(context), 10_000, "Claude Code keeps only 10 000 characters")
        self.assertIn("ENTRY_RECEIPT: kb-architect", context)
        self.assertIn("роль dev", context)
        self.assertIn("- ops: shop operations", context)
        self.assertNotIn("ПОСЛЕДНЯЯ СТРОКА NOW", context, "a big entry is a file, not context")
        self.assertIn("ПОСЛЕДНЯЯ СТРОКА NOW", Path(self.bundle_of(context)).read_text())
        self.assertIn("правки закрыты", got["systemMessage"])
        self.assertEqual(self.tool("Edit", file_path=str(self.root / "NOW.md")), "deny")
        self.assertEqual(self.tool("Write", file_path="x"), "deny")
        self.assertEqual(self.tool("mcp__odoo__create_record"), "deny")
        self.assertEqual(self.tool("mcp__odoo__search_records"), "allow")
        self.assertEqual(self.tool("Read", file_path="x"), "allow")
        for cmd in ("cat NOW.md | head -5", "git status --short", "ls -la && wc -c NOW.md",
                    "sed -n 1,20p NOW.md 2>/dev/null", "grep -rn x kb/ 2>&1 | head",
                    "pdftotext -layout in.pdf - | head -50"):
            self.assertEqual(self.tool("Bash", command=cmd), "allow", cmd)
        for cmd in ("rm -rf kb", "echo x > NOW.md", "git commit -qm x", "sed -i '' s/a/b/ NOW.md",
                    "find . -delete", "cat $(ls)", "python3 - <<'EOF'\nprint(1)\nEOF",
                    "ssh prime 'ls'", "git push origin main", "pdftotext in.pdf"):
            self.assertEqual(self.tool("Bash", command=cmd), "deny", cmd)
        reason = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {}})
        reason = reason["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("kb_start.py confirm", reason)
        self.assertIn("kb_entry.py", reason)

    def test_only_every_part_mark_in_order_opens_the_lock(self):
        self.project(big_now=True)
        bundle = self.bundle_of(self.start()["hookSpecificOutput"]["additionalContext"])
        marks = self.marks(bundle)
        self.assertGreaterEqual(len(marks), 3)
        self.assertNotIn(marks[0], json.dumps(json.loads(Path(bundle + ".json").read_text())),
                         "the sidecar keeps hashes, not marks")
        wrong = self.confirm("-".join(marks[:-1] + ["0000"]), "--session", "s1")
        self.assertEqual(wrong.returncode, 1)
        self.assertIn(f"не совпали части: {len(marks)}", wrong.stdout)
        self.assertEqual(self.tool("Edit"), "deny")
        ok = self.confirm("-".join(marks), "--session", "s1")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("ENTRY_CONFIRMED: роль dev", ok.stdout)
        self.assertEqual(self.tool("Edit"), "allow")
        self.assertIsNone(self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"}))

    def test_the_read_file_names_the_session_when_the_command_cannot(self):
        self.project(big_now=True)
        bundle = self.bundle_of(self.start()["hookSpecificOutput"]["additionalContext"])
        ok = self.confirm("-".join(self.marks(bundle)))
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("сессия s1", ok.stdout)
        self.assertEqual(self.tool("Bash", command="git commit -qm x"), "allow")

    def test_another_role_is_entered_with_its_own_file(self):
        self.project(big_now=True)
        self.start()
        out = self.run_tool("kb_entry.py", "--role", "ops")
        bundle = re.search(r"ENTRY_BUNDLE=(\S+)", out.stdout).group(1)
        ok = self.confirm("-".join(self.marks(bundle)), "--session", "s1")
        self.assertIn("ENTRY_CONFIRMED: роль ops", ok.stdout)
        self.assertEqual(self.tool("Edit"), "allow")

    def test_compaction_locks_again_with_the_confirmed_role(self):
        self.project(big_now=True)
        self.start()
        out = self.run_tool("kb_entry.py", "--role", "ops")
        bundle = re.search(r"ENTRY_BUNDLE=(\S+)", out.stdout).group(1)
        self.confirm("-".join(self.marks(bundle)), "--session", "s1")
        got = self.start(source="compact")
        context = got["hookSpecificOutput"]["additionalContext"]
        self.assertIn("контекст сжат", context)
        self.assertIn("роль ops", context)
        self.assertEqual(self.tool("Edit"), "deny")
        resumed = self.start(source="resume")
        self.assertIn("возобновление без подтверждённого входа",
                      resumed["hookSpecificOutput"]["additionalContext"])

    def test_a_session_older_than_the_hook_gets_its_entry_at_the_first_write(self):
        self.project(big_now=True)
        self.assertEqual(self.tool("Edit"), "deny")
        reminder = self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "fix it"})
        self.assertIn("KB-вход не подтверждён", reminder["hookSpecificOutput"]["additionalContext"])

    def test_two_hooks_one_entry(self):
        self.project()
        self.assertIsNotNone(self.start())
        self.assertIsNone(self.start(), "user-level and project-level hooks inject once")

    def test_small_entry_is_inlined(self):
        self.project()
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Never overwrite a card code.", context)
        self.assertIn("метка", context)
        self.assertNotIn("======== CLAUDE.md", context, "Claude loads CLAUDE.md itself")

    def test_codex_gets_the_whole_file_with_the_rules_it_does_not_load(self):
        self.project(big_now=True)
        codex = self.hook({"hook_event_name": "SessionStart", "source": "startup", "session_id": "c1"},
                          agent="codex")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ПОСЛЕДНЯЯ СТРОКА NOW", codex)
        self.assertIn("======== CLAUDE.md", codex, "Codex loads AGENTS.md, which is absent here")

    def test_own_failure_opens_the_lock_visibly_instead_of_blocking_the_machine(self):
        self.project(big_now=True)
        broken = self.base / "state-is-a-file"
        broken.write_text("x", encoding="utf-8")
        got = self.start(KB_ENTRY_STATE=str(broken))
        self.assertIn("hook упал", got["systemMessage"])
        out = subprocess.run([sys.executable, str(HERE / "kb_start.py"), "hook"],
                             input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1",
                                               "cwd": str(self.root), "tool_name": "Edit"}),
                             capture_output=True, text=True, timeout=60,
                             env=self.env(KB_ENTRY_STATE=str(broken)))
        self.assertNotIn('"deny"', out.stdout)

    def test_archived_inbox_is_not_addressed_again(self):
        """tg-archive 01.10: after moving processed packets to _inbox/archive/, kb_debts went
        quiet but kb_check kept 44 lines of «own outgoing» and «unmatched addressee»."""
        self.init_git()
        self.save("CLAUDE.md", "project_aliases: shop\n")
        self.save("NOW.md", "Обновлено: 2026-09-29\n")
        sent = ("---\ntype: agent-message\nmessage_id: out-000001\ncreated_at: 2026-09-20T00:00:00Z\n"
                "from_project: shop\nto_project: other\ndelivery_state: delivered\n---\nreply\n")
        self.save("_inbox/archive/2026-09/out.md", sent)
        self.commit_at("2026-09-20", ".")
        self.assertNotIn("ИСХОДЯЩЕЕ В СОБСТВЕННОМ ИНБОКСЕ", self.run_tool("kb_check.py").stdout)
        self.save("_inbox/out.md", sent)
        self.assertIn("ИСХОДЯЩЕЕ В СОБСТВЕННОМ ИНБОКСЕ", self.run_tool("kb_check.py").stdout)

    def test_unknown_role_is_never_named_in_the_receipt(self):
        self.project()
        out = self.run_tool("kb_entry.py", "--role", "odoo-engineer")
        receipt = next(l for l in out.stdout.splitlines() if l.startswith("ENTRY_RECEIPT"))
        self.assertIn("роль не выбрана", receipt)
        self.assertNotIn("odoo-engineer", receipt)
        self.assertEqual(out.returncode, 1)

    def test_install_merges_once_keeps_foreign_hooks_and_removes_cleanly(self):
        home = self.base / "home"
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "audit.sh"}]}
        settings.write_text(json.dumps({"theme": "dark", "hooks": {"PreToolUse": [foreign]}}))

        def run(*args):
            return subprocess.run([sys.executable, str(HERE / "kb_start.py"), "install", *args],
                                  capture_output=True, text=True, timeout=30, env=self.env(HOME=str(home)))
        self.assertEqual(run("--check").returncode, 1)
        self.assertIn("INSTALLED claude", run().stdout)
        first = settings.read_text()
        run()
        self.assertEqual(settings.read_text(), first, "idempotent")
        data = json.loads(first)
        self.assertEqual(data["theme"], "dark")
        self.assertIn(foreign, data["hooks"]["PreToolUse"])
        self.assertEqual(sum("kb_start.py" in json.dumps(g) for g in data["hooks"]["PreToolUse"]), 1)
        self.assertEqual(data["hooks"]["SessionStart"][0]["matcher"], "startup|resume|clear|compact")
        self.assertEqual(run("--check").returncode, 0)
        run("--remove")
        data = json.loads(settings.read_text())
        self.assertEqual(data["hooks"], {"PreToolUse": [foreign]})
        codex = run("--agent", "codex")
        self.assertIn("Review hooks", codex.stdout)
        hooks = json.loads((home / ".codex" / "hooks.json").read_text())["hooks"]
        self.assertEqual(hooks["SessionStart"][0]["hooks"][0]["additionalContextLimit"], 0)
        self.assertEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["additionalContextLimit"], 0)
        for event in ("Stop", "PreToolUse"):
            self.assertNotIn("additionalContextLimit", hooks[event][0]["hooks"][0],
                             "Codex warns: this event cannot emit additionalContext")
        names = [hooks[e][0]["hooks"][0].get("statusMessage") for e in hooks]
        self.assertTrue(all(n and n.startswith("База знаний: ") for n in names),
                        f"Codex lists hooks by their status line, not «Хук 1»: {names}")
        self.assertEqual(len(set(names)), 4)
        run()
        claude_hooks = json.loads(settings.read_text())["hooks"]
        self.assertEqual(claude_hooks["SessionStart"][0]["hooks"][0]["statusMessage"],
                         "База знаний: вход в проект")
        for event in ("UserPromptSubmit", "PreToolUse", "Stop"):
            ours = [g for g in claude_hooks[event] if "kb_start.py" in json.dumps(g)]
            self.assertNotIn("statusMessage", ours[0]["hooks"][0],
                             "no status flash in Claude Code on every prompt or tool call")
        self.assertIn("apply_patch", hooks["PreToolUse"][0]["matcher"])
        self.assertIn("--agent codex", hooks["SessionStart"][0]["hooks"][0]["command"])


class ExecutableEntryReview0210Tests(unittest.TestCase):
    """Fresh-context review of the 7.4.0 candidate, 02.10.2026: locks that could not be opened,
    marks that outlived compaction, an unenforced role, read-only commands that write."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    env = ExecutableEntry0110Tests.env
    hook = ExecutableEntry0110Tests.hook
    start = ExecutableEntry0110Tests.start
    tool = ExecutableEntry0110Tests.tool
    marks = ExecutableEntry0110Tests.marks
    confirm = ExecutableEntry0110Tests.confirm
    bundle_of = ExecutableEntry0110Tests.bundle_of

    def shell(self, cmd, cwd=None):
        got = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                         "tool_input": {"command": cmd}}, cwd=cwd)
        return got

    def decision(self, got):
        return (got or {}).get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def test_inline_current_still_gives_a_part_with_a_mark(self):
        self.save("CLAUDE.md", "# Rules\nkb_standard_version: 7.2.0\n\n## СЕЙЧАС\nWork in progress.\n")
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("current (NOW.md) не найден", context)
        bundle = self.bundle_of(context)
        marks = self.marks(bundle)
        self.assertGreaterEqual(len(marks), 1, "every entry has at least the roles part")
        self.assertEqual(self.confirm("-".join(marks), "--session", "s1").returncode, 0)
        self.assertEqual(self.tool("Edit"), "allow")

    def test_the_hook_confirms_the_command_itself_without_session_env_or_cache_writes(self):
        self.project(big_now=True)
        bundle = self.bundle_of(self.start()["hookSpecificOutput"]["additionalContext"])
        marks = self.marks(bundle)
        bad = self.shell(f"python3 {HERE}/kb_start.py confirm {self.root} --token {'-'.join(['0000'] * len(marks))}")
        self.assertEqual(self.decision(bad), "deny")
        self.assertIn("не совпали части", bad["hookSpecificOutput"]["permissionDecisionReason"])
        ok = self.shell(f"python3 {HERE}/kb_start.py confirm {self.root} --token {'-'.join(marks)}")
        self.assertEqual(self.decision(ok), "allow")
        self.assertEqual(self.tool("Edit"), "allow", "the hook recorded the confirmation itself")

    def test_marks_from_before_compaction_do_not_reopen_the_lock(self):
        self.project(big_now=True)
        old = self.marks(self.bundle_of(self.start()["hookSpecificOutput"]["additionalContext"]))
        self.assertEqual(self.decision(self.shell(
            f"python3 {HERE}/kb_start.py confirm {self.root} --token {'-'.join(old)}")), "allow")
        self.start(source="compact")
        self.assertEqual(self.tool("Edit"), "deny")
        replay = self.shell(f"python3 {HERE}/kb_start.py confirm {self.root} --token {'-'.join(old)}")
        self.assertEqual(self.decision(replay), "deny")
        self.assertEqual(self.confirm("-".join(old), "--session", "s1").returncode, 1)

    def test_second_compaction_after_the_dedup_window_locks_again(self):
        self.project(big_now=True)
        self.start()
        self.start(source="compact")
        context = self.start(source="compact")
        self.assertIsNone(context, "the same event twice within seconds is one entry")
        time.sleep(5.5)
        again = self.start(source="compact")
        self.assertIsNotNone(again)

    def test_a_role_is_required_when_the_project_has_roles_and_no_default(self):
        self.project(big_now=True)
        roles = json.loads((self.root / "PROJECT_ROLES.json").read_text())
        roles.pop("entry_role")
        self.save("PROJECT_ROLES.json", roles)
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Роль по умолчанию не объявлена", context)
        marks = "-".join(self.marks(self.bundle_of(context)))
        refused = self.shell(f"python3 {HERE}/kb_start.py confirm {self.root} --token {marks}")
        self.assertIn("у проекта есть роли", refused["hookSpecificOutput"]["permissionDecisionReason"])
        out = self.run_tool("kb_entry.py", "--role", "ops", "--agent", "claude")
        role_bundle = re.search(r"ENTRY_BUNDLE=(\S+)", out.stdout).group(1)
        self.assertNotIn("======== CLAUDE.md", Path(role_bundle).read_text(), "--agent skips loaded rules")
        ok = self.confirm("-".join(self.marks(role_bundle)), "--session", "s1")
        self.assertIn("ENTRY_CONFIRMED: роль ops", ok.stdout)

    def test_no_role_is_an_explicit_reasoned_choice(self):
        self.project(big_now=True)
        roles = json.loads((self.root / "PROJECT_ROLES.json").read_text())
        roles.pop("entry_role")
        self.save("PROJECT_ROLES.json", roles)
        marks = "-".join(self.marks(self.bundle_of(self.start()["hookSpecificOutput"]["additionalContext"])))
        ok = self.shell(f"python3 {HERE}/kb_start.py confirm {self.root} --token {marks} "
                        "--no-role 'question about the calendar only'")
        self.assertEqual(self.decision(ok), "allow")
        self.assertEqual(self.tool("Edit"), "allow")

    def test_role_file_outside_git_is_confirmed_by_its_path(self):
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 7.2.0\n")
        self.save("NOW.md", "Обновлено: 2026-09-29\n" + "state\n" * 3000)
        self.save("skills/dev/SKILL.md", "# Dev\n")
        self.save("PROJECT_ROLES.json", {"roles": [{"id": "dev", "skill": "dev", "load_when": ["x"]},
                                                   {"id": "ops", "skill": "dev", "load_when": ["y"]}],
                                         "skills": [{"name": "dev", "canonical": "skills/dev"}]})
        self.start()
        out = self.run_tool("kb_entry.py", "--role", "ops")
        bundle = re.search(r"ENTRY_BUNDLE=(\S+)", out.stdout).group(1)
        self.assertNotIn(str(self.root), bundle, "no git dir: the file lives in a temp folder")
        marks = "-".join(self.marks(bundle))
        self.assertIn("--bundle", self.confirm(marks, "--session", "s1").stdout)
        ok = self.confirm(marks, "--session", "s1", "--bundle", bundle)
        self.assertIn("ENTRY_CONFIRMED: роль ops", ok.stdout)

    def test_paths_with_spaces_survive_copying_the_printed_command(self):
        self.root = self.base / "Foxio LTD "
        self.root.mkdir()
        self.project(big_now=True)
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        bundle = re.search(r"целиком: (.+ENTRY-\S+\.md)", context).group(1)
        line = next(l.strip() for l in context.splitlines() if "kb_start.py" in l and " confirm " in l)
        cmd = line.replace("<метки>", "-".join(self.marks(bundle)))
        out = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=60,
                             env=self.env(CLAUDE_CODE_SESSION_ID="s1"))
        self.assertIn("ENTRY_CONFIRMED", out.stdout, out.stdout + out.stderr)

    def test_no_session_id_never_locks(self):
        self.project(big_now=True)
        got = subprocess.run([sys.executable, str(HERE / "kb_start.py"), "hook"],
                             input=json.dumps({"hook_event_name": "PreToolUse", "cwd": str(self.root),
                                               "tool_name": "Edit", "tool_input": {}}),
                             capture_output=True, text=True, timeout=60, env=self.env())
        self.assertEqual(got.stdout.strip(), "")
        self.assertFalse((self.root / ".git" / "kb-entry").exists())

    def test_the_lock_follows_the_edited_file_not_only_cwd(self):
        self.project(big_now=True)
        outside = self.base / "elsewhere"
        outside.mkdir()
        got = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                         "tool_input": {"file_path": str(self.root / "NOW.md")}}, cwd=outside)
        self.assertEqual(self.decision(got), "deny")
        patch_in = {"command": f"*** Begin Patch\n*** Update File: {self.root}/NOW.md\n@@\n-a\n+b\n*** End Patch"}
        got = self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                         "tool_input": patch_in, "session_id": "c9"}, agent="codex", cwd=outside)
        self.assertEqual(self.decision(got), "deny")

    def test_read_only_shell_check_closes_the_writes_the_review_found(self):
        self.project(big_now=True)
        self.start()
        for cmd in ("git branch new-x", "git log -1 --output=NOW.md", "git diff --output=f",
                    "sort -o NOW.md NOW.md", "uniq a NOW.md", "sed -n --in-place 's/a/b/p' f",
                    "sed -n '1w out' f", "cat f & rm -rf kb", "find . -fprint0 out", "tree -o out",
                    "rg --pre ./x y", f"python3 {HERE}/kb_start.py install",
                    f"python3 {HERE}/kb_entry.py . --out x", "awk '{print > \"f\"}' x",
                    "xargs rm < list", "env FOO=1 rm x", "echo hi >> NOW.md"):
            self.assertEqual(self.decision(self.shell(cmd)), "deny", cmd)
        self.assertEqual(self.tool("mcp__gmail__get_or_create_label"), "deny")
        for cmd in ("git -C /tmp status", "git -c core.pager=cat log -1", "git tag", "git stash list",
                    "git rev-list HEAD -3", "grep -n '->' NOW.md", "rg '=>' NOW.md",
                    f"python3 -u {HERE}/kb_due.py .", f"python3.11 {HERE}/kb_check.py .", "ps aux",
                    "cat NOW.md 2>&1 | head -5", "git config --get user.name", "ls > /dev/null"):
            self.assertEqual(self.decision(self.shell(cmd)), "allow", cmd)

    def test_template_placeholder_is_not_a_kb_project(self):
        self.save("CLAUDE.md", "# Template\nkb_standard_version: <минимальная версия, сейчас 7.2.0>\n")
        self.assertIsNone(self.start())

    def test_non_utf8_locale_still_emits_valid_json(self):
        self.project(big_now=True)
        out = subprocess.run([sys.executable, str(HERE / "kb_start.py"), "hook"],
                             input=json.dumps({"hook_event_name": "SessionStart", "session_id": "s1",
                                               "cwd": str(self.root), "source": "startup"}),
                             capture_output=True, text=True, timeout=90,
                             env=self.env(PYTHONIOENCODING="latin-1", LC_ALL="C"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("KB-", json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_install_keeps_symlinks_modes_history_and_odd_files(self):
        home = self.base / "home"
        real = self.base / "dotfiles" / "settings.json"
        real.parent.mkdir(parents=True)
        real.write_text(json.dumps({"hooks": None, "theme": "dark"}))
        real.chmod(0o600)
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").symlink_to(real)

        def run(*args):
            return subprocess.run([sys.executable, str(HERE / "kb_start.py"), "install", *args],
                                  capture_output=True, text=True, timeout=30, env=self.env(HOME=str(home)))
        self.assertIn("INSTALLED claude", run().stdout)
        self.assertTrue((home / ".claude" / "settings.json").is_symlink())
        self.assertEqual(real.stat().st_mode & 0o777, 0o600)
        self.assertIn("UNCHANGED", run().stdout)
        self.assertEqual(len(list(real.parent.glob("settings.json.kb-start-backup-*"))), 1)
        self.assertIn("NOTHING_TO_REMOVE", run("--agent", "codex", "--remove").stdout)
        self.assertFalse((home / ".codex" / "hooks.json").exists())
        real.write_text(json.dumps({"hooks": {"PreToolUse": {"matcher": "x"}}}))
        self.assertEqual(run().returncode, 2)

    def test_codex_skips_rules_it_loads_through_a_symlink(self):
        self.project(big_now=True)
        (self.root / "AGENTS.md").symlink_to("CLAUDE.md")
        codex = self.hook({"hook_event_name": "SessionStart", "source": "startup", "session_id": "c1"},
                          agent="codex")["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("======== CLAUDE.md", codex)

    def test_text_entry_does_not_relock_a_confirmed_session(self):
        self.project(big_now=True)
        marks = "-".join(self.marks(self.bundle_of(self.start()["hookSpecificOutput"]["additionalContext"])))
        self.confirm(marks, "--session", "s1")
        subprocess.run([sys.executable, str(HERE / "kb_start.py"), "text", str(self.root)],
                       capture_output=True, text=True, timeout=90, env=self.env(CLAUDE_CODE_SESSION_ID="s1"))
        self.assertEqual(self.tool("Edit"), "allow")

    def test_switch_off_per_session(self):
        self.project(big_now=True)
        self.assertIsNone(self.hook({"hook_event_name": "SessionStart", "source": "startup"},
                                    KB_ENTRY_HOOK="off"))


class ReleaseActions0210Tests(unittest.TestCase):
    """02.10.2026: after 7.4.0 «обновись» and kb_due answered «no migration» while the Odoo
    product kept five roles without entry_role and its own entry hook; tg-archive writes its
    version in backticks and the entry hook did not recognise it as a KB project."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    env = ExecutableEntry0110Tests.env
    hook = ExecutableEntry0110Tests.hook
    start = ExecutableEntry0110Tests.start

    def actions(self):
        import kb_start
        return kb_start.project_actions(str(self.root))

    def test_version_in_backticks_is_a_kb_project(self):
        self.project()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n`kb_standard_version: 7.0.0`\n")
        self.assertIsNotNone(self.start())

    def test_actions_name_what_the_release_asks_and_disappear_when_done(self):
        self.project()
        roles = json.loads((self.root / "PROJECT_ROLES.json").read_text())
        roles.pop("entry_role")
        self.save("PROJECT_ROLES.json", roles)
        self.save(".claude/settings.json", {"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": "python3 agents/scripts/cold_start.py"}]}]}})
        got = " | ".join(self.actions())
        self.assertIn("`entry_role`", got)
        # Внешний аудит 03.10.2026: диагностика hook'а показывает отпечаток, не команду.
        self.assertIn(hashlib.sha256(b"python3 agents/scripts/cold_start.py").hexdigest()[:12], got)
        self.assertIn("не называют исполняемый вход", got)
        roles["entry_role"] = "dev"
        self.save("PROJECT_ROLES.json", roles)
        self.save(".claude/settings.json", {"theme": "dark"})
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md — исполняет hook kb_start\nkb_standard_version: 7.2.0\n")
        self.assertEqual(self.actions(), [])

    def test_start_names_the_project_level_and_puts_it_in_the_receipt(self):
        self.project(big_now=True)
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 7.0.0\n")
        got = self.start()
        context = got["hookSpecificOutput"]["additionalContext"]
        self.assertIn("## Обновление (hook сделал до входа)", context)
        self.assertIn("дельта проекта открыта", context)
        self.assertIn("--project", context)
        self.assertIn("проект: дельта проекта открыта", got["systemMessage"])
        bundle = ExecutableEntry0110Tests.bundle_of(self, context)
        marks = "-".join(ExecutableEntry0110Tests.marks(self, bundle))
        ok = ExecutableEntry0110Tests.confirm(self, marks, "--session", "s1")
        receipt = next(l for l in ok.stdout.splitlines() if l.startswith("ENTRY_RECEIPT"))
        self.assertIn("проект: дельта проекта открыта", receipt)

    def test_update_runs_before_entry_and_a_new_edition_builds_the_entry(self):
        import kb_start
        calls = []

        class Done:
            def __init__(self, out):
                self.stdout, self.returncode = out, 0

        def fake(cmd, **kw):
            calls.append(cmd)
            return Done("Claude Code  копия обновлена: 7.4.0 → 7.4.1\nUPDATE_STATUS=INSTALLED\n")
        class Proc:
            pid = 0
            def communicate(self, timeout=None):
                return fake(calls_args[0]).stdout, ""
        calls_args = []

        def popen(cmd, **kw):
            calls_args.append(cmd)
            return Proc()
        with patch.object(kb_start.subprocess, "Popen", popen), \
                patch.dict(os.environ, {"KB_ENTRY_UPDATE": "", "KB_ENTRY_STATE": str(self.base / "st")}):
            got = kb_start.update_skill()
        self.assertEqual(got["status"], "INSTALLED")
        self.assertIn("7.4.0 → 7.4.1", got["line"])
        self.assertIn("--сделать", calls[0])
        with patch.dict(os.environ, {"KB_ENTRY_UPDATE": "off"}):
            self.assertEqual(kb_start.update_skill()["status"], "OFF")

    def test_review_741_receipt_kb_apply_failures_and_version_shapes(self):
        import kb_start
        self.project(big_now=True)
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 7.0.0\n")
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        marks = "-".join(ExecutableEntry0110Tests.marks(self, ExecutableEntry0110Tests.bundle_of(self, context)))
        receipt = next(l for l in ExecutableEntry0110Tests.confirm(self, marks, "--session", "s1").stdout
                       .splitlines() if l.startswith("ENTRY_RECEIPT"))
        self.assertEqual(receipt.count("проект:"), 1, receipt)
        class Run:
            def __init__(self, code, out, err=""):
                self.returncode, self.stdout, self.stderr = code, out, err
        for fake in (Run(1, "", "Traceback (most recent call last):\nAttributeError: x"),
                     Run(0, "PROJECT_VERSION_OK\nPROJECT_RELEASE_ACTIONS: НЕ ПРОВЕРЕНЫ (AttributeError)")):
            with patch.object(kb_start.subprocess, "run", lambda *a, **k: fake):
                self.assertEqual(kb_start.project_update(str(self.root))["short"],
                                 "уровень проекта не проверен")
        for line, ok in (("+ kb_standard_version: 7.2.0", True), ("KB_STANDARD_VERSION: 7.2.0", True),
                         ('"kb_standard_version": "7.2.0"', True), ("kb_standard_version: v7.2.0", True),
                         ("| kb_standard_version: 7.2.0 |", False), ("text kb_standard_version: 7.2.0", False)):
            self.assertEqual(bool(kb_start.KB_MARK.search(line)), ok, line)

    def test_a_failed_update_is_not_retried_on_every_start(self):
        import kb_start
        calls = []

        class Proc:
            pid = 0
            def communicate(self, timeout=None):
                calls.append(1)
                return "UPDATE_STATUS=UNKNOWN\n", ""
        with patch.dict(os.environ, {"KB_ENTRY_UPDATE": "", "KB_ENTRY_STATE": str(self.base / "st")}), \
                patch.object(kb_start.subprocess, "Popen", lambda *a, **k: Proc()):
            self.assertEqual(kb_start.update_skill()["status"], "UNKNOWN")
            self.assertEqual(kb_start.update_skill()["status"], "SKIPPED")
        self.assertEqual(len(calls), 1)

    def test_due_and_update_print_the_actions_instead_of_no_migration(self):
        self.project()
        roles = json.loads((self.root / "PROJECT_ROLES.json").read_text())
        roles.pop("entry_role")
        self.save("PROJECT_ROLES.json", roles)
        due = self.run_tool("kb_due.py").stdout
        self.assertIn("номер проекта менять не нужно", due)
        self.assertIn("действие выпуска", due)
        self.assertNotIn("выпуск не требует миграции", due)
        import kb_update
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kb_update.actions_of_project(str(HERE.parent), str(self.root), True)
        self.assertIn("SESSION_ACTION=APPLY_RELEASE_ACTIONS", out.getvalue())


class FoxKb0210Tests(unittest.TestCase):
    """A company knowledge base, 02.10.2026: delivering a letter into another project's inbox
    required a full entry into that project; a `%20` link to an existing file was «broken»;
    a project born at 7.2.0 could not finalize its release receipt."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    env = ExecutableEntry0110Tests.env

    def kb_project(self, name):
        root = self.base / name
        root.mkdir()
        (root / "CLAUDE.md").write_text("# Rules\nвход: NOW.md\nkb_standard_version: 7.2.0\n",
                                        encoding="utf-8")
        (root / "NOW.md").write_text("Обновлено: 2026-10-02\n" + "state\n" * 3000, encoding="utf-8")
        (root / "_inbox").mkdir()
        return root

    def tool(self, cwd, name, **tool_input):
        out = subprocess.run([sys.executable, str(HERE / "kb_start.py"), "hook"],
                             input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1",
                                               "cwd": str(cwd), "tool_name": name,
                                               "tool_input": tool_input}),
                             capture_output=True, text=True, timeout=60, env=self.env())
        got = json.loads(out.stdout) if out.stdout.strip() else {}
        return got.get("hookSpecificOutput", {}).get("permissionDecision", "allow"), got

    def test_a_new_letter_in_another_inbox_needs_the_senders_entry_only(self):
        sender, recipient = self.kb_project("fox"), self.kb_project("invest")
        letter = str(recipient / "_inbox" / "2026-10-02_fox.md")
        decision, got = self.tool(sender, "Write", file_path=letter)
        self.assertEqual(decision, "deny")
        self.assertIn("(fox)", got["hookSpecificOutput"]["permissionDecisionReason"])
        import kb_start
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            state = kb_start.load_state("s1", str(sender))
            state["confirmed"] = {"at": "now", "roles": [], "receipt": ""}
            kb_start.save_state(state)
        self.assertEqual(self.tool(sender, "Write", file_path=letter)[0], "allow")
        (recipient / "_inbox" / "old.md").write_text("x", encoding="utf-8")
        self.assertEqual(self.tool(sender, "Write", file_path=str(recipient / "_inbox" / "old.md"))[0],
                         "deny", "rewriting the recipient's file is work in its project")
        self.assertEqual(self.tool(sender, "Edit", file_path=str(recipient / "NOW.md"))[0], "deny")
        self.assertEqual(self.tool(sender, "Write", file_path=str(recipient / "_inbox" / ".." / "x.md"))[0],
                         "deny", "a path that leaves the inbox is not a delivery")
        patch_add = f"*** Begin Patch\n*** Add File: {recipient}/_inbox/codex.md\n+hi\n*** End Patch"
        self.assertEqual(self.tool(sender, "apply_patch", command=patch_add)[0], "allow")
        patch_upd = f"*** Begin Patch\n*** Update File: {recipient}/_inbox/old.md\n@@\n-x\n+y\n*** End Patch"
        self.assertEqual(self.tool(sender, "apply_patch", command=patch_upd)[0], "deny")

    def test_percent_encoded_link_to_an_existing_file_is_not_broken(self):
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\n")
        self.save("NOW.md", "Обновлено: 2026-10-02\n")
        self.save("reports/Доступ агента к GYG.md", "# Report\n")
        self.save("INDEX.md", "[r](reports/Доступ%20агента%20к%20GYG.md)\n[bad](reports/Нет%20такого.md)\n")
        out = subprocess.run([sys.executable, str(HERE / "kb_check.py"), str(self.root)],
                             capture_output=True, text=True, timeout=60).stdout
        self.assertIn("БИТЫЕ ССЫЛКИ — 1", out)
        self.assertIn("Нет%20такого", out)
        self.assertNotIn("Доступ%20агента", out)

    def test_project_born_at_its_version_finalizes_its_receipt(self):
        self.init_git()
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 7.2.0\n")
        self.save("NOW.md", "Обновлено: 2026-10-02\n")
        self.git("add", "CLAUDE.md", "NOW.md")
        self.git("commit", "-qm", "born")
        first = self.git("rev-parse", "HEAD")
        self.save("KB_RELEASE_APPLICATION.json", {"schema": 3, "application": {
            "from_version": None, "to_version": "7.2.0", "status": "finalized",
            "source": {"commit": first, "version_source": "CLAUDE.md"},
            "owner": {"accepted_by": "owner", "accepted_at": "2026-10-02"},
            "finalized_at": "2026-10-02", "open": []}})
        self.git("add", "KB_RELEASE_APPLICATION.json")
        self.git("commit", "-qm", "receipt")
        out = subprocess.run([sys.executable, str(HERE / "kb_apply.py"), str(self.root)],
                             capture_output=True, text=True, timeout=60)
        self.assertIn("APPLICATION_RECEIPT_OK", out.stdout, out.stdout)
        self.assertEqual(out.returncode, 0)



class VersionLine0210Tests(unittest.TestCase):
    """tg-archive 02.10.2026: the owner raised the project number to 7.4.2; kb_apply accepted
    it, kb_due demanded equality with the minimum line and printed a false «ПОРА» forever."""

    setUp = RedesignTests.setUp
    run_tool = RedesignTests.run_tool
    save = RedesignTests.save

    def test_a_number_above_the_minimum_is_not_a_due_item(self):
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 7.4.2\n")
        self.save("NOW.md", "Обновлено: 2026-10-02\n")
        out = self.run_tool("kb_due.py").stdout
        self.assertNotIn("примени применимое и обнови строку", out)
        self.assertIn("версия проекта: 7.4.2", out)
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 7.0.0\n")
        self.assertIn("примени применимое и обнови", self.run_tool("kb_due.py").stdout)
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nkb_standard_version: 9.1.0\n")
        self.assertIn("новее установленного скилла", self.run_tool("kb_due.py").stdout)


class TurnRegistry0210Tests(unittest.TestCase):
    """02.10.2026 audit: agents record knowledge incompletely and in the cheapest place; the
    self-check stayed green. 7.5 records every turn silently — what was done, whether it reached
    the base — without command text (commands carry secrets), and keeps project facts out of the
    agent's private memory."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    env = ExecutableEntry0110Tests.env
    hook = ExecutableEntry0110Tests.hook

    def confirmed_project(self):
        self.project(big_now=True)
        self.save("addons/x.py", "x = 1\n")
        self.commit_at("2026-10-02", ".")
        import kb_start
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            state, _ = kb_start.start_entry(str(self.root), "s1", "claude", "startup")
            state["confirmed"] = {"at": "now", "roles": ["dev"], "receipt": ""}
            kb_start.save_state(state)

    def turn(self, prompt, tools, writes):
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": prompt})
        for name, tool_input in tools:
            got = self.hook({"hook_event_name": "PreToolUse", "tool_name": name,
                             "tool_input": tool_input})
            self.assertIsNone(got, got)
        for rel, text in writes:
            self.save(rel, text)
        self.assertIsNone(self.hook({"hook_event_name": "Stop"}), "record mode is silent")
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            lines = Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()
        return json.loads(lines[-1])

    def test_a_work_turn_without_knowledge_is_recorded_as_such(self):
        self.confirmed_project()
        token_value = "tok_SECRET_123456789"
        row = self.turn("fix the bouquet", [
            ("Edit", {"file_path": str(self.root / "addons/x.py")}),
            ("Bash", {"command": f"curl -X POST https://api.example.com/v1 -H 'Authorization: {token_value}'"}),
            ("Bash", {"command": "ssh prime 'systemctl restart odoo'"}),
            ("mcp__odoo__update_record", {"id": 1}),
            ("Bash", {"command": "python3 analyse.py"})],
            [("addons/x.py", "x = 2\n")])
        self.assertEqual(row["certain"], 4)
        self.assertEqual(row["uncertain"], 1)
        self.assertEqual(row["work_files"], 1)
        self.assertEqual(row["knowledge_files"], 0)
        stored = "".join(p.read_text() for p in (self.base / "state").rglob("*.json*"))
        self.assertNotIn(token_value, stored, "no command text in state, snapshot or registry")
        self.assertNotIn("api.example.com", stored)
        self.assertNotIn("prime", stored)

    def test_secrets_never_reach_the_state_while_a_turn_runs(self):
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "deploy"})
        for cmd in ("curl -X POST https://ghp_SECRETTOKEN123@api.github.com/x",
                    "rsync -e 'sshpass -p HUNTER2PASS ssh' a b:/c", "git -C . commit -qm x"):
            self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": cmd}})
        stored = "".join(p.read_text() for p in (self.base / "state").rglob("*.json*"))
        self.assertNotIn("SECRETTOKEN", stored)
        self.assertNotIn("HUNTER2PASS", stored)
        self.hook({"hook_event_name": "Stop"})
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            row = json.loads(Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()[-1])
        self.assertEqual(row["kinds"].get("certain:git"), 1, "git -C commit is a certain git write")

    def test_a_turn_that_writes_the_base_counts_and_reading_counts_nothing(self):
        self.confirmed_project()
        row = self.turn("правило: всегда так", [("Bash", {"command": "git status --short"})],
                        [("NOW.md", "Обновлено: 2026-10-02\nрешено\n")])
        self.assertEqual(row["certain"], 0)
        self.assertEqual(row["knowledge_files"], 1)
        self.assertTrue(row["decision"])
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            summary = kb_turns.summary(str(self.root))
        self.assertEqual(summary["turns"], 1)
        self.assertEqual(summary["decision_recorded"], 1)

    def test_notifications_and_other_sessions_do_not_cut_a_turn(self):
        """03.10.2026: 97 task notifications in one session cut turns into pieces («прервано» —
        a third of all turns) and counted as owner decisions: work and its record landed in
        different pieces. Environment messages mid-turn keep the turn; after it they start one."""
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "почини букеты"})
        self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                   "tool_input": {"file_path": str(self.root / "addons/x.py")}})
        self.save("addons/x.py", "x = 3\n")
        for prompt in ("<task-notification>\n<task-id>a1</task-id>\nрешено: правило всегда\n"
                       "</task-notification>",
                       'Another Claude session sent a message:\n<cross-session-message from="uds:/x">'
                       "решено, впредь так</cross-session-message>"):
            self.hook({"hook_event_name": "UserPromptSubmit", "prompt": prompt})
        self.save("NOW.md", "Обновлено: 2026-10-03\nбукеты починены\n")
        self.hook({"hook_event_name": "Stop"})
        after = self.turn("[SYSTEM NOTIFICATION - NOT USER INPUT]\n<task-notification>впредь так"
                          "</task-notification>", [], [])
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            rows = [json.loads(line) for line in
                    Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()]
            summary = kb_turns.summary(str(self.root))
        self.assertEqual(len(rows), 2, rows)
        self.assertFalse(rows[0]["interrupted"])
        self.assertEqual((rows[0]["work_files"], rows[0]["knowledge_files"]), (1, 1),
                         "the work and its record stay in one turn")
        self.assertEqual((rows[0]["trigger"], rows[0]["decision"]), ("human", False))
        self.assertEqual((after["trigger"], after["decision"]), ("notification", False))
        self.assertEqual((summary["by_environment"], summary["decision_prompts"]), (1, 0))
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "сделай A"})
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "нет, сделай B"})
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            last = json.loads(Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()[-1])
        self.assertTrue(last["interrupted"], "a new owner prompt before Stop still closes the turn")
        import kb_turns as turns
        self.assertEqual(turns.prompt_kind("Посмотри, почему <task-notification> режет ходы"), "human",
                         "an owner quoting the tag stays the owner")
        self.assertTrue(turns.is_decision("Впредь <task-notification> не считать решением"))

    def test_compaction_in_the_middle_of_a_turn_keeps_the_turn(self):
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "почини букеты"})
        self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                   "tool_input": {"file_path": str(self.root / "addons/x.py")}})
        self.save("addons/x.py", "x = 4\n")
        self.hook({"hook_event_name": "SessionStart", "source": "compact"})
        self.save("NOW.md", "Обновлено: 2026-10-03\nпосле сжатия\n")
        self.hook({"hook_event_name": "Stop"})
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            rows = [json.loads(line) for line in
                    Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual((rows[0]["work_files"], rows[0]["knowledge_files"], rows[0]["certain"]),
                         (1, 1, 1), "work before compaction and its record after it — one turn")

    def test_commits_inside_the_turn_are_seen(self):
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        self.save("addons/x.py", "x = 3\n")
        self.save("kb/05_catalog.md", "# Catalog\nupdated\n")
        self.commit_at("2026-10-02", "addons/x.py", "kb/05_catalog.md")
        self.hook({"hook_event_name": "Stop"})
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            row = json.loads(Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()[-1])
        self.assertEqual((row["work_files"], row["knowledge_files"]), (1, 1))

    def test_a_project_in_a_subfolder_of_a_bigger_repo_counts_only_its_files(self):
        outer = self.base / "outer"
        outer.mkdir()
        self.init_git(root=outer)
        self.root = outer / "proj"
        self.root.mkdir()
        self.project(big_now=True)
        self.save("src/app.py", "a = 1\n")
        (outer / "other.py").write_text("b = 1\n")
        self.git("add", ".", root=outer)
        self.git("commit", "-qm", "base", root=outer)
        self.save("src/app.py", "a = 2\n")             # dirty before the turn
        import kb_start
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            state, _ = kb_start.start_entry(str(self.root), "s1", "claude", "startup")
            state["confirmed"] = {"at": "now", "roles": ["dev"], "receipt": ""}
            kb_start.save_state(state)
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        time.sleep(0.01)
        self.save("src/app.py", "a = 33\n")
        (outer / "other.py").write_text("b = 2\n")
        self.save("kb/решения.md", "# Решения\n")
        self.hook({"hook_event_name": "Stop"})
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            row = json.loads(Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()[-1])
        self.assertEqual((row["work_files"], row["knowledge_files"]), (1, 1))

    def test_pulled_commits_are_not_this_turns_work(self):
        self.confirmed_project()
        remote = self.base / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "origin", "HEAD:main")
        clone = self.base / "clone"
        subprocess.run(["git", "clone", "-q", "-b", "main", str(remote), str(clone)], check=True)
        self.git("config", "user.email", "x@example.invalid", root=clone)
        self.git("config", "user.name", "X", root=clone)
        (clone / "kb").mkdir(exist_ok=True)
        (clone / "kb" / "b.md").write_text("# B\n")
        (clone / "z.py").write_text("z = 1\n")
        self.git("add", ".", root=clone)
        self.git("commit", "-qm", "other agent", root=clone)
        self.git("push", "-q", "origin", "HEAD:main", root=clone)
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "pull"})
        self.git("pull", "-q", "origin", "main")
        self.hook({"hook_event_name": "Stop"})
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            row = json.loads(Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()[-1])
        self.assertEqual((row["work_files"], row["knowledge_files"]), (0, 0))

    def test_a_failing_registry_write_stays_silent_and_keeps_the_lock(self):
        self.project(big_now=True)
        self.git("add", ".")
        self.git("commit", "-qm", "x")
        self.hook({"hook_event_name": "SessionStart", "source": "startup"})
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        turns = self.base / "state" / "turns"
        turns.mkdir(parents=True, exist_ok=True)
        turns.chmod(0o500)
        try:
            out = subprocess.run([sys.executable, str(HERE / "kb_start.py"), "hook", "--agent", "codex"],
                                 input=json.dumps({"hook_event_name": "Stop", "session_id": "s1",
                                                   "cwd": str(self.root)}),
                                 capture_output=True, text=True, timeout=60, env=self.env())
        finally:
            turns.chmod(0o755)
        self.assertEqual(out.stdout.strip(), "")
        got = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {}})
        self.assertEqual(got["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_an_interrupted_turn_is_recorded_at_the_next_prompt(self):
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "first"})
        self.save("addons/x.py", "x = 9\n")
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "second"})
        import kb_turns
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            row = json.loads(Path(kb_turns.registry_path(str(self.root))).read_text().splitlines()[-1])
        self.assertTrue(row["interrupted"])
        self.assertEqual(row["work_files"], 1)

    def test_project_facts_cannot_hide_in_agent_memory(self):
        self.confirmed_project()
        mem = self.base / "home" / ".claude" / "projects" / "-x-project" / "memory"
        mem.mkdir(parents=True)

        def write(text):
            got = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Write",
                             "tool_input": {"file_path": str(mem / "fact.md"), "content": text}})
            return (got or {}).get("hookSpecificOutput", {}).get("permissionDecision", "allow")
        fact = "---\nname: f\nmetadata:\n  type: project\n---\nThe POS uses series C.\n"
        self.assertEqual(write(fact), "deny")
        self.assertEqual(write(fact + "See kb/05_catalog.md.\n"), "allow")
        self.assertEqual(write("---\nmetadata:\n  type: feedback\n---\nPrefer short answers.\n"), "allow")
        self.assertEqual(write("---\nmetadata:\n  type: reference\n---\nhttps://grafana.example\n"),
                         "allow")
        self.assertEqual(write('---\nmetadata:\n  Type: "Project"\n---\nA fact.\n'), "deny")
        self.assertEqual(write(fact + f"See {self.root}/NOW.md\n"), "allow", "absolute pointer")
        self.save("kb/решения.md", "# Решения\n")
        self.save(".claude/settings.json", "{}")
        self.git("add", "kb/решения.md", ".claude/settings.json")
        self.assertEqual(write(fact + "См. kb/решения.md\n"), "allow", "Cyrillic pointer")
        self.assertEqual(write(fact + "See .claude/settings.json\n"), "allow", "dot-folder pointer")
        (mem / "old.md").write_text(fact + "Second paragraph.\n")

        def edit(tool, tool_input):
            got = self.hook({"hook_event_name": "PreToolUse", "tool_name": tool,
                             "tool_input": dict(tool_input, file_path=str(mem / "old.md"))})
            return (got or {}).get("hookSpecificOutput", {}).get("permissionDecision", "allow")
        self.assertEqual(edit("Edit", {"old_string": "Second paragraph.\n", "new_string": ""}),
                         "allow", "retiring an old fact")
        self.assertEqual(edit("Edit", {"old_string": "Second", "new_string": "See NOW.md, second"}),
                         "allow", "adding the address")
        self.assertIn(edit("MultiEdit", {"edits": None}), ("allow", "deny"), "malformed input: no crash")
        self.assertEqual(write("---\nmetadata:\n  type: feedback\n---\nShort answers.\n"), "allow")

    def test_a_chronicle_now_is_a_release_action(self):
        self.project()
        self.save("NOW.md", "Обновлено: 2026-10-02\n" + "запись хроники\n" * 2000)
        import kb_start
        self.assertTrue(any("хроника" in a for a in kb_start.project_actions(str(self.root))))

    def test_install_adds_the_stop_hook_for_both_agents(self):
        home = self.base / "home2"
        for agent, path in (("codex", ".codex/hooks.json"), ("claude", ".claude/settings.json")):
            out = subprocess.run([sys.executable, str(HERE / "kb_start.py"), "install", "--agent", agent],
                                 capture_output=True, text=True, timeout=30, env=self.env(HOME=str(home)))
            self.assertIn("INSTALLED", out.stdout)
            self.assertIn("Stop", json.loads((home / path).read_text())["hooks"])



class ServicePass0210Tests(unittest.TestCase):
    """Owner 02.10.2026: no nightly jobs — «хорошо бы, чтобы какой-нибудь агент время от времени
    говорил: ой, пора обслужить базу». The entry hook says when (once a day, can be postponed);
    the owner says «обслужи базу»; the session follows the plan; a clean-context exam checks the
    structure. Review of the candidate: counting, nesting, closure marks, isolation, failures."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    env = ExecutableEntry0110Tests.env
    hook = ExecutableEntry0110Tests.hook

    def service(self, *args, env=None):
        return subprocess.run([sys.executable, str(HERE / "kb_service.py"), *args, str(self.root)],
                              capture_output=True, text=True, timeout=120, env=env or self.env())

    def due(self):
        return json.loads(self.service("due", "--json").stdout)

    def piled_up(self, rows=50):
        self.project()
        today = __import__("datetime").date.today().isoformat()
        entries = "".join(f"- 2026-09-{(d % 28) + 1:02d} · правка {d}: факт {d}\n" for d in range(rows))
        self.save("CORRECTIONS.md", "# Канал правок\n\n" + entries)
        self.save("CLAUDE.md", "# Rules\nвход: NOW.md\nканал правок: CORRECTIONS.md\n"
                  "kb_standard_version: 7.2.0\n")
        self.commit_at(today, ".")

    def test_due_names_what_piled_up_and_a_service_commit_resets_it(self):
        self.piled_up()
        self.assertTrue(self.due()["due"])
        self.assertIn("ждут разнесения записей канала правок: 50", self.service("due").stdout)
        context = self.hook({"hook_event_name": "SessionStart", "source": "startup"})
        self.assertIn("## Пора обслужить базу", context["hookSpecificOutput"]["additionalContext"])
        self.assertIn("пора обслужить базу", context["systemMessage"])
        again = self.hook({"hook_event_name": "SessionStart", "source": "startup", "session_id": "s2"})
        self.assertNotIn("Пора обслужить", again["hookSpecificOutput"]["additionalContext"],
                         "said once a day per project")
        entries = "".join(f"- 2026-09-{(d % 28) + 1:02d} · правка {d}: ✔ учтено → kb/05.md\n" for d in range(50))
        self.save("CORRECTIONS.md", "# Канал правок\n\n" + entries)
        self.git("add", ".")
        self.git("commit", "-qm", "Сервисный обход базы: разнесено 50 записей")
        state = self.due()
        self.assertEqual(state["since"], __import__("datetime").date.today().isoformat())
        self.assertFalse(state["due"])

    def test_closure_marks_of_real_projects_count_as_closed(self):
        self.piled_up(rows=0)
        self.save("CORRECTIONS.md", "# Канал\n\n- 2026-09-01 · a — статус CLOSED\n"
                  "- 2026-09-02 · b ✔ код исправлен\n- 2026-09-03 · c [x]\n- 2026-09-04 · d открыто\n")
        self.assertEqual(self.due()["corrections"], 1)

    def test_day_first_dates_uppercase_closure_and_the_template_are_read_right(self):
        """External audit 03.10.2026: «**ЗАКРЫТО.**» was not a closure (tg-archive, 37 entries);
        entries dated 10.09.2026 or **25/09/2026 were glued to their neighbours (UAD, a company project),
        so one neighbour's mark hid open entries; the template example counted as a debt."""
        self.piled_up(rows=0)
        self.save("CORRECTIONS.md", "# Канал\n\n"
                  "- 2026-08-23 · `path/to/file.md` — утверждает X, на самом деле Y. Источник: <чем проверил>.\n"
                  "- 2026-09-01 · a — **ЗАКРЫТО.** исправлено кодом\n"
                  "- 2026-09-02 · b — порт 3306 закрыт снаружи, причина не найдена\n"
                  "## 10.09.2026 — c открыто\n"
                  "- **25/09/2026 · d** — открыто\n"
                  "- 2026-09-26 · e ✔ закрыто\n")
        import kb_service
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            dates = sorted(d for d, _ in kb_service.open_corrections(str(self.root)))
        self.assertEqual(dates, ["2026-09-02", "2026-09-10", "2026-09-25"])
        out = self.service("plan", "--all").stdout
        self.assertIn("CORRECTIONS.md:7 ", out, "every entry carries its line address")

    def test_postponed_and_quiet_projects_are_not_nagged(self):
        self.piled_up()
        self.service("later", "--days", "3")
        import kb_service
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            self.assertEqual(kb_service.due_text(str(self.root)), "")
        self.assertTrue(self.service("due").stdout.startswith("SERVICE_LATER"))
        quiet = self.base / "quiet"
        quiet.mkdir()
        self.root = quiet
        self.project()
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.assertFalse(self.due()["due"])

    def test_plan_lists_the_pile_and_the_steps(self):
        self.piled_up()
        out = self.service("plan").stdout
        for part in ("## 1. Разнести накопленное (50", "## 2. Работа без описания", "## 3. Починить",
                     "## 4. Экзамен", "## 6. Отметка", "Сервисный обход базы:", "карта проекта"):
            self.assertIn(part, out)

    def fake(self, mode="good"):
        fake = self.base / "fake_agent.py"
        fake.write_text(r"""
import json, os, sys
args = sys.argv[1:]
cwd, out, prompt = args[args.index("--cwd") + 1], args[args.index("--out") + 1], args[-1]
mode = os.environ.get("FAKE_MODE", "good")
if prompt.startswith("ИЗВЛЕЧЕНИЕ"):
    reply = [{"id": "1", "question": "Какая серия у расходников?", "expected": "C00001"},
             {"id": "1", "question": "Столица?", "expected": "Мадрид"}]
elif prompt.startswith("ЭКЗАМЕН"):
    if mode == "dead":
        sys.exit(1)
    leak = os.path.exists(os.path.join(cwd, "QUESTIONS.md"))
    source = {"leak": "QUESTIONS.md", "outside": "~/work/proj/kb/05_catalog.md",
              "inside": os.path.join(cwd, "kb", "05_catalog.md") + " / раздел"}.get(mode, "kb/05_catalog.md")
    reply = [{"id": "1", "answer": "LEAK" if leak else "C00001", "source": source, "confidence": "высокая"},
             {"id": "2", "answer": "Мадрид", "source": "kb/geo.md", "confidence": "высокая"}]
else:
    data = json.loads(prompt[prompt.index("Данные:") + 7:])
    good = {"C00001", "Мадрид"}
    reply = [{"id": d["id"], "verdict": "PASS" if d["answer"] in good else "FAIL", "reason": "-"} for d in data]
open(out, "w").write("Источник: [QUESTIONS.md] — см. ниже\n" + json.dumps(reply, ensure_ascii=False))
""", encoding="utf-8")
        return self.env(KB_AGENT_CMD=f"{sys.executable} {fake}", FAKE_MODE=mode)

    def exam_project(self):
        self.project()
        self.save("QUESTIONS.md", "# Контрольные вопросы\n| Вопрос | Ответ |\n|---|---|\n"
                  "| Какая серия у расходников? | C00001 |\n| Столица? | Мадрид |\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def test_exam_hides_the_answers_renumbers_and_grades(self):
        self.exam_project()
        out = self.service("exam", env=self.fake("good"))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("верно 2", out.stdout, "duplicate ids renumbered, brackets in text tolerated")
        self.assertEqual(self.due()["exam_age"], 0)

    def test_a_leaking_or_dead_exam_is_not_a_pass(self):
        self.exam_project()
        leak = self.service("exam", env=self.fake("leak"))
        self.assertIn("неверно 1", leak.stdout)
        self.assertIn("неверно 1", self.service("exam", env=self.fake("outside")).stdout)
        inside = self.service("exam", env=self.fake("inside"))
        self.assertIn("верно 2", inside.stdout, "a full path inside the exam copy is not a leak")
        dead = self.service("exam", env=self.fake("dead"))
        self.assertIn("EXAM_FAILED", dead.stdout)
        self.assertEqual(dead.returncode, 1)


class EntryLock0310Tests(unittest.TestCase):
    """Внешний аудит 03.10.2026: полнота входа, Git-гейт, переносы и вывод hook'ов."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    hook = ExecutableEntry0110Tests.hook
    start = ExecutableEntry0110Tests.start
    marks = ExecutableEntry0110Tests.marks
    confirm = ExecutableEntry0110Tests.confirm
    bundle_of = ExecutableEntry0110Tests.bundle_of

    def env(self, **extra):
        extra = dict({"KB_ENTRY_HOOK": "", "KB_ENTRY_RERUN": ""}, **extra)
        return ExecutableEntry0110Tests.env(self, **extra)

    def assemble(self, roles=("dev",)):
        import kb_entry
        result = kb_entry.build(str(self.root), roles)
        bundle = self.base / "ENTRY-test.md"
        _, marks = kb_entry.write(str(self.root), result, str(bundle))
        return result, bundle, "-".join(marks)

    def assert_incomplete(self, result, bundle, token, missing):
        import kb_start
        side = json.loads(Path(str(bundle) + ".json").read_text())
        self.assertEqual(side.get("missing"), result["missing"])
        for state in (None, {"root": str(self.root), "bundle": str(bundle),
                            "part_sha256": side["part_sha256"], "roles": side["roles"],
                            "missing": result["missing"], "blocking": result["blocking"]}):
            confirmed, why = kb_start.verify(str(self.root), state, token, str(bundle),
                                              no_role="outside role")
            self.assertIsNone(confirmed)
            self.assertIn(missing, why)
        out = self.confirm(token, "--bundle", str(bundle), "--no-role", "outside role")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn(missing, out.stdout)

    def test_missing_role_method_is_not_confirmed_by_cli_or_hook(self):
        self.project()
        (self.root / "skills/dev/SKILL.md").unlink()
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        bundle = self.bundle_of(context)
        token = "-".join(self.marks(bundle))
        denied = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": f"python3 {HERE}/kb_start.py confirm "
                                           f"{self.root} --token {token}"}})
        self.assertEqual((denied or {}).get("hookSpecificOutput", {}).get("permissionDecision"),
                         "deny")
        result, bundle, token = self.assemble()
        self.assertNotIn("dev", result["found_roles"])
        self.assert_incomplete(result, bundle, token, "SKILL.md")

    def test_oversized_and_binary_methods_are_incomplete(self):
        import kb_entry
        self.project()
        method = self.root / "skills/dev/SKILL.md"
        for data, reason in ((b"x" * (kb_entry.FILE_CAP + 1), "больше предела"),
                             (b"method\0secret", "двоичный")):
            with self.subTest(reason=reason):
                method.write_bytes(data)
                result, bundle, token = self.assemble()
                self.assertNotIn("dev", result["found_roles"])
                self.assert_incomplete(result, bundle, token, reason)

    def test_unreadable_method_blocks_and_unreadable_current_warns(self):
        """A role gap holds the lock (another role or «no role» is the way out). A missing or
        unreadable non-role file is reported but does not: restoring it needs the open lock."""
        import builtins, kb_start
        self.project()
        real_open = builtins.open
        for rel in ("skills/dev/SKILL.md", "NOW.md"):
            with self.subTest(path=rel):
                blocked = self.root / rel
                def unreadable(path, *args, **kwargs):
                    if Path(path).resolve() == blocked.resolve():
                        raise PermissionError("fixture unreadable")
                    return real_open(path, *args, **kwargs)
                with patch("builtins.open", unreadable):
                    result, bundle, token = self.assemble()
                if rel == "NOW.md":
                    self.assertTrue(any("NOW.md" in m for m in result["missing"]))
                    self.assertEqual(result["blocking"], [])
                    confirmed, why = kb_start.verify(str(self.root), None, token, str(bundle))
                    self.assertIsNotNone(confirmed, why)
                else:
                    self.assert_incomplete(result, bundle, token, rel)

    def inherited_roles(self):
        self.project()
        roles = json.loads((self.root / "PROJECT_ROLES.json").read_text())
        roles["roles"][0]["extends"] = "base"
        roles["roles"][1]["extends"] = "base"
        roles["roles"].insert(0, {"id": "base", "skill": "base", "knowledge_routes": ["parent"]})
        roles["skills"].append({"name": "base", "canonical": "skills/base"})
        self.save("PROJECT_ROLES.json", roles)
        self.save("skills/base/SKILL.md", "# Parent method\nInherited stop.\n")
        self.save("kb/parent.md", "Inherited mandatory source.\n")
        index = json.loads((self.root / "KNOWLEDGE_INDEX.json").read_text())
        index["routes"].append({"id": "parent", "load_when": ["always"], "paths": ["kb/parent.md"]})
        self.save("KNOWLEDGE_INDEX.json", index)
        return roles

    def test_ancestors_and_shared_methods_are_read_once(self):
        import kb_start
        self.inherited_roles()
        result, bundle, token = self.assemble(("dev", "ops", "dev"))
        self.assertEqual(result["found_roles"], ["base", "dev", "ops"])
        text = bundle.read_text()
        self.assertEqual(text.count("# Parent method"), 1)
        self.assertEqual(text.count("# Dev method"), 1)
        self.assertIn("Inherited mandatory source.", text)
        confirmed, why = kb_start.verify(str(self.root), None, token, str(bundle))
        self.assertIsNotNone(confirmed, why)

    def test_missing_ancestor_unknown_parent_and_cycle_block_confirmation(self):
        roles = self.inherited_roles()
        (self.root / "skills/base/SKILL.md").unlink()
        result, bundle, token = self.assemble()
        self.assert_incomplete(result, bundle, token, "base")
        for parent in ("absent", "dev"):
            with self.subTest(parent=parent):
                roles["roles"][0]["extends"] = parent
                self.save("PROJECT_ROLES.json", roles)
                result, bundle, token = self.assemble()
                self.assert_incomplete(result, bundle, token, parent)

    def test_no_role_does_not_require_unselected_missing_methods(self):
        import kb_start
        self.project()
        (self.root / "skills/dev/SKILL.md").unlink()
        result, bundle, token = self.assemble(())
        self.assertEqual(result["missing"], [])
        confirmed, why = kb_start.verify(str(self.root), None, token, str(bundle),
                                         no_role="calendar question")
        self.assertIsNotNone(confirmed, why)

    def test_role_id_wins_over_another_roles_skill_name(self):
        """Adas startup 03.10.2026: the first role uses a skill named like the second role's id;
        the lookup matched the skill first and built the entry for the wrong role."""
        self.project()
        self.save("PROJECT_ROLES.json", {
            "roles": [{"id": "evidence", "skill": "steward"},
                      {"id": "steward", "skill": "lead", "extends": "evidence"}],
            "skills": [{"name": "steward", "canonical": "skills/evidence"},
                       {"name": "lead", "canonical": "skills/lead"}]})
        self.save("skills/evidence/SKILL.md", "# Evidence method\n")
        self.save("skills/lead/SKILL.md", "# Lead method\n")
        result, bundle, _ = self.assemble(("steward",))
        self.assertEqual(result["found_roles"], ["evidence", "steward"])
        self.assertIn("# Lead method", bundle.read_text())

    def test_legacy_sidecar_without_completeness_is_accepted_as_before(self):
        import kb_start
        self.project()
        _, bundle, token = self.assemble()
        side_path = Path(str(bundle) + ".json")
        side = json.loads(side_path.read_text())
        side.pop("missing")
        side.pop("blocking", None)
        side_path.write_text(json.dumps(side))
        confirmed, why = kb_start.verify(str(self.root), None, token, str(bundle))
        self.assertIsNotNone(confirmed, "a bundle built before 7.7 confirms as before: " + str(why))

    def test_git_repository_selection_environment_cannot_forge_owner(self):
        import kb_owner_gate
        self.init_git()
        self.git("remote", "add", "origin", "git@github.com:sugestr/kb-architect-lab.git")
        consumer = self.base / "consumer"
        consumer.mkdir()
        self.init_git(root=consumer)
        self.git("remote", "add", "origin", "https://github.com/example/consumer.git", root=consumer)
        runtime = {"CLAUDE_PROJECT_DIR": str(consumer)}
        for injected in ({"GIT_DIR": str(self.root / ".git")},
                         {"GIT_COMMON_DIR": str(self.root / ".git")},
                         {"GIT_DIR": str(self.root / ".git"), "GIT_WORK_TREE": str(self.root),
                          "GIT_INDEX_FILE": str(self.root / ".git/index"), "GIT_PREFIX": "spoof/",
                          "GIT_OBJECT_DIRECTORY": str(self.root / ".git/objects")}):
            with self.subTest(env=injected), patch.dict(os.environ, injected):
                self.assertEqual(kb_owner_gate.evaluate(self.root, True, runtime)["state"],
                                 "BLOCKED_WRONG_EXECUTOR")
                self.assertEqual(kb_owner_gate.evaluate(consumer, env={})["state"],
                                 "BLOCKED_WRONG_EXECUTOR")
                self.assertEqual(kb_owner_gate.evaluate(self.root, True,
                                 {"CLAUDE_PROJECT_DIR": str(self.root)})["state"], "PASS")

    def move_event(self, destination):
        return {"session_id": "move", "cwd": str(self.root), "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch", "tool_input": {"input":
                f"*** Begin Patch\n*** Update File: source.md\n*** Move to: {destination}\n"
                "@@\n-old\n+new\n*** End Patch"}}

    def test_cross_project_move_checks_destination_lock_and_records_both_paths(self):
        import kb_start
        self.project()
        other = self.base / "other"
        self.save("CLAUDE.md", "kb_standard_version: 7.2.0\nвход: NOW.md\n", root=other)
        self.save("NOW.md", "Обновлено: 2026-10-03\n", root=other)
        event = self.move_event("../other/destination.md")
        self.assertEqual(kb_start.touched_roots(event), [str(self.root), str(other)])
        with patch.dict(os.environ, self.env()):
            first, _ = kb_start.start_entry(str(self.root), "move", "codex", "startup")
            first["confirmed"], why = kb_start.verify(str(self.root), first,
                                      "-".join(self.marks(first["bundle"])))
            self.assertIsNotNone(first["confirmed"], why)
            kb_start.save_state(first)
            blocked = kb_start.on_tool(event, "codex")
            self.assertEqual(blocked["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn(str(other), blocked["hookSpecificOutput"]["permissionDecisionReason"])
            second = kb_start.load_state("move", str(other))
            second["confirmed"], why = kb_start.verify(str(other), second,
                                        "-".join(self.marks(second["bundle"])))
            self.assertIsNotNone(second["confirmed"], why)
            first["turn"], second["turn"] = {"effects": []}, {"effects": []}
            kb_start.save_state(first)
            kb_start.save_state(second)
            self.assertIsNone(kb_start.on_tool(event, "codex"))
            for root, path in ((self.root, "source.md"), (other, "destination.md")):
                self.assertIn(["certain", "file", path],
                              kb_start.load_state("move", str(root))["turn"]["effects"])

    def test_local_move_records_source_and_destination_once(self):
        import kb_start
        self.project()
        event = self.move_event("destination.md")
        self.assertEqual(kb_start.touched_roots(event), [str(self.root)])
        with patch.dict(os.environ, self.env()):
            state, _ = kb_start.start_entry(str(self.root), "move", "codex", "startup")
            state["turn"] = {"effects": []}
            kb_start.save_state(state)
            kb_start.record_effects(event, [str(self.root)], "move", "codex")
            self.assertEqual(kb_start.load_state("move", str(self.root))["turn"]["effects"],
                             [["certain", "file", "source.md"], ["certain", "file", "destination.md"]])

    def test_foreign_hook_secret_never_reaches_apply_or_entry_output(self):
        self.project()
        self.save("KB_RELEASE_APPLICATION.json", {"schema": 3, "application": {
            "from_version": None, "to_version": "7.2.0", "status": "finalized",
            "source": {"commit": self.git("rev-parse", "HEAD"), "version_source": "CLAUDE.md"},
            "owner": {"accepted_by": "fixture", "accepted_at": "2026-10-03"},
            "finalized_at": "2026-10-03", "open": []}})
        self.git("add", "--", "KB_RELEASE_APPLICATION.json")
        planted = "ARTIFICIAL_SECRET_0310"
        commands = (f"ACCESS={planted} python3 private_cold_start.py", f"echo {planted}_codex")
        for agent, command in zip(("claude", "codex"), commands):
            name = ".codex/hooks.json" if agent == "codex" else ".claude/settings.json"
            self.save(name, {"hooks": {"SessionStart": [{"hooks": [
                      {"type": "command", "command": command}]}]}})
        out = subprocess.run([sys.executable, str(HERE / "kb_apply.py"), str(self.root)],
                             capture_output=True, text=True, env=self.env(), timeout=30)
        context = self.start()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        combined = out.stdout + out.stderr + json.dumps(context, ensure_ascii=False)
        self.assertNotIn(planted, combined)
        self.assertNotIn("private_cold_start.py", combined)
        for agent, command in zip(("claude", "codex"), commands):
            name = ".codex/hooks.json" if agent == "codex" else ".claude/settings.json"
            for output in (out.stdout, json.dumps(context, ensure_ascii=False)):
                self.assertIn(name, output)
                self.assertIn(hashlib.sha256(command.encode()).hexdigest()[:12], output)
        self.assertIn("SessionStart", combined)


class HonestChecks0310Tests(unittest.TestCase):
    """Внешний аудит 03.10.2026: сбой проверки не означает отсутствие проблем."""

    setUp = RedesignTests.setUp
    save = RedesignTests.save
    init_git = RedesignTests.init_git
    git = RedesignTests.git
    commit = RedesignTests.commit
    run_tool = RedesignTests.run_tool

    def test_due_failure_is_visible_and_retried_within_the_hour(self):
        """A failed kb_due is shown as a failure, remembered for one hour (a slow project does
        not pay the timeout on every start), and retried after it — never «ПОРА пусто» for a day."""
        import kb_start
        for failure in (subprocess.CompletedProcess([], 2, "", "failed"),
                        subprocess.TimeoutExpired("kb_due", 20)):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(kb_start, "state_root", return_value=str(self.base / "state")), \
                    patch.object(kb_start.subprocess, "run") as run:
                if isinstance(failure, Exception):
                    run.side_effect = failure
                else:
                    run.return_value = failure
                self.assertIn("не выполнен", kb_start.due_summary(str(self.root)))
                self.assertIn("не выполнен", kb_start.due_summary(str(self.root)))
                self.assertEqual(run.call_count, 1, "same hour: the failure is remembered")
                for stale in (self.base / "state" / "due").glob("*.fail"):
                    stale.unlink()                    # the hour has passed
                run.side_effect = None
                run.return_value = subprocess.CompletedProcess([], 0, "ПОРА:\n  долг\n\n", "")
                self.assertIn("долг", kb_start.due_summary(str(self.root)))
                self.assertEqual(run.call_count, 2)
            shutil.rmtree(self.base / "state", ignore_errors=True)

    def test_due_partial_unknown_is_visible_in_the_cached_block(self):
        import kb_start
        with patch.object(kb_start, "state_root", return_value=str(self.base / "state")), \
                patch.object(kb_start.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 0,
                                 "Сведения и границы проверки:\n  · код — НЕ ПРОВЕРЕНО\n", "")) as run:
            for _ in range(2):
                self.assertIn("НЕ ПРОВЕРЕНО", kb_start.due_summary(str(self.root)))
            self.assertEqual(run.call_count, 1)

    def test_due_success_is_cached(self):
        import kb_start
        with patch.object(kb_start, "state_root", return_value=str(self.base / "state")), \
                patch.object(kb_start.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 0, "", "")) as run:
            self.assertEqual(kb_start.due_summary(str(self.root)), "ПОРА пусто.")
            self.assertEqual(kb_start.due_summary(str(self.root)), "ПОРА пусто.")
            self.assertEqual(run.call_count, 1)

    def test_empty_verify_before_status_is_found(self):
        self.init_git()
        self.save("action.md", "---\nverify:   \nstatus: sent\n---\nAction\n")
        self.commit("action.md")
        result = self.run_tool("kb_check.py")
        self.assertIn("ПУСТОЙ verify", result.stdout)
        self.assertEqual(result.returncode, 1)

    def test_generated_sources_distinguish_missing_untracked_and_external(self):
        self.init_git()
        self.save("sources/loose.md", "input")
        for value, reason in (("sources/missing.md", "отсутствует"),
                              ("sources/loose.md", "не в Git")):
            with self.subTest(value=value):
                findings = kb_check.generated_from_findings(str(self.root), "view.md",
                                                           "generated_from: " + value)
                self.assertEqual(len(findings), 1)
                self.assertIn(reason, findings[0][2])
        for value in ("https://example.invalid/sources/input.md", "Google Sheet", "чужой git"):
            self.assertEqual(kb_check.generated_from_findings(str(self.root), "view.md",
                                                             "generated_from: " + value), [])
        self.commit("sources/loose.md")
        self.assertEqual(kb_check.generated_from_findings(str(self.root), "view.md",
                                                         "generated_from: sources/loose.md"), [])

    def test_check_keeps_unknown_debt_scope_in_final_line(self):
        import kb_debts
        self.init_git()
        self.save("NOW.md", "Current")
        self.commit("NOW.md")
        report = kb_debts.debts(str(self.root))
        report["code"] = {"status": "NOT_CHECKED", "reason": "git log не ответил"}
        for with_debt in (False, True):
            with self.subTest(with_debt=with_debt), \
                    patch.object(sys, "argv", ["kb_check.py", str(self.root)]), \
                    patch.object(kb_debts, "debts", return_value=report), \
                    patch.object(kb_debts, "summary_lines", return_value=
                                 (["известный долг"] if with_debt else [],
                                  ["код — НЕ ПРОВЕРЕНО: git log не ответил"])), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                kb_check.main()
                final = output.getvalue().splitlines()[-1]
                self.assertIn("НЕ ПРОВЕРЕНО", final)
                self.assertNotIn("долги знания — нет", final)

    def code_report(self, replies):
        import kb_debts
        with patch.object(kb_debts, "history", return_value=[("head", 1, {"module/f.py"})]), \
                patch.object(kb_debts, "anchors_for", return_value=[("module/README.md", "whole")]), \
                patch.object(kb_debts, "git", side_effect=replies):
            return kb_debts.code(str(self.root), ["module/f.py", "module/package.json", "module/README.md"],
                                 __import__("datetime").date.today(), 10)

    def test_description_query_failure_is_unknown_and_empty_is_no_date(self):
        for reply in (None, "malformed"):
            with self.subTest(reply=reply):
                report = self.code_report([reply])
                self.assertEqual(report["status"], "NOT_CHECKED")
                self.assertEqual(report["described"], 0)
        self.assertNotEqual(self.code_report([""])["status"], "NOT_CHECKED",
                            "git answered: no commit carries the description — not an unknown")

    def test_lag_count_failure_is_unknown(self):
        report = self.code_report(["older 1 2026-01-01", None])
        self.assertEqual(report["status"], "NOT_CHECKED")
        self.assertEqual(report["described"], 0)

    def test_partial_code_debt_keeps_unknown_and_area_filter(self):
        import kb_debts
        self.init_git()
        self.save("NOW.md", "Current")
        self.commit("NOW.md")
        files = ["broken/f.py", "broken/package.json", "missing/f.py", "missing/package.json"]
        with patch.object(kb_debts, "history", return_value=[("head", 1, set(files))]), \
                patch.object(kb_debts, "anchors_for", side_effect=
                             [[("broken/README.md", "whole")], []]), \
                patch.object(kb_debts, "git", return_value=None):
            code = kb_debts.code(str(self.root), files, __import__("datetime").date.today(), 10)
        self.assertEqual(code["status"], "DEBT")
        self.assertEqual(code["unchecked"][0]["unit"], "broken")
        report = kb_debts.debts(str(self.root))
        report["code"] = code
        lines, scope = kb_debts.summary_lines(report)
        self.assertTrue(any("missing" in line for line in lines))
        self.assertTrue(any("broken" in line and "НЕ ПРОВЕРЕНО" in line for line in scope))
        for area, expected in (("broken", "NOT_CHECKED"), ("missing", "DEBT"), ("outside", "PASS")):
            with self.subTest(area=area), patch.object(kb_debts, "code", return_value=__import__("copy").deepcopy(code)):
                self.assertEqual(kb_debts.debts(str(self.root), area=area)["code"]["status"], expected)

    def test_git_lock_walk_prunes_objects_but_keeps_refs_and_logs(self):
        self.init_git()
        self.save("NOW.md", "Current")
        self.commit("NOW.md")
        git_dir = self.root / ".git"
        for name in ("objects/deep", "refs/deep", "logs/deep"):
            lock = self.save(f".git/{name}/old.lock", "lock")
            os.utime(lock, (1, 1))
        walk = os.walk
        visited = []

        def observed_walk(path, *args, **kwargs):
            for sub, dirs, files in walk(path, *args, **kwargs):
                if str(path) == str(git_dir):
                    visited.append(os.path.relpath(sub, git_dir))
                yield sub, dirs, files

        with patch.object(sys, "argv", ["kb_due.py", str(self.root)]), \
                patch.object(kb_due.os, "walk", side_effect=observed_walk), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            kb_due.main()
        self.assertFalse(any(p == "objects" or p.startswith("objects/") for p in visited))
        self.assertIn("refs/deep", visited)
        self.assertIn("logs/deep", visited)
        self.assertIn("refs/deep/old.lock", output.getvalue())


class InstallService0310Tests(unittest.TestCase):
    """Внешний аудит 03.10.2026: установка проверенного снимка и честный сервисный обход."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    env = ExecutableEntry0110Tests.env
    exam_project = ServicePass0210Tests.exam_project

    def skill(self, path, version):
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(f'---\nmetadata:\n  version: "{version}"\n---\n')
        return path

    def update(self, source, install, public=True, do=True):
        import argparse
        import kb_update
        args = argparse.Namespace(do_update=do)
        with patch.object(kb_update, "MESTA", [("Fixture", str(install))]), \
                patch.object(kb_update, "record_public_receipt", return_value=None), \
                patch.object(kb_update, "test_skill", return_value=(True, "")), \
                contextlib.redirect_stdout(io.StringIO()):
            return kb_update.update_from_source(str(source), args, "fixture", record_receipt=public)

    def test_public_remote_advance_cannot_change_verified_install(self):
        import kb_update
        remote = self.base / "remote"
        self.skill(remote, "1.0.0")
        self.init_git(root=remote)
        self.git("add", "SKILL.md", root=remote)
        self.git("commit", "-qm", "release", root=remote)
        self.git("tag", "v1.0.0", root=remote)
        checked = self.git("rev-parse", "HEAD", root=remote)
        source, temp, error = None, None, None

        def tagged(version):
            self.skill(remote, "2.0.0")
            self.git("add", "SKILL.md", root=remote)
            self.git("commit", "-qm", "remote advanced", root=remote)
            return checked, None

        with patch.object(kb_update, "PUBLIC_REPOSITORY", str(remote)), \
                patch.object(kb_update, "public_tag_commit", side_effect=tagged):
            source, temp, error = kb_update.public_source()
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        self.assertIsNone(error)
        install = self.skill(self.base / "install", "0.0.0")
        self.assertEqual(self.update(source, install), 0)
        self.assertEqual(kb_update.versiya(str(install)), "1.0.0")
        self.assertEqual(self.git("rev-parse", "HEAD", root=Path(source)), checked)

    def test_maintainer_source_keeps_prepare_route(self):
        import kb_update
        source = self.skill(self.base / "source", "1.0.0")
        install = self.skill(self.base / "install", "0.0.0")
        with patch.object(kb_update, "prepare_source", return_value=(True, "fixture", None)) as prepare:
            self.assertEqual(self.update(source, install, public=False), 0)
        prepare.assert_called_once_with(str(source), True)

    def test_killed_between_renames_recovers_before_update(self):
        import kb_update
        source = self.skill(self.base / "source", "1.0.0")
        install = self.skill(self.base / "install", "0.0.0")
        killer = self.base / "kill_update.py"
        killer.write_text("import os, signal, sys\n"
                          f"sys.path.insert(0, {str(HERE)!r})\nimport kb_update\n"
                          "rename = os.rename\n"
                          "def kill_after_old(a, b):\n"
                          "    rename(a, b)\n"
                          "    if a == sys.argv[2]: os.kill(os.getpid(), signal.SIGKILL)\n"
                          "kb_update.os.rename = kill_after_old\n"
                          "kb_update.safe_replace(sys.argv[1], sys.argv[2], '0.0.0')\n")
        killed = subprocess.run([sys.executable, str(killer), str(source), str(install)],
                                capture_output=True, text=True, timeout=15)
        self.assertLess(killed.returncode, 0)
        self.assertFalse(install.exists())
        self.assertEqual(self.update(source, install), 0)
        self.assertEqual(kb_update.versiya(str(install)), "1.0.0")
        self.assertTrue(any(kb_update.versiya(str(p)) == "0.0.0"
                            for p in (install.parent / ".backups").iterdir()))

    def test_recovery_precedes_fast_receipt_and_network_failure(self):
        import kb_update
        source = self.skill(self.base / "source", "1.0.0")
        install = self.skill(self.base / "install", "0.0.0")
        rename = os.rename

        def stop(a, b):
            rename(a, b)
            if a == str(install):
                raise SystemExit("остановка между rename")

        with patch.object(kb_update.os, "rename", side_effect=stop):
            with self.assertRaises(SystemExit):
                kb_update.safe_replace(str(source), str(install), "0.0.0")
        with patch.object(kb_update, "MESTA", [("Fixture", str(install))]), \
                patch.object(sys, "argv", ["kb_update.py", "--public", "--fast", "--do"]), \
                patch.object(kb_update, "fast_public_check", return_value=2), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(kb_update.main(), 2)
        self.assertEqual(kb_update.versiya(str(install)), "0.0.0")

    def test_completed_rename_recovery_keeps_new_release_and_report_only_does_not_write(self):
        import kb_update
        source = self.skill(self.base / "source", "1.0.0")
        install = self.skill(self.base / "install", "0.0.0")
        rename = os.rename

        def stop(a, b):
            rename(a, b)
            if b == str(install):
                raise SystemExit("остановка после обоих rename")

        with patch.object(kb_update.os, "rename", side_effect=stop):
            with self.assertRaises(SystemExit):
                kb_update.safe_replace(str(source), str(install), "0.0.0")
        journal = Path(kb_update.install_journal(str(install)))
        self.assertTrue(journal.exists())
        self.assertEqual(self.update(source, install, do=False), 2)
        self.assertTrue(journal.exists())
        self.assertEqual(self.update(source, install), 0)
        self.assertFalse(journal.exists())
        self.assertEqual(kb_update.versiya(str(install)), "1.0.0")

    def test_external_questions_absolute_parent_and_symlink_are_refused(self):
        import kb_service
        self.project()
        external = self.save("outside.md", "контрольные ответы", root=self.base)
        for declared in (str(external), "../outside.md", "linked.md"):
            with self.subTest(declared=declared):
                link = self.root / "linked.md"
                if not link.exists():
                    link.symlink_to(external)
                self.save("CLAUDE.md", f"# Rules\nвопросы: {declared}\n")
                with patch.object(kb_service, "run_agent") as agent:
                    report = kb_service.exam(str(self.root))
                self.assertEqual(report["status"], "UNSAFE_QUESTIONS")
                self.assertIn("вне", report["reason"])
                agent.assert_not_called()
                self.assertEqual(external.read_text(), "контрольные ответы")

    def exam_agent(self, calls):
        def run(prompt, cwd):
            cwd = Path(cwd)
            calls.append((prompt, cwd))
            if prompt.startswith("ИЗВЛЕЧЕНИЕ"):
                self.assertIn("Прочитай файл QUESTIONS.md", prompt)
                self.assertIn("HEAD answer", (cwd / "QUESTIONS.md").read_text())
                self.assertNotIn("dirty answer", (cwd / "QUESTIONS.md").read_text())
                return json.dumps([{"question": "Вопрос?", "expected": "HEAD answer"}])
            if prompt.startswith("ЭКЗАМЕН"):
                self.assertFalse((cwd / "QUESTIONS.md").exists())
                self.assertEqual((cwd / "kb" / "answer.md").read_text(), "HEAD answer")
                self.assertFalse((cwd / "sibling.md").exists())
                return json.dumps([{"id": "1", "answer": "HEAD answer", "source": "kb/answer.md"}])
            return json.dumps([{"id": "1", "verdict": "PASS"}])
        return run

    def test_nested_exam_uses_one_head_snapshot_and_reports_dirty_questions(self):
        import kb_service
        repo = self.base / "repo"
        repo.mkdir()
        self.root = repo / "nested" / "project"
        self.root.mkdir(parents=True)
        self.init_git(root=repo)
        self.save("CLAUDE.md", "# Rules\nвопросы: QUESTIONS.md\n")
        self.save("QUESTIONS.md", "# Вопросы\nHEAD answer")
        self.save("kb/answer.md", "HEAD answer")
        self.save("sibling.md", "не часть проекта", root=repo)
        self.git("add", ".", root=repo)
        self.git("commit", "-qm", "snapshot", root=repo)
        sha = self.git("rev-parse", "HEAD", root=repo)
        self.save("QUESTIONS.md", "dirty answer")
        self.save("kb/answer.md", "dirty answer")
        calls = []
        with patch.dict(os.environ, self.env()), \
                patch.object(kb_service, "run_agent", side_effect=self.exam_agent(calls)):
            report = kb_service.exam(str(self.root))
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["pass"], 1)
        self.assertEqual(report["snapshot"], sha)
        self.assertTrue(report["questions_dirty"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            kb_service.print_exam(report)
        self.assertIn("HEAD", output.getvalue())
        self.assertIn("незакоммич", output.getvalue())
        self.assertEqual(len({str(cwd) for _, cwd in calls}), 1)
        self.assertEqual((self.root / "QUESTIONS.md").read_text(), "dirty answer")

    def test_untracked_questions_do_not_exam_a_different_snapshot(self):
        import kb_service
        self.project()
        self.git("add", ".")
        self.git("commit", "-qm", "snapshot")
        self.save("QUESTIONS.md", "новые вопросы, которых нет в HEAD")
        with patch.object(kb_service, "run_agent") as agent:
            report = kb_service.exam(str(self.root))
        self.assertEqual(report["status"], "NO_QUESTIONS_IN_HEAD")
        self.assertTrue(report["questions_dirty"])
        agent.assert_not_called()

    def test_absolute_questions_inside_project_are_read_from_head_copy(self):
        import kb_service
        self.init_git()
        self.save("CLAUDE.md", f"# Rules\nвопросы: {self.root / 'QUESTIONS.md'}\n")
        self.save("QUESTIONS.md", "HEAD answer")
        self.save("kb/answer.md", "HEAD answer")
        self.git("add", ".")
        self.git("commit", "-qm", "snapshot")
        self.save("QUESTIONS.md", "dirty answer")
        calls = []
        with patch.dict(os.environ, self.env()), \
                patch.object(kb_service, "run_agent", side_effect=self.exam_agent(calls)):
            report = kb_service.exam(str(self.root))
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["pass"], 1)
        self.assertTrue(report["questions_dirty"])
        self.assertEqual((self.root / "QUESTIONS.md").read_text(), "dirty answer")

    def test_snapshot_questions_symlink_cannot_escape_temporary_copy(self):
        import kb_service
        self.project()
        external = self.save("outside.md", "ответы", root=self.base)
        questions = self.root / "QUESTIONS.md"
        questions.symlink_to(external)
        self.git("add", ".")
        self.git("commit", "-qm", "unsafe snapshot")
        questions.unlink()
        questions.write_text("безопасное рабочее дерево")
        with patch.object(kb_service, "run_agent") as agent:
            report = kb_service.exam(str(self.root))
        self.assertEqual(report["status"], "UNSAFE_QUESTIONS")
        agent.assert_not_called()
        self.assertEqual(external.read_text(), "ответы")

    def test_failed_due_has_hourly_retry_and_no_daily_success_flag(self):
        import datetime
        import kb_service
        now = time.time()
        with patch.dict(os.environ, self.env()), \
                patch.object(time, "time", return_value=now), \
                patch.object(kb_service, "accumulated", side_effect=RuntimeError("расчёт упал")) as calc:
            with self.assertRaises(RuntimeError):
                kb_service.due_text(str(self.root), once_a_day=True)
            flag = Path(kb_service.state_dir("said")) / (kb_service.key(str(self.root)) + "-" +
                                                       datetime.date.today().isoformat())
            self.assertFalse(flag.exists())
            self.assertEqual(kb_service.due_text(str(self.root), once_a_day=True), "")
            self.assertEqual(calc.call_count, 1)
            with patch.object(time, "time", return_value=now + 3601):
                with self.assertRaises(RuntimeError):
                    kb_service.due_text(str(self.root), once_a_day=True)
            self.assertEqual(calc.call_count, 2)
        with patch.dict(os.environ, self.env()), \
                patch.object(time, "time", return_value=now + 7202), \
                patch.object(kb_service, "accumulated", return_value={"due": False}) as calc:
            self.assertEqual(kb_service.due_text(str(self.root), once_a_day=True), "")
            self.assertTrue(flag.exists())
            self.assertEqual(kb_service.due_text(str(self.root), once_a_day=True), "")
            self.assertEqual(calc.call_count, 1)

    def test_quoted_inline_and_fenced_closures_do_not_close_open_entries(self):
        import kb_service
        self.save("CORRECTIONS.md", "# Канал\n"
                  "- 2026-09-01 · ошибка: система показывает CLOSED\n"
                  "> статус CLOSED, ✔ закрыто [x] **ЗАКРЫТО**\n"
                  "- 2026-09-02 · пример `статус CLOSED ✔ [x] ЗАКРЫТО`\n"
                  "- 2026-09-03 · код\n```markdown\nстатус CLOSED ✔ [x] ЗАКРЫТО\n"
                  "- 2026-09-20 · пример записи в коде\n```\n"
                  "- 2026-09-04 · код\n~~~markdown\nстатус CLOSED ✔ [x] ЗАКРЫТО\n~~~\n"
                  "- 2026-09-05 · пример ``статус CLOSED `✔` [x] ЗАКРЫТО``\n"
                  "- 2026-09-06 · закрыто по делу — статус CLOSED\n"
                  "- 2026-09-07 · закрыто по делу ✔ код исправлен\n")
        dates = sorted(d for d, _ in kb_service.open_corrections(str(self.root)))
        self.assertEqual(dates, [f"2026-09-{n:02d}" for n in range(1, 6)])

    def test_closed_as_a_status_mark_closes_and_closed_in_prose_does_not(self):
        """Lab check 03.10.2026 on real channels: the old parser closed entries on «fail-closed»,
        «411/497 closed», «`closed`» (tg-archive 22, a health project 8, UAD 1 entries hidden);
        «· CLOSED 2026-09-18:» is a real status mark and must keep closing."""
        import kb_service
        self.save("CORRECTIONS.md", "# Канал\n"
                  "- 2026-09-01 · a — fail-closed барьер остался\n"
                  "- 2026-09-02 · b — projection 411/497 closed, 86 open\n"
                  "- 2026-09-03 · c — статус `closed` заменён на answered\n"
                  "- 2026-09-04 · d — поправлено · CLOSED 2026-09-18: маршруты\n"
                  "- 2026-09-05 · e — **CLOSED**\n")
        dates = sorted(d for d, _ in kb_service.open_corrections(str(self.root)))
        self.assertEqual(dates, ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_registry_counts_from_exact_service_time_and_age_from_first_trigger(self):
        import kb_service
        import kb_turns
        self.project()
        self.git("add", ".")
        self.git("commit", "-qm", "Сервисный обход базы: fixture")
        cutoff = int(self.git("show", "-s", "--format=%ct", "HEAD"))
        rows = [{"ts_epoch": cutoff - 10 * 86400, "session": "old", "certain": ["file"]},
                {"ts_epoch": cutoff - 8 * 86400, "session": "first", "trigger": "owner"},
                {"ts_epoch": cutoff - 1, "session": "before", "trigger": "owner", "certain": ["file"]}]
        rows += [{"ts_epoch": cutoff + i + 1, "session": f"after{i}", "trigger": "owner",
                  "certain": ["file"]} for i in range(10)]
        with patch.dict(os.environ, self.env()):
            path = Path(kb_turns.registry_path(str(self.root)))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with patch.object(kb_turns.time, "time", return_value=cutoff + 100):
                result = kb_service.accumulated(str(self.root))
        self.assertEqual(result["unrecorded_turns"], 10)
        self.assertIn("ходов с работой без записи в базу: 10", result["reasons"])

    def test_registry_age_ignores_old_rows_without_trigger(self):
        import kb_service
        import kb_turns
        self.project()
        self.git("add", ".")
        self.git("commit", "-qm", "snapshot")
        now = time.time()
        rows = [{"ts_epoch": now - 20 * 86400, "session": "legacy", "certain": ["file"]}]
        rows += [{"ts_epoch": now - 100 + i, "session": str(i), "trigger": "owner",
                  "certain": ["file"]} for i in range(10)]
        with patch.dict(os.environ, self.env()):
            path = Path(kb_turns.registry_path(str(self.root)))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            result = kb_service.accumulated(str(self.root))
        self.assertEqual(result["unrecorded_turns"], 10)
        self.assertFalse(any("ходов с работой" in r for r in result["reasons"]))


class TurnRegistry0310Tests(unittest.TestCase):
    """Внешний аудит 03.10.2026: реестр различает чтение, попытку и результат."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    env = ExecutableEntry0110Tests.env
    hook = ExecutableEntry0110Tests.hook
    confirmed_project = TurnRegistry0210Tests.confirmed_project

    def effects(self, cmd):
        import kb_start, kb_turns
        return kb_turns.shell_effects(cmd, kb_start.shell_segments(cmd), kb_start.shell_read_only)

    def rows(self):
        import kb_turns
        with patch.dict(os.environ, self.env()):
            path = Path(kb_turns.registry_path(str(self.root)))
            return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []

    def test_real_read_patterns(self):
        for cmd in ("ssh prime 'ps aux | head; ls /tmp'",
                    "ssh -p 22 prime 'journalctl -u odoo -n 20 --no-pager'",
                    "ssh -i /tmp/key prime 'cat README.md; ls'",
                    "sed -n '/## 6. Текст Jose/,$p' chapter.md", "sleep 1",
                    "curl -X GET https://example.invalid", "curl --request=GET https://example.invalid"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.effects(cmd), [])

    def test_explicit_writes(self):
        for cmd, kind in (("mkdir -p out", "file"), ("cp a b", "file"), ("mv a b", "file"),
                          ("rm a", "file"), ("touch a", "file"), ("chmod 600 a", "file"),
                          ("pkill -f odoo", "process"), ("kill 123", "process"),
                          ("ssh prime 'cp a b'", "file"), ("scp a prime:/tmp/a", "remote"),
                          ("rsync -e 'ssh -p 22' a prime:/tmp/", "remote"),
                          ("rsync -p a prime:/tmp/", "remote"),
                          ("curl --request=POST https://example.invalid", "http"),
                          ("curl --request POST https://example.invalid", "http"),
                          ("curl -X GET --data-raw=x https://example.invalid", "http")):
            with self.subTest(cmd=cmd):
                self.assertIn(("certain", kind), self.effects(cmd))

    def test_complex_shell_stays_uncertain_but_keeps_writes(self):
        for cmd in ("git commit -F - <<'EOF'\nfix\nEOF",
                    "cat <<'EOF'\ngit commit -qm example\nEOF\ngit commit -qm real",
                    "x=$(cat a); mkdir -p out"):
            effects = self.effects(cmd)
            self.assertTrue(any(c == "certain" for c, k in effects), effects)
            self.assertTrue(any(c == "uncertain" for c, k in effects), effects)
        for cmd in ("python3 read.py", "node read.js", "cat $(python3 write.py)",
                    "cat <<'EOF'\ngit commit -qm example\nEOF", "ssh prime", "sftp prime",
                    "scp prime:/tmp/a ./a", "ssh prime 'python3 x.py'",
                    "sed -n '/start/,$p;w out' a"):
            effects = self.effects(cmd)
            self.assertTrue(any(c == "uncertain" for c, k in effects), effects)
        self.assertNotIn(("certain", "git"), self.effects("cat <<'EOF'\ngit commit -qm example\nEOF"))

    def test_prompt_duplicate_is_an_event_not_permanent_text_dedup(self):
        self.confirmed_project()
        event = {"hook_event_name": "UserPromptSubmit", "prompt": "правило: сделай A"}
        self.hook(event)
        self.hook(event)
        self.assertEqual(self.rows(), [])
        self.hook({"hook_event_name": "Stop"})
        self.hook(event)
        self.hook({"hook_event_name": "Stop"})
        self.assertEqual(len(self.rows()), 1, "дубль после Stop тоже не создаёт пустой ход")
        import kb_start
        with patch.dict(os.environ, self.env()), patch.object(kb_start.time, "time", return_value=time.time() + 10):
            state = kb_start.load_state("s1", str(self.root))
            kb_start.begin_turn(state, str(self.root), event["prompt"])
            kb_start.finish_turn(state)
        self.assertEqual(len(self.rows()), 2, "тот же текст позднее — новая реплика")

    def test_concurrent_hooks_keep_effects_and_one_stop(self):
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        events = [{"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": str(i),
                   "tool_input": {"command": "mkdir -p out"}} for i in range(12)]
        self.parallel_hooks(events)
        self.parallel_hooks([{"hook_event_name": "Stop"}] * 4)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kinds"].get("certain:file"), 12)

    def parallel_hooks(self, events):
        procs = [subprocess.Popen([sys.executable, str(HERE / "kb_start.py"), "hook"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, env=self.env()) for event in events]
        for proc, event in zip(procs, events):
            proc.stdin.write(json.dumps(dict(session_id="s1", cwd=str(self.root), **event)))
            proc.stdin.close()
            proc.stdin = None
        for proc in procs:
            out, err = proc.communicate(timeout=30)
            self.assertEqual(proc.returncode, 0, err)
            self.assertEqual(out, "", out)

    def test_result_events_and_no_result_are_distinct(self):
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        for ident, result in (("ok", {"exit_code": 0}), ("bad", {"isError": True}),
                              ("unknown", None), ("failure", "failure")):
            event = {"tool_name": "Bash", "tool_use_id": ident,
                     "tool_input": {"command": "cp a b"}}
            self.hook(dict(event, hook_event_name="PreToolUse"))
            if result is not None:
                post = dict(event, hook_event_name="PostToolUseFailure" if result == "failure" else "PostToolUse",
                            tool_response=result)
                self.hook(post)
                self.hook(post)
        self.hook({"hook_event_name": "Stop"})
        row = self.rows()[-1]
        self.assertEqual(row["outcomes"], {"attempt": 1, "succeeded": 1, "failed": 2})
        self.assertEqual(row["certain_succeeded"], 1)
        import kb_start
        self.assertEqual([e[0] for e in kb_start.HOOK_EVENTS],
                         ["SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"])

    def test_attempt_without_a_result_counts_as_work_and_a_known_failure_does_not(self):
        """Lab review 03.10.2026: result events (PostToolUse) are not installed yet, so an attempt
        with an unknown outcome stays work as before 7.7 — never a «success»; once a result is
        known, only what succeeded is work."""
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": "cp a b"}})
        self.hook({"hook_event_name": "Stop"})
        import kb_turns
        with patch.dict(os.environ, self.env()):
            s = kb_turns.summary(str(self.root))
        self.assertEqual((s["turns_with_work"], s["turns_succeeded"]), (1, 0))
        self.assertEqual(self.rows()[-1]["outcomes"], {"attempt": 1, "succeeded": 0, "failed": 0})
        with patch.dict(os.environ, self.env()):
            kb_turns.record(str(self.root), {"ts_epoch": time.time(), "trigger": "human", "certain": 1,
                                             "outcomes": {"attempt": 0, "succeeded": 0, "failed": 1}})
            self.assertEqual(kb_turns.summary(str(self.root))["turns_with_work"], 1,
                             "a known failure adds no work")

    def test_rotation_is_serialized(self):
        import kb_turns
        with patch.dict(os.environ, self.env()):
            path = Path(kb_turns.registry_path(str(self.root)))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"seed": "x" * (kb_turns.ROTATE_BYTES + 1)}) + "\n")
            code = "import kb_turns,sys; kb_turns.record(sys.argv[1], {'writer': sys.argv[2]})"
            procs = [subprocess.Popen([sys.executable, "-c", code, str(self.root), str(i)],
                                     cwd=HERE, env=self.env()) for i in range(12)]
            for proc in procs:
                self.assertEqual(proc.wait(timeout=30), 0)
            self.assertIn("seed", json.loads(Path(str(path) + ".1").read_text()))
            self.assertEqual({json.loads(s)["writer"] for s in path.read_text().splitlines()},
                             {str(i) for i in range(12)})

    def test_worktree_registry_and_local_snapshots(self):
        self.confirmed_project()
        worktree = self.base / "writer"
        self.git("worktree", "add", "-q", "-b", "writer", str(worktree))
        import kb_turns
        with patch.dict(os.environ, self.env()):
            self.assertEqual(kb_turns.registry_path(str(self.root)), kb_turns.registry_path(str(worktree)))
            self.assertNotEqual(kb_turns.snap_path("s1", str(self.root)), kb_turns.snap_path("s1", str(worktree)))
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"}, cwd=worktree)
        self.hook({"hook_event_name": "Stop"})
        row = self.rows()[-1]
        self.assertTrue(row["worktree"])
        self.assertEqual(row["project"], self.root.name)

    def test_cli_defaults_to_current_generation(self):
        import kb_turns
        with patch.dict(os.environ, self.env()):
            kb_turns.record(str(self.root), {"ts_epoch": time.time()})
            kb_turns.record(str(self.root), {"ts_epoch": time.time(), "trigger": "human"})
        for options, count in (([], 1), (["--all-generations"], 2)):
            out = subprocess.run([sys.executable, str(HERE / "kb_turns.py"), str(self.root), "--json", *options],
                                 env=self.env(), capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout)["turns"], count)

    def test_snapshot_has_one_budget_and_bounded_reflog(self):
        import kb_turns
        calls, clock = [], [100.0]
        def slow_run(args, **kw):
            calls.append((args, kw["timeout"]))
            clock[0] += kw["timeout"]
            raise subprocess.TimeoutExpired(args, kw["timeout"])
        with patch.object(kb_turns.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(kb_turns.subprocess, "run", side_effect=slow_run):
            snap = kb_turns.snapshot(str(self.root))
        self.assertLessEqual(sum(timeout for args, timeout in calls), 10)
        self.assertIsNone(snap["dirty"])
        self.assertTrue(snap["incomplete"])
        with patch.object(kb_turns, "git", return_value=b"") as run:
            kb_turns.reflog(str(self.root))
        self.assertTrue(any(str(a).startswith("-n") for a in run.call_args.args), run.call_args)

    def test_saturated_reflog_still_finds_new_commits(self):
        import kb_turns
        before = [(str(i), "commit: old") for i in range(501)]
        with patch.object(kb_turns, "reflog", return_value=before):
            snap = kb_turns.snapshot(str(self.root))
        with patch.object(kb_turns, "reflog", return_value=[("new", "commit: new")] + before[:500]):
            self.assertEqual(kb_turns.local_commits(str(self.root), snap), ["new"])

    def test_rollback_of_preexisting_dirty_knowledge_is_not_capture(self):
        self.confirmed_project()
        self.save("NOW.md", "dirty before turn\n")
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "отмени"})
        self.git("restore", "NOW.md")
        self.hook({"hook_event_name": "Stop"})
        self.assertEqual(self.rows()[-1]["knowledge_files"], 0)

    def test_prompt_dedup_is_session_specific_and_parallel(self):
        self.confirmed_project()
        event = {"hook_event_name": "UserPromptSubmit", "prompt": "go"}
        self.parallel_hooks([event] * 4)
        self.hook({"hook_event_name": "Stop"})
        self.assertEqual(len(self.rows()), 1)
        import kb_start
        with patch.dict(os.environ, self.env()):
            state = kb_start.load_state("s1", str(self.root))
            state["session"] = "s2"
            kb_start.save_state(state)
        self.hook(dict(event, session_id="s2"))
        self.hook({"hook_event_name": "Stop", "session_id": "s2"})
        self.assertEqual(len(self.rows()), 2)

    def test_subprojects_are_not_merged_by_common_git_dir(self):
        self.confirmed_project()
        nested = self.root / "nested"
        nested.mkdir()
        import kb_turns
        with patch.dict(os.environ, self.env()):
            self.assertNotEqual(kb_turns.registry_path(str(self.root)), kb_turns.registry_path(str(nested)))

    def test_read_gate_does_not_accept_scripts_or_complex_sed(self):
        import kb_start
        for cmd in ("sed -n '/## 6/,$p' a", "sed -n '/a\\/b/,$p' a", "sleep 1"):
            self.assertTrue(kb_start.shell_read_only(cmd), cmd)
        for cmd in ("sed -n -e 1p -e 'w out' a", "sed -n '/a/,$p;w out' a",
                    "python3 -c 'print(1)'", "node -e 'console.log(1)'", "cat $(touch out)",
                    "cat <<'EOF'\nhi\nEOF", "sleep $N"):
            self.assertFalse(kb_start.shell_read_only(cmd), cmd)
        self.assertIn(("certain", "file"), self.effects("curl -X GET -o out https://example.invalid"))
        self.assertIn(("uncertain", "remote"), self.effects("ssh -o 'ProxyCommand=touch out' prime 'cat a'"))

    def test_missing_snapshot_does_not_capture_preexisting_dirty_files(self):
        self.confirmed_project()
        self.save("NOW.md", "dirty before turn\n")
        import kb_turns
        snap = {"dirty": None, "reflog_n": None, "incomplete": True}
        self.assertEqual(kb_turns.changed_since(str(self.root), snap), set())

    def test_separate_git_dirs_keep_distinct_project_keys(self):
        self.git("init", "-q", "--separate-git-dir", str(self.base / "first.git"))
        second = self.base / "second"
        second.mkdir()
        self.git("init", "-q", "--separate-git-dir", str(self.base / "second.git"), root=second)
        import kb_turns
        with patch.dict(os.environ, self.env()):
            self.assertNotEqual(kb_turns.root_key(str(self.root)), kb_turns.root_key(str(second)))
            self.assertFalse(kb_turns.project_identity(str(self.root))[1])

    def test_result_callback_keeps_secrets_out_of_state(self):
        self.confirmed_project()
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        event = {"tool_name": "mcp__fixture__send", "tool_use_id": "tool-secret-marker",
                 "tool_input": {"password": "input-secret-marker"}}
        self.hook(dict(event, hook_event_name="PreToolUse"))
        self.hook(dict(event, hook_event_name="PostToolUse",
                       tool_response={"error": "response-secret-marker"}))
        self.hook({"hook_event_name": "Stop"})
        self.assertEqual(self.rows()[-1]["outcomes"]["failed"], 1)
        stored = "".join(p.read_text() for p in (self.base / "state").rglob("*.json*"))
        self.assertNotIn("secret-marker", stored)

    def test_legacy_certain_is_not_a_successful_result(self):
        import kb_turns
        with patch.dict(os.environ, self.env()):
            kb_turns.record(str(self.root), {"ts_epoch": time.time(), "trigger": "human", "certain": 1})
            summary = kb_turns.summary(str(self.root), whole_only=True)
        self.assertEqual(summary["turns_certain"], 1)
        self.assertEqual(summary["turns_attempted"], 1)
        self.assertEqual(summary["turns_with_work"], 1, "unknown outcome: work, as before 7.7")
        self.assertEqual(summary["turns_succeeded"], 0, "but never a success")



class Review0310Tests(unittest.TestCase):
    """Independent review of the 7.7.0 candidate, 03.10.2026: a turn begun under 7.6 keeps its
    effects, an unclosed code fence does not swallow the next entries, a git failure inside a
    repository stays unknown."""

    setUp = RedesignTests.setUp
    git = RedesignTests.git
    init_git = RedesignTests.init_git
    save = RedesignTests.save
    commit_at = KnowledgeDebts2609Tests.commit_at
    project = ExecutableEntry0110Tests.project
    env = ExecutableEntry0110Tests.env

    def test_a_turn_begun_before_7_7_keeps_its_effects(self):
        import kb_start
        self.project()
        with patch.dict(os.environ, {"KB_ENTRY_STATE": str(self.base / "state")}):
            state, _ = kb_start.start_entry(str(self.root), "s1", "claude", "startup")
            state["confirmed"] = {"at": "now", "roles": ["dev"], "receipt": ""}
            state["turn"] = {"at": "then", "decision": False, "trigger": "human",
                             "effects": [["certain", "remote"], ["uncertain", "shell"]]}
            kb_start.save_state(state)
            kb_start.record_effects({"tool_name": "Bash", "cwd": str(self.root),
                                     "tool_input": {"command": "mkdir -p out"}},
                                    [os.path.realpath(str(self.root))], "s1", "claude")
            turn = kb_start.load_state("s1", str(self.root))["turn"]
        kinds = [f"{e[0]}:{e[1]}" for e in turn["effects"]]
        self.assertIn("certain:remote", kinds)
        self.assertIn("uncertain:shell", kinds)
        self.assertTrue(any(k.startswith("certain:file") for k in kinds), kinds)

    def test_an_unclosed_fence_does_not_swallow_the_next_entries(self):
        import kb_service
        self.save("CORRECTIONS.md", "# Канал\n- 2026-09-01 · a\n```\nнезакрытый блок\n"
                                    "- 2026-09-02 · b\n- 2026-09-03 · c\n")
        self.save("CLAUDE.md", "# Rules\nканал правок: CORRECTIONS.md\n")
        dates = sorted(d for d, _ in kb_service.open_corrections(str(self.root)))
        self.assertEqual(dates, ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_git_failure_inside_a_repository_is_not_checked(self):
        import kb_debts
        self.init_git()
        with patch.object(kb_debts, "tracked", return_value=None), \
                patch.object(kb_debts.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 10)):
            d = kb_debts.debts(str(self.root))
        self.assertEqual(d["code"]["status"], "NOT_CHECKED")

if __name__ == "__main__":
    unittest.main(verbosity=2)
