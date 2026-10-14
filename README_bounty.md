# Pipeline de chasse aux primes open source

`python -m bounty` automatise la chasse aux primes (bounties) attachées à des issues GitHub. Le
pipeline fait le travail répétitif ; l'utilisateur garde cinq décisions.

| Étape | Travail automatisé | Intervention de l'utilisateur |
|---|---|---|
| Recherche | Repérer les primes et analyser les demandes | Choisir une tâche et vérifier ses conditions |
| Résolution | Lire le code, reproduire le problème, programmer | Arbitrer les points ambigus |
| Vérification | Exécuter les tests et examiner les changements | Vérifier que le résultat répond à la demande |
| Livraison | Préparer la proposition et son explication | Valider la soumission |
| Paiement | Suivre le statut | Recevoir le paiement sur son compte |

## Installation

Python 3.11 ou plus récent (bibliothèque standard ; avant 3.11, installer `toml`) et git.

```bash
python -m bounty --help
python -m unittest discover -s tests -v
```

`bounty.toml` porte le profil (langages, montants, concurrence tolérée) et les filtres de dépôts
pièges. `bounty.local.toml`, non versionné, porte les réglages personnels : identité git
(`[profil] git_nom`, `git_email`) et mots proscrits (`[publication] mots_interdits`). Un jeton
GitHub dans `GITHUB_TOKEN` active la recherche API, le suivi et la soumission ; l'outil ne l'affiche
ni ne l'écrit jamais.

## Commandes

| Étape | Commande | Effet |
|---|---|---|
| 1 | `search` | Recherche API GitHub (labels de prime) et API Algora, classement des candidates. |
| 1 | `plan`, `import FICHIER` | Sans accès API : URL de recherche à relever, puis import du relevé JSON. |
| 1 | `candidates` | Candidates classées par pré-score, avec motifs d'exclusion. |
| 1 | `analyze URL` | Montant confirmé, concurrence (`/attempt`, `/claim`, PR liées), santé du dépôt, conditions, verdict GO, PRUDENCE ou NON. `--offline DIR` lit des JSON déjà relevés. |
| 2 | `start URL` | Clone, branche, identité git du clone, détection de la pile, brief `TASK.md`. Reprend une branche existante sans la réinitialiser. |
| 3 | `verify URL` | Installation, tests et lint détectés (ou `--cmd`), rapport `VERIFY.md`. |
| 4 | `deliver URL` | `PR.md`, `PR_BODY.md`, `CHECKLIST.md`, `changes.patch` et contrôle des règles de publication. |
| 4 | `submit URL --yes` | Fork, poussée, ouverture de la PR ; refusé tant qu'un écart aux règles subsiste. |
| 5 | `track` | État des PR et détection du paiement. |
| | `controle`, `status`, `note`, `abandon`, `config` | Contrôle d'une branche quelconque, tableau de bord, notes d'arbitrage, abandon, configuration. |

## Règles de publication

`deliver`, `submit` et `controle` vérifient tout texte public : titre et corps de PR, identité et
message de chaque commit, lignes ajoutées au dépôt cible.

- Aucun tiret cadratin ni demi-cadratin.
- Aucun trailer de co-auteur.
- Aucun mot de `mots_interdits`.

Les correctifs exportés (`.patch`), qui citent du contenu tiers, ne sont pas contrôlés.

## Verdict de l'analyse

Score de 0 à 100. Un signal d'alerte impose NON quel que soit le score : issue fermée ou assignée,
dépôt fork ou archivé, PR déjà fusionnée, trop de réclamations ou de PR concurrentes, montant
introuvable, label exclu. Le score monte avec le montant, la confirmation par un bot de plateforme,
les primes déjà payées par le dépôt, les étoiles, le langage du profil, la qualité de la
spécification, la présence de tests et la fraîcheur de l'issue. Il baisse avec la concurrence, l'âge
et l'inactivité du dépôt.

## Constats sur les plateformes (13 et 14 octobre 2026)

- Algora : le mainteneur commente `/bounty $X`, la PR doit contenir `/claim #n`, paiement après
  fusion via un compte Algora relié à GitHub et à Stripe. Aucune issue créée depuis septembre 2026
  ne porte le label `💎 Bounty` : la liste à jour se consulte sur algora.io.
- Beaucoup de bruit sur GitHub : dépôts à milliers d'« issues à prime » jamais payées, forks avec
  labels copiés, dépôts de démonstration. Ils sont filtrés par `bounty.toml`.
- Concurrence : une prime visible depuis quelques jours attire 5 à 30 PR. Les primes gagnables sont
  publiées depuis moins de 48 h, bien spécifiées, dans un dépôt qui a déjà payé.

## Première prime : SUSU-LABS/susu-indexer#45 (70 $)

| Étape | Résultat |
|---|---|
| Recherche | Analyses de #45 et #40 : 70 $ chacune, 4 à 5 PR concurrentes, conditions de paiement non écrites. |
| Résolution | Deux commits : CI de nouveau verte sur `main`, puis le correctif (les deux sources de dérive du start ledger, signalées dans les logs et la réponse, section du runbook). |
| Vérification | Format, lint, typage et 234 tests verts, dont 10 nouveaux, y compris avec la commande du workflow CI. |
| Livraison | `.bounty/dossiers/SUSU-LABS__susu-indexer__45/` : `soumettre.py` (fork, poussée et PR en une commande), `changes.patch`, `PR_BODY.md`, `SUBMIT.md`. |
| Paiement | En attente de la soumission puis de la fusion. |
