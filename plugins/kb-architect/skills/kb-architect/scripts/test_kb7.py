#!/usr/bin/env python3
"""Observed 6.x failures and 7.0 heterogeneous-project contracts, in isolation."""

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import kb_due
import kb_index
import kb_lookup
import kb_paths
import kb_skills

HERE = Path(__file__).resolve().parent


class RedesignTests(unittest.TestCase):
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
        self.assertIn("НЕ СЛИТО В КАНОН", output.stdout)
        self.assertNotIn("СОДЕРЖИМОЕ УЖЕ В КАНОНЕ", output.stdout)
        result = self.run_tool("kb_lookup.py", "--finalize", receipt, "--outcome", "supported",
                               "--supports", "c1", "--reason", "old state only")
        self.assertEqual(result.returncode, 2)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
