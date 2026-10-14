"""Tests unitaires du pipeline de primes (bibliothèque standard uniquement).

Exécution : python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bounty.analyze import analyze_data, extract_conditions, render_dossier, spec_quality  # noqa: E402
from bounty.config import load_config  # noqa: E402
from bounty.deliver import claim_line, pr_body, pr_title, user_checklist  # noqa: E402
from bounty.models import Bounty, PipelineItem, Stage, parse_ref  # noqa: E402
from bounty.publication import check_branch, check_text  # noqa: E402
from bounty.sources import (build_queries, dedupe, import_results, parse_algora_payload, parse_amount,  # noqa: E402
                            prefilter, prescore)
from bounty.state import StateStore  # noqa: E402
from bounty.workspace import branch_name, create_branch, detect_stack, set_identity, slugify  # noqa: E402

EM, EN = "\u2014", "\u2013"


def iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(microsecond=0).isoformat()


def cfg() -> dict:
    return load_config(ROOT / "bounty.toml")


def git(args: list[str], cwd: Path, name: str = "Test", email: str = "test@example.com") -> str:
    proc = subprocess.run(["git", "-c", f"user.name={name}", "-c", f"user.email={email}", *args],
                          cwd=cwd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def init_repo(root: Path) -> Path:
    git(["init", "-q"], root)
    git(["checkout", "-q", "-b", "main"], root)
    (root / "base.txt").write_text(f"contenu amont {EM} déjà présent\n", encoding="utf-8")
    git(["add", "base.txt"], root)
    git(["commit", "-q", "-m", "base"], root)
    return root


class ParseTests(unittest.TestCase):
    def test_parse_amount_variants(self):
        self.assertEqual(parse_amount("## 💎 $50 bounty"), 50)
        self.assertEqual(parse_amount("/bounty $1.2k"), 1200)
        self.assertEqual(parse_amount("[Bounty: $70] fix"), 70)
        self.assertEqual(parse_amount("reward of 100 USD"), 100)
        self.assertEqual(parse_amount("$ 1,000 total"), 1000)
        self.assertEqual(parse_amount("was $50, now $100"), 100)
        self.assertIsNone(parse_amount("export $HOME and $PATH"))
        self.assertIsNone(parse_amount(""))

    def test_parse_ref(self):
        self.assertEqual(parse_ref("https://github.com/acme/widget/issues/42"), ("acme", "widget", 42))
        self.assertEqual(parse_ref("acme/widget#7"), ("acme", "widget", 7))
        with self.assertRaises(ValueError):
            parse_ref("https://github.com/acme/widget/pull/42")

    def test_import_results_from_copied_text(self):
        text = """Voici :
```json
[
  {"repo": "acme/widget", "number": 12, "title": "[Bounty: $70] fix paging", "labels": ["bounty"],
   "created": "3 hours ago", "amount": "$70", "snippet": "Pays $70 when merged"},
  {"issue_url": "https://github.com/acme/other/issues/3", "title": "no amount", "labels": "bug, help wanted"}
]
```
TOTAL: 2"""
        items = import_results(text, source="test")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].key, "acme/widget#12")
        self.assertEqual(items[0].amount_usd, 70)
        self.assertEqual(items[0].platform, "label")
        self.assertIn("créée : 3 hours ago", items[0].prescore_notes)
        self.assertEqual(items[1].key, "acme/other#3")
        self.assertEqual(items[1].labels, ["bug", "help wanted"])

    def test_parse_algora_payload(self):
        nested = {"items": [{"reward": {"amount": 5000}, "task": {"url": "https://github.com/acme/widget/issues/9"}}]}
        self.assertEqual(parse_algora_payload(nested), [])
        flat = {"items": [{"amount": 5000, "url": "https://github.com/acme/widget/issues/9", "title": "Fix it"}]}
        found = parse_algora_payload(flat)
        self.assertEqual(found[0].amount_usd, 50)
        self.assertEqual(found[0].platform, "algora")


class FilterTests(unittest.TestCase):
    def test_prefilter_excludes_traps(self):
        trap = Bounty("SecureBananaLabs", "bug-bounty", 1, title="x", amount_usd=780,
                      labels=["💎 Bounty", "Bots only, no humans"], created_at=iso(1))
        reasons = prefilter(trap, cfg())
        self.assertTrue(any("propriétaire exclu" in r for r in reasons))
        self.assertTrue(any("label exclu" in r for r in reasons))
        paid = Bounty("acme", "widget", 2, amount_usd=80, labels=["💰 Rewarded"], created_at=iso(1))
        self.assertTrue(any("label exclu (rewarded)" in r for r in prefilter(paid, cfg())))

    def test_prefilter_keeps_good_candidate(self):
        c = cfg()
        good = Bounty("acme", "widget", 2, title="fix", amount_usd=80, labels=["bounty"],
                      created_at=iso(2), language="Python")
        self.assertEqual(prefilter(good, c), [])
        stale = Bounty("acme", "widget", 3, amount_usd=80, created_at=iso(100), comments_count=40)
        self.assertGreater(prescore(good, c), prescore(stale, c))

    def test_prefilter_amount_and_age(self):
        reasons = prefilter(Bounty("acme", "widget", 4, amount_usd=5, created_at=iso(400)), cfg())
        self.assertTrue(any("montant trop bas" in r for r in reasons))
        self.assertTrue(any("trop ancienne" in r for r in reasons))

    def test_build_queries_and_dedupe(self):
        queries = build_queries(cfg())
        self.assertTrue(any('label:"💎 Bounty"' in q["q"] and "language:Python" in q["q"] for q in queries))
        a = Bounty("acme", "widget", 1, title="", amount_usd=None, labels=["bounty"])
        b = Bounty("acme", "widget", 1, title="Titre", amount_usd=50, labels=["💎 Bounty"])
        merged = dedupe([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "Titre")
        self.assertEqual(merged[0].amount_usd, 50)
        self.assertEqual(merged[0].labels, ["bounty", "💎 Bounty"])


def _comment(login: str, body: str, bot: bool = False) -> dict:
    return {"user": {"login": login, "type": "Bot" if bot else "User"}, "body": body, "created_at": iso(1)}


class AnalyzeTests(unittest.TestCase):
    def test_flooded_bounty_is_rejected(self):
        b = Bounty("acme", "widget", 8032, title="document instrumentation", platform="algora")
        issue = {"title": b.title, "body": "see thread", "state": "open", "created_at": iso(900),
                 "labels": [{"name": "💎 Bounty"}], "assignees": [], "comments": 60}
        comments = [_comment("algora-pbc[bot]", "## 💎 $20 bounty\n/claim #8032 in your PR", bot=True)]
        comments += [_comment(f"user{i}", "/attempt #8032") for i in range(6)]
        pulls = [{"number": n, "title": "fix #8032", "body": "", "state": "open"} for n in range(5)]
        pulls.append({"number": 99, "title": "docs", "body": "Fixes #8032", "state": "closed", "merged_at": iso(10)})
        a = analyze_data(b, cfg(), {"stargazers_count": 8000, "fork": False, "language": "TypeScript",
                                    "pushed_at": iso(1)}, issue, comments, pulls, rewarded_count=12,
                         root_entries=["tests", "package.json"])
        self.assertEqual(a.amount_usd, 20)
        self.assertTrue(a.bot_bounty_comment)
        self.assertEqual((a.claims, a.linked_prs_open, a.linked_prs_merged), (6, 5, 1))
        self.assertEqual(a.verdict, "NON")
        self.assertTrue(any("réclamé" in f for f in a.red_flags))
        self.assertTrue(any("/claim #8032" in cond for cond in a.conditions))

    def test_fresh_clean_bounty_is_go(self):
        b = Bounty("acme", "widget", 37, title="[Bounty: $80] Add stable ORDER BY", platform="label")
        body = ("## Problem\nPaging is unstable.\n\n## Acceptance criteria\n- [ ] Add ORDER BY id\n"
                "- [ ] Tests must cover paging\n\nSteps to reproduce: run the query twice. Expected: same order.\n"
                "```sql\nSELECT 1\n```\n")
        issue = {"title": b.title, "body": body, "state": "open", "created_at": iso(1),
                 "labels": [{"name": "bounty"}], "assignees": [], "comments": 0}
        a = analyze_data(b, cfg(), {"stargazers_count": 40, "fork": False, "language": "TypeScript",
                                    "pushed_at": iso(0.5)}, issue, [], [], rewarded_count=0,
                         root_entries=["package.json", "tests"])
        self.assertEqual(a.amount_usd, 80)
        self.assertEqual(a.red_flags, [])
        self.assertEqual(a.verdict, "GO", a.reasons)
        self.assertIn("Add ORDER BY id", a.conditions)

    def test_fork_and_assigned_are_red_flags(self):
        b = Bounty("someone", "qdrant-qdrant", 337, title="copied", amount_usd=500)
        issue = {"title": "copied", "body": "", "state": "open", "created_at": iso(5), "labels": [],
                 "assignees": [{"login": "x"}]}
        a = analyze_data(b, cfg(), {"fork": True, "stargazers_count": 0}, issue, [], [])
        self.assertEqual(a.verdict, "NON")
        self.assertTrue(any("fork" in f for f in a.red_flags))
        self.assertTrue(any("assignée" in f for f in a.red_flags))

    def test_spec_quality_and_conditions(self):
        self.assertEqual(spec_quality(""), 0)
        self.assertGreaterEqual(spec_quality("x" * 700 + " steps to reproduce expected ```code```"), 6)
        conds = extract_conditions("- [ ] must add tests\nThe PR should include docs.", [], "opire", 5)
        self.assertIn("must add tests", conds)
        self.assertTrue(any("should include docs" in c for c in conds))


class PublicationTests(unittest.TestCase):
    def test_dashes_trailers_and_words(self):
        text = (f"Titre propre\nUne phrase {EM} avec tiret\nPlage 1{EN}2\n"
                "Co-authored-by: Quelqu'un <a@b.c>\nLe mot TOTO ici\nen minuscules toto passe")
        found = check_text(text, "corps", ["TOTO"])
        rules = [(v.where, v.rule) for v in found]
        self.assertEqual(rules, [
            ("corps, ligne 2", "tiret cadratin"),
            ("corps, ligne 3", "tiret demi-cadratin"),
            ("corps, ligne 4", "trailer de co-auteur"),
            ("corps, ligne 5", "mot proscrit « TOTO »"),
        ])
        self.assertEqual(check_text("Texte conforme - avec trait d'union", "x", ["TOTO"]), [])

    def test_word_boundaries_and_case(self):
        self.assertEqual(len(check_text("Toto.", "x", ["toto"])), 1)
        self.assertEqual(check_text("totoro xtoto", "x", ["toto"]), [])

    def test_check_branch_covers_identity_message_and_added_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            git(["checkout", "-q", "-b", "feature"], repo)
            (repo / "a.txt").write_text(f"ligne propre\nligne {EM} fautive\n", encoding="utf-8")
            (repo / "data.patch").write_text(f"+contexte tiers {EM} cité\n", encoding="utf-8")
            git(["add", "a.txt", "data.patch"], repo)
            git(["commit", "-q", "-m", "feat: ajout\n\nCo-authored-by: Robot <r@example.com>"], repo,
                name="Toto", email="toto@example.com")
            found = check_branch(repo, "main", ["Toto"])
            rules = sorted((v.where.split(",")[0], v.rule) for v in found)
            sha = git(["rev-parse", "--short", "HEAD"], repo)
            self.assertIn((f"auteur du commit {sha}", "mot proscrit « Toto »"), rules)
            self.assertIn((f"committer du commit {sha}", "mot proscrit « Toto »"), rules)
            self.assertIn((f"message du commit {sha}", "trailer de co-auteur"), rules)
            self.assertIn(("a.txt:2", "tiret cadratin"), rules)
            self.assertFalse(any(where.startswith("data.patch") or where.startswith("base.txt")
                                 for where, _ in rules))

    def test_clean_branch_has_no_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            git(["checkout", "-q", "-b", "feature"], repo)
            (repo / "a.txt").write_text("ligne propre\n", encoding="utf-8")
            git(["add", "a.txt"], repo)
            git(["commit", "-q", "-m", "fix: correction"], repo, name="Dev", email="dev@example.com")
            self.assertEqual(check_branch(repo, "main", ["Toto"]), [])


class ConfigTests(unittest.TestCase):
    def test_local_file_overrides_and_extends(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bounty.toml").write_text('[profil]\nlangages = ["Python"]\nmontant_min = 30\n',
                                              encoding="utf-8")
            (root / "bounty.local.toml").write_text(
                '[profil]\ngit_nom = "Dev"\n[publication]\nmots_interdits = ["toto"]\n', encoding="utf-8")
            loaded = load_config(root / "bounty.toml")
            self.assertEqual(loaded["profil"]["langages"], ["Python"])
            self.assertEqual(loaded["profil"]["montant_min"], 30)
            self.assertEqual(loaded["profil"]["git_nom"], "Dev")
            self.assertEqual(loaded["publication"]["mots_interdits"], ["toto"])
            self.assertEqual(loaded["profil"]["claims_max"], 2)  # valeur par défaut conservée


class StateAndDeliveryTests(unittest.TestCase):
    def test_state_roundtrip_and_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            store.add_candidates([Bounty("acme", "widget", 1, title="Fix", amount_usd=70, labels=["bounty"],
                                         prescore=55)])
            item = store.ensure_item("acme/widget#1")
            item.log("choix", Stage.RESOLUTION)
            item.notes.append("arbitrage : option A")
            store.save()
            again = StateStore(Path(tmp) / "state.json")
            loaded = again.require_item("https://github.com/acme/widget/issues/1")
            self.assertEqual(loaded.stage, Stage.RESOLUTION)
            self.assertEqual(loaded.notes, ["arbitrage : option A"])
            self.assertEqual(loaded.checkpoint, "Arbitrer les points ambigus")
            self.assertIn("acme/widget#1", again.table())
            with self.assertRaises(KeyError):
                again.require_item("acme/widget#2")

    def test_pr_title_body_and_checklist(self):
        c = cfg()
        item = PipelineItem(bounty=Bounty("acme", "widget", 12, title="Paging returns duplicates", labels=["bug"],
                                          platform="algora"))
        self.assertEqual(pr_title(item), "fix: paging returns duplicates")
        feat = PipelineItem(bounty=Bounty("acme", "widget", 13, title="Add JSON output", labels=["enhancement"]))
        self.assertTrue(pr_title(feat).startswith("feat:"))
        self.assertEqual(claim_line(item, c), "/claim #12")
        body = pr_body(item, c, "Fixes duplicate rows.", "Added ORDER BY.", "Ran the suite.",
                       {"files": ["src/db.ts"], "stat": "1 file changed"})
        self.assertIn("Fixes #12", body)
        self.assertIn("/claim #12", body)
        self.assertEqual(check_text(body, "corps"), [])
        diff = {"stat": "1 file changed", "commits": ["abc fix"], "uncommitted": False}
        clean = user_checklist(item, c, diff, [])
        self.assertIn("Valider la soumission", clean)
        self.assertIn("aucun écart", clean)
        flagged = user_checklist(item, c, diff, check_text(f"a {EM} b", "corps"))
        self.assertIn("écarts à corriger", flagged)

    def test_render_dossier_contains_pipeline_table(self):
        text = render_dossier(PipelineItem(bounty=Bounty("acme", "widget", 5, title="Something", body="corps")))
        self.assertIn("Choisir une tâche et vérifier ses conditions", text)
        self.assertIn("Travail automatisé", text)
        self.assertIn("➡️ recherche", text)


class WorkspaceTests(unittest.TestCase):
    def test_slug_and_branch(self):
        self.assertEqual(slugify("Add --json output format!"), "add-json-output-format")
        self.assertEqual(branch_name(Bounty("a", "b", 7, title="Fix: Crash when config missing")),
                         "bounty/7-fix-crash-when-config-missing")

    def test_detect_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (root / "tests").mkdir()
            stack = detect_stack(root)
            self.assertIn("python", stack["stack"])
            self.assertIn("python -m pytest -q", stack["test"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "typecheck": "tsc"}}),
                                               encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            stack = detect_stack(root)
            self.assertIn("node/pnpm", stack["stack"])
            self.assertIn("pnpm run typecheck", stack["lint"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "deno.json").write_text(json.dumps({"tasks": {"check": "deno check x.ts", "lint": "deno lint",
                                                                   "test": "deno test tests/"}}), encoding="utf-8")
            stack = detect_stack(root)
            self.assertEqual(stack["stack"], ["deno"])
            self.assertEqual(stack["test"], ["deno task test"])
            self.assertEqual(stack["lint"], ["deno task check", "deno task lint"])
        with tempfile.TemporaryDirectory() as tmp:
            stack = detect_stack(Path(tmp))
            self.assertEqual(stack["stack"], [])
            self.assertTrue(stack["notes"])

    def test_create_branch_keeps_existing_work_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            base = git(["rev-parse", "HEAD"], repo)
            git(["update-ref", "refs/remotes/origin/main", base], repo)
            create_branch(repo, "feature", "main")
            (repo / "travail.txt").write_text("en cours\n", encoding="utf-8")
            git(["add", "travail.txt"], repo)
            git(["commit", "-q", "-m", "travail"], repo)
            work = git(["rev-parse", "HEAD"], repo)
            git(["checkout", "-q", "main"], repo)
            create_branch(repo, "feature", "main")  # reprise : ne doit pas revenir à origin/main
            self.assertEqual(git(["rev-parse", "HEAD"], repo), work)
            self.assertEqual(set_identity(repo, "Dev", "dev@example.com"), "Dev <dev@example.com>")
            self.assertIsNone(set_identity(repo, "", ""))


class CliTests(unittest.TestCase):
    def test_import_and_status_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bounty.toml").write_text('[profil]\nlangages = ["Python"]\n', encoding="utf-8")
            data = root / "results.json"
            data.write_text(json.dumps([
                {"repo": "acme/widget", "number": 1, "title": "[Bounty: $70] fix", "labels": ["bounty"],
                 "amount": "$70", "created_at": iso(1), "language": "Python"},
                {"repo": "SecureBananaLabs/bug-bounty", "number": 2, "title": "trap", "labels": ["💎 Bounty"],
                 "amount": "$780"},
            ]), encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(ROOT))
            base = [sys.executable, "-m", "bounty", "--config", str(root / "bounty.toml")]
            out = subprocess.run(base + ["import", str(data), "--all"], cwd=tmp, capture_output=True, text=True,
                                 env=env)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("acme/widget#1", out.stdout)
            self.assertIn("propriétaire exclu", out.stdout)
            status = subprocess.run(base + ["status"], cwd=tmp, capture_output=True, text=True, env=env)
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            self.assertIn("Candidates en attente d'analyse : 2", status.stdout)


if __name__ == "__main__":
    unittest.main()
