"""Interface en ligne de commande du pipeline de primes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .analyze import analyze_data, analyze_live, render_dossier
from .config import github_token, load_config, resolve
from .deliver import claim_line, export_patch, pr_body, pr_title, user_checklist
from .github import GitHubClient, GitHubError, ScopeError, search_available
from .models import CHECKPOINTS, Bounty, PipelineItem, Stage, VerifyResult
from .publication import Violation, check_branch, check_text
from .sources import (dedupe, discovery_plan, fetch_algora, import_results, prefilter, prescore,
                      search_github_api)
from .state import StateStore
from .track import check_item
from .workspace import (branch_name, clone_repo, create_branch, default_branch, detect_stack,
                        diff_summary, git, run, set_identity, write_brief)


def log(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except BrokenPipeError:  # sortie coupée (par ex. `| head`) : ne pas planter
        sys.stderr.close()
        raise SystemExit(0)


def _public_violations(ctx: "Ctx", item: PipelineItem, title: str, body: str) -> list[Violation]:
    """Règles de publication appliquées au titre, au corps et à la branche de travail."""
    words = ctx.cfg["publication"].get("mots_interdits", [])
    path = Path(item.workspace or "")
    base = item.base_branch or default_branch(path)
    return (check_text(title, "titre de la PR", words) + check_text(body, "corps de la PR", words)
            + check_branch(path, f"origin/{base}", words))


class Ctx:
    def __init__(self, args: argparse.Namespace):
        self.cfg = load_config(args.config)
        self.store = StateStore(resolve(self.cfg, self.cfg["workspace"]["etat"]))
        self.dossiers = resolve(self.cfg, self.cfg["workspace"]["dossiers"])
        self._client: GitHubClient | None = None

    @property
    def client(self) -> GitHubClient:
        if self._client is None:
            self._client = GitHubClient(token=github_token(self.cfg), api=self.cfg["github"]["api"])
        return self._client

    def write_dossier(self, item: PipelineItem) -> Path:
        self.dossiers.mkdir(parents=True, exist_ok=True)
        path = self.dossiers / f"{item.bounty.owner}__{item.bounty.repo}__{item.bounty.number}.md"
        path.write_text(render_dossier(item), encoding="utf-8")
        return path

    def item_dir(self, item: PipelineItem) -> Path:
        path = self.dossiers / f"{item.bounty.owner}__{item.bounty.repo}__{item.bounty.number}"
        path.mkdir(parents=True, exist_ok=True)
        return path


def _print_candidates(ctx: Ctx, bounties: list[Bounty], show_excluded: bool = False, top: int = 25) -> None:
    rows = []
    for b in bounties:
        reasons = prefilter(b, ctx.cfg)
        if reasons and not show_excluded:
            continue
        rows.append((b, reasons))
    rows.sort(key=lambda r: (-(r[0].prescore or 0), r[0].key))
    if not rows:
        log("(aucune candidate retenue)")
        return
    log("| Pré-score | Prime | Montant | Plateforme | Langage | Titre | Exclusion |")
    log("|---|---|---|---|---|---|---|")
    for b, reasons in rows[:top]:
        amount = f"{b.amount_usd:.0f} $" if b.amount_usd else "?"
        title = b.title[:60].replace("|", "/")
        log(f"| {b.prescore or 0} | {b.key} | {amount} | {b.platform} | {b.language or '?'} | {title} | "
            f"{'; '.join(reasons) or '-'} |")
    if len(rows) > top:
        log(f"... {len(rows) - top} autres (utiliser --top)")


def _ingest(ctx: Ctx, bounties: list[Bounty]) -> tuple[int, int, int]:
    kept = 0
    for b in bounties:
        b.prescore = prescore(b, ctx.cfg)
        if not prefilter(b, ctx.cfg):
            kept += 1
    added, updated = ctx.store.add_candidates(bounties)
    ctx.store.save()
    return added, updated, kept


# ----------------------------------------------------------------- commandes
def cmd_search(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    found: list[Bounty] = []
    ok, why = search_available(ctx.client)
    log(f"API GitHub : {why}")
    if ok:
        found += search_github_api(ctx.client, ctx.cfg, max_pages=args.pages, log=log)
        log(f"  {len(found)} issue(s) trouvée(s) via l'API GitHub")
    if not args.no_algora:
        try:
            algora = fetch_algora(ctx.cfg)
            log(f"  {len(algora)} prime(s) via l'API Algora")
            found += algora
        except Exception as exc:  # réseau restreint, schéma inconnu…
            log(f"  Algora indisponible : {exc.__class__.__name__}: {str(exc)[:120]}")
    found = dedupe(found)
    if found:
        added, updated, kept = _ingest(ctx, found)
        log(f"Candidates : {added} nouvelle(s), {updated} mise(s) à jour, {kept} retenue(s) après pré-filtre")
        _print_candidates(ctx, ctx.store.ranked_candidates(), show_excluded=args.all, top=args.top)
    plan_path = resolve(ctx.cfg, ".bounty/recherche_plan.md")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(discovery_plan(ctx.cfg), encoding="utf-8")
    if not ok:
        log("")
        log(discovery_plan(ctx.cfg))
        log(f"(plan enregistré dans {plan_path})")
        return 2
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    log(discovery_plan(ctx.cfg))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    bounties: list[Bounty] = []
    for file in args.files:
        text = Path(file).read_text(encoding="utf-8")
        parsed = import_results(text, source=args.source or f"import:{Path(file).name}", language=args.language)
        log(f"{file} : {len(parsed)} élément(s)")
        bounties += parsed
    bounties = dedupe(bounties)
    added, updated, kept = _ingest(ctx, bounties)
    log(f"Candidates : {added} nouvelle(s), {updated} mise(s) à jour, {kept} retenue(s) après pré-filtre")
    _print_candidates(ctx, bounties, show_excluded=args.all, top=args.top)
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    _print_candidates(ctx, ctx.store.ranked_candidates(), show_excluded=args.all, top=args.top)
    return 0


def _load_offline(directory: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in ("repo", "issue", "comments", "pulls", "root"):
        path = directory / f"{name}.json"
        if path.is_file():
            data[name] = json.loads(path.read_text(encoding="utf-8"))
    return data


def cmd_analyze(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    exit_code = 0
    for ref in args.refs:
        item = ctx.store.ensure_item(ref)
        b = item.bounty
        log(f"== {b.key}")
        try:
            if args.offline:
                data = _load_offline(Path(args.offline))
                root = [e.get("name", "") for e in data.get("root", [])] if isinstance(data.get("root"), list) else None
                issue = data.get("issue") or {}
                b.title = issue.get("title") or b.title
                b.body = (issue.get("body") or b.body or "")[:4000]
                b.created_at = issue.get("created_at") or b.created_at
                b.state = issue.get("state") or b.state
                b.language = (data.get("repo") or {}).get("language") or b.language
                analysis = analyze_data(b, ctx.cfg, data.get("repo"), issue, data.get("comments", []),
                                        data.get("pulls", []), None, root)
            else:
                analysis = analyze_live(ctx.client, b, ctx.cfg, log=log)
        except ScopeError as exc:
            log(f"  ! dépôt hors du périmètre de l'environnement : {exc.message}")
            log("    -> rendre le dépôt accessible puis relancer, ou fournir --offline DIR")
            exit_code = 2
            continue
        except GitHubError as exc:
            log(f"  ! {exc}")
            exit_code = 1
            continue
        item.analysis = analysis
        item.log(f"analyse : verdict {analysis.verdict} (score {analysis.score})", Stage.RECHERCHE)
        path = ctx.write_dossier(item)
        ctx.store.save()
        amount = f"{analysis.amount_usd:.0f} $" if analysis.amount_usd else "montant inconnu"
        log(f"  verdict {analysis.verdict} (score {analysis.score}/100), {amount}")
        for flag in analysis.red_flags:
            log(f"  ⚠ {flag}")
        for reason in analysis.reasons:
            log(f"  - {reason}")
        log(f"  dossier : {path}")
        log(f"  intervention attendue : {item.checkpoint}")
    return exit_code


def cmd_start(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    item = ctx.store.ensure_item(args.ref)
    if item.analysis is None and not args.force:
        log("Aucune analyse enregistrée : lance `analyze` d'abord (ou --force).")
        return 1
    if item.analysis and item.analysis.verdict == "NON" and not args.force:
        log(f"Verdict NON ({'; '.join(item.analysis.red_flags) or 'score trop bas'}) : utiliser --force pour passer outre.")
        return 1
    item.log(f"choix validé par l'utilisateur{(' : ' + args.note) if args.note else ''}")
    try:
        path = clone_repo(item.bounty, ctx.cfg, log=log)
        base = args.base or default_branch(path)
        branch = args.branch or branch_name(item.bounty)
        create_branch(path, branch, base)
        identity = set_identity(path, ctx.cfg["profil"].get("git_nom"), ctx.cfg["profil"].get("git_email"))
    except RuntimeError as exc:
        log(f"! {exc}")
        return 1
    if identity:
        log(f"Identité git du clone : {identity}")
    item.workspace = str(path)
    item.branch = branch
    item.base_branch = base
    item.stack = detect_stack(path)
    brief = write_brief(item, ctx.item_dir(item) / "TASK.md", ctx.cfg)
    item.log(f"espace de travail prêt : {path} (branche {branch} sur {base})", Stage.RESOLUTION)
    ctx.write_dossier(item)
    ctx.store.save()
    log(f"Espace de travail : {path}")
    log(f"Branche : {branch} (base {base})")
    log(f"Pile : {', '.join(item.stack.get('stack', [])) or '?'} ; tests : {item.stack.get('test')}")
    log(f"Brief : {brief}")
    log(f"Étape : {item.stage.value} ; intervention attendue : {item.checkpoint}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    item = ctx.store.require_item(args.ref)
    if not item.workspace:
        log("Pas d'espace de travail : lance `start` d'abord.")
        return 1
    path = Path(item.workspace)
    stack = item.stack or detect_stack(path)
    commands: list[str] = []
    if args.cmd:
        commands = list(args.cmd)
    else:
        if not args.skip_install:
            commands += stack.get("install", [])
        commands += stack.get("test", [])
        if not args.skip_lint:
            commands += stack.get("lint", [])
    if not commands:
        log("Aucune commande à exécuter : préciser --cmd.")
        return 1
    timeout = int(ctx.cfg["workspace"].get("timeout_tests_s", 1800))
    results: list[VerifyResult] = []
    for cmd in commands:
        log(f"$ {cmd}")
        result = run(cmd, path, timeout=timeout)
        results.append(result)
        log(f"  -> code {result.returncode} en {result.duration_s}s")
        if result.returncode != 0:
            log(result.output_tail[-1500:])
    item.verify_results = [r for r in item.verify_results if r.command not in commands] + results
    diff = diff_summary(path, item.base_branch or default_branch(path))
    ok = all(r.ok for r in results)
    item.log(f"vérification : {'succès' if ok else 'échec'} ({len(results)} commande(s))", Stage.VERIFICATION)
    report = ctx.item_dir(item) / "VERIFY.md"
    lines = [f"# Vérification : {item.bounty.key}", "", "| Commande | Code | Durée |", "|---|---|---|"]
    lines += [f"| `{r.command}` | {r.returncode} | {r.duration_s}s |" for r in results]
    lines += ["", "## Diff", "", "```", diff.get("stat") or "(aucun changement commité)", "```", ""]
    if diff.get("uncommitted"):
        lines.append("⚠️ Modifications non commitées présentes.")
    for r in results:
        lines += ["", f"## Sortie : `{r.command}`", "", "```", r.output_tail[-3000:], "```"]
    report.write_text("\n".join(lines), encoding="utf-8")
    ctx.write_dossier(item)
    ctx.store.save()
    log(f"Rapport : {report}")
    log(f"Diff : {len(diff.get('files', []))} fichier(s) ; commits : {len(diff.get('commits', []))}")
    log(f"Étape : {item.stage.value} ; intervention attendue : {item.checkpoint}")
    return 0 if ok else 1


def cmd_deliver(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    item = ctx.store.require_item(args.ref)
    if not item.workspace:
        log("Pas d'espace de travail : lance `start` puis `verify` d'abord.")
        return 1
    path = Path(item.workspace)
    base = item.base_branch or default_branch(path)
    diff = diff_summary(path, base)
    if not diff.get("commits"):
        log("Aucun commit sur la branche de travail : committer le correctif d'abord.")
        return 1
    summary = args.summary or ""
    approach = args.approach or ""
    testing = args.testing or ""
    title = pr_title(item, args.title)
    body = pr_body(item, ctx.cfg, summary, approach, testing, diff)
    out = ctx.item_dir(item)
    violations = _public_violations(ctx, item, title, body)
    (out / "PR.md").write_text(f"# {title}\n\n{body}", encoding="utf-8")
    (out / "PR_BODY.md").write_text(body, encoding="utf-8")
    (out / "CHECKLIST.md").write_text(user_checklist(item, ctx.cfg, diff, violations), encoding="utf-8")
    patch = export_patch(path, base, out)
    item.log(f"proposition préparée (PR.md, CHECKLIST.md, changes.patch) ; "
             f"{len(violations)} écart(s) aux règles de publication", Stage.LIVRAISON)
    ctx.write_dossier(item)
    ctx.store.save()
    log(f"Titre : {title}")
    log(f"PR : {out / 'PR.md'}")
    log(f"Checklist : {out / 'CHECKLIST.md'}")
    log(f"Patch : {patch}")
    claim = claim_line(item, ctx.cfg)
    if claim:
        log(f"Réclamation incluse : {claim}")
    if violations:
        log(f"Règles de publication : {len(violations)} écart(s) à corriger avant soumission")
        for violation in violations[:20]:
            log(f"  - {violation}")
    else:
        log("Règles de publication : aucun écart")
    log(f"Étape : {item.stage.value} ; intervention attendue : {item.checkpoint}")
    return 1 if violations else 0


def cmd_submit(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    item = ctx.store.require_item(args.ref)
    if item.stage != Stage.LIVRAISON and not args.force:
        log(f"L'étape courante est {item.stage.value} : lancer `deliver` d'abord (ou --force).")
        return 1
    if not args.yes:
        log("Soumission externe : ajouter --yes pour confirmer que l'utilisateur a validé la proposition.")
        return 1
    b = item.bounty
    path = Path(item.workspace or "")
    out = ctx.item_dir(item)
    pr_md = (out / "PR.md").read_text(encoding="utf-8")
    title, _, body = pr_md.partition("\n")
    title = title.lstrip("# ").strip()
    violations = _public_violations(ctx, item, title, body)
    if violations and not args.force:
        log(f"Soumission refusée : {len(violations)} écart(s) aux règles de publication (voir CHECKLIST.md).")
        for violation in violations[:20]:
            log(f"  - {violation}")
        return 1
    login = args.fork_owner or ctx.cfg["profil"].get("github_login") or ""
    try:
        if not login:
            login = ctx.client.me().get("login", "")
        if login.lower() != b.owner.lower():
            log(f"Fork vers {login}/{b.repo} …")
            ctx.client.fork(b.owner, b.repo)
            fork_url = f"https://github.com/{login}/{b.repo}.git"
            if "fork" not in git(["remote"], path).split():
                git(["remote", "add", "fork", fork_url], path)
            remote, head = "fork", f"{login}:{item.branch}"
        else:
            remote, head = "origin", item.branch or ""
        log(f"git push {remote} {item.branch}")
        git(["push", "-u", remote, item.branch or ""], path)
        pull = ctx.client.create_pull(b.owner, b.repo, title, head, item.base_branch or "main", body.strip(),
                                      draft=args.draft)
    except (GitHubError, RuntimeError) as exc:
        log(f"! soumission impossible : {exc}")
        log("  Alternative manuelle : pousser la branche sur votre fork et ouvrir la PR avec le contenu de PR.md.")
        return 1
    item.pr_url = pull.get("html_url")
    item.pr_number = pull.get("number")
    item.pr_state = "open"
    item.log(f"PR ouverte : {item.pr_url}", Stage.PAIEMENT)
    ctx.write_dossier(item)
    ctx.store.save()
    log(f"PR : {item.pr_url}")
    log(f"Étape : {item.stage.value} ; intervention attendue : {item.checkpoint}")
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    items = [ctx.store.require_item(args.ref)] if args.ref else ctx.store.active_items()
    code = 0
    for item in items:
        if item.stage not in (Stage.LIVRAISON, Stage.PAIEMENT) and not args.ref:
            continue
        try:
            report = check_item(ctx.client, item, log=log)
        except ScopeError as exc:
            log(f"{item.key} : hors périmètre ({exc.message})")
            code = 2
            continue
        log(f"{item.key} : {json.dumps(report, ensure_ascii=False)}")
        ctx.write_dossier(item)
    ctx.store.save()
    log("")
    log(ctx.store.table())
    return code


def cmd_status(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    log(ctx.store.table())
    pending = [(i.key, i.stage.value, i.checkpoint) for i in ctx.store.active_items() if i.checkpoint]
    if pending:
        log("")
        log("Interventions attendues :")
        for key, stage, checkpoint in pending:
            log(f"- {key} [{stage}] : {checkpoint}")
    log("")
    log(f"Candidates en attente d'analyse : {len(ctx.store.candidates)}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    item = ctx.store.require_item(args.ref)
    item.notes.append(args.text)
    item.log(f"note : {args.text}")
    ctx.write_dossier(item)
    ctx.store.save()
    return 0


def cmd_abandon(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    item = ctx.store.require_item(args.ref)
    item.log(f"abandon : {args.reason}", Stage.ABANDONNE)
    ctx.write_dossier(item)
    ctx.store.save()
    log(f"{item.key} abandonnée.")
    return 0


def cmd_controle(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    words = ctx.cfg["publication"].get("mots_interdits", [])
    violations = check_branch(Path(args.repo).resolve(), args.base, words)
    for file in args.fichier or []:
        violations += check_text(Path(file).read_text(encoding="utf-8"), file, words)
    for violation in violations:
        log(f"- {violation}")
    log(f"{len(violations)} écart(s) aux règles de publication "
        f"({len(words)} mot(s) proscrit(s) configuré(s))")
    return 1 if violations else 0


def cmd_config(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    cfg = {k: v for k, v in ctx.cfg.items() if not k.startswith("_")}
    log(f"fichier : {ctx.cfg.get('_path') or '(défauts)'} ; racine : {ctx.cfg['_root']}")
    log(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bounty", description="Pipeline de chasse aux primes open source.")
    p.add_argument("--config", help="chemin de bounty.toml (défaut : recherche vers le haut)")
    p.add_argument("--version", action="version", version=f"bounty {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="1. Recherche : repérer les primes (API GitHub, Algora)")
    s.add_argument("--pages", type=int, default=None)
    s.add_argument("--no-algora", action="store_true")
    s.add_argument("--all", action="store_true", help="afficher aussi les candidates exclues")
    s.add_argument("--top", type=int, default=25)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("plan", help="1. Recherche : afficher les URL à consulter quand l'API est inaccessible")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("import", help="1. Recherche : importer des résultats JSON (relevé d'une recherche)")
    s.add_argument("files", nargs="+")
    s.add_argument("--source")
    s.add_argument("--language")
    s.add_argument("--all", action="store_true")
    s.add_argument("--top", type=int, default=25)
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("candidates", help="1. Recherche : lister les candidates classées")
    s.add_argument("--all", action="store_true")
    s.add_argument("--top", type=int, default=25)
    s.set_defaults(func=cmd_candidates)

    s = sub.add_parser("analyze", help="1. Recherche : analyser une ou plusieurs issues (verdict, conditions)")
    s.add_argument("refs", nargs="+", help="URL d'issue ou owner/repo#n")
    s.add_argument("--offline", help="dossier contenant repo.json, issue.json, comments.json, pulls.json")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("start", help="2. Résolution : valider le choix, cloner, créer la branche et le brief")
    s.add_argument("ref")
    s.add_argument("--branch")
    s.add_argument("--base")
    s.add_argument("--note", help="note de l'utilisateur sur son choix")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("verify", help="3. Vérification : exécuter installation, tests et lint")
    s.add_argument("ref")
    s.add_argument("--cmd", action="append", help="commande explicite (répétable)")
    s.add_argument("--skip-install", action="store_true")
    s.add_argument("--skip-lint", action="store_true")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("deliver", help="4. Livraison : préparer PR.md, CHECKLIST.md et le patch")
    s.add_argument("ref")
    s.add_argument("--title")
    s.add_argument("--summary")
    s.add_argument("--approach")
    s.add_argument("--testing")
    s.set_defaults(func=cmd_deliver)

    s = sub.add_parser("submit", help="4. Livraison : fork, push et ouverture de la PR (après validation)")
    s.add_argument("ref")
    s.add_argument("--yes", action="store_true", help="l'utilisateur a validé la soumission")
    s.add_argument("--draft", action="store_true")
    s.add_argument("--fork-owner")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_submit)

    s = sub.add_parser("track", help="5. Paiement : suivre PR et paiement")
    s.add_argument("ref", nargs="?")
    s.set_defaults(func=cmd_track)

    s = sub.add_parser("status", help="Tableau du pipeline et interventions attendues")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("note", help="Ajouter une note (arbitrage, décision)")
    s.add_argument("ref")
    s.add_argument("text")
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("abandon", help="Retirer une prime du pipeline")
    s.add_argument("ref")
    s.add_argument("reason")
    s.set_defaults(func=cmd_abandon)

    s = sub.add_parser("controle", help="Contrôler les textes publics d'une branche (tirets, trailers, mots)")
    s.add_argument("--repo", default=".", help="dépôt à contrôler (défaut : dossier courant)")
    s.add_argument("--base", default="origin/main", help="référence de base (défaut : origin/main)")
    s.add_argument("--fichier", action="append", help="fichier texte à contrôler en plus (répétable)")
    s.set_defaults(func=cmd_controle)

    s = sub.add_parser("config", help="Afficher la configuration effective")
    s.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyError as exc:
        log(str(exc.args[0]) if exc.args else str(exc))
        return 1
    except ValueError as exc:
        log(f"Erreur : {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
