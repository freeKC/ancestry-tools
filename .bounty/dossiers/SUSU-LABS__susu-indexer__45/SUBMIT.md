# Soumission de la PR pour SUSU-LABS/susu-indexer#45 (70 $)

Le correctif est prêt et vérifié : format, lint, typage et 234 tests verts, y compris avec la
commande de tests du workflow CI du dépôt.

## Une commande

Depuis ce dossier, sur un poste avec Python 3 et git :

```bash
python3 soumettre.py --jeton CHEMIN_DU_FICHIER_JETON
```

Le script crée le fork `freeKC/susu-indexer` (ou réutilise celui qui existe), clone le dépôt amont,
applique `changes.patch`, pousse la branche `fix/45-start-ledger-above-checkpoint` sur le fork,
ouvre la PR avec `PR_BODY.md` et affiche son URL.

Options : `--tests` lance la suite Deno avant la poussée, `--brouillon` ouvre la PR en brouillon,
`--commenter` signale la PR sur l'issue, `--simulation` fait tout sauf le fork, la poussée et la PR.

Le jeton est lu dans le fichier indiqué (ou dans `GITHUB_TOKEN`). Il n'est jamais affiché, jamais
écrit sur disque, jamais passé en argument : git le reçoit par variable d'environnement, avec les
gestionnaires d'identifiants désactivés.

## Ensuite

- Paiement : l'issue ne précise ni devise ni moyen de paiement. Les 15 primes déjà closes de ce dépôt
  l'ont été par des PR fusionnées, sans échange public sur le règlement. Répondre aux mainteneurs
  (GEEKYFOCUS, salienne) avec les coordonnées de paiement quand ils les demandent.
- Concurrence au 14 octobre 2026 : PR #60, #74, #83, #102 et #120 ouvertes sur la même issue, aucune
  fusion dans le dépôt depuis le 9 octobre. Aucune ne traite les deux sources de dérive ni ne rend la
  CI verte.
- Suivi : `python -m bounty track SUSU-LABS/susu-indexer#45` avec un jeton dans `GITHUB_TOKEN`.
