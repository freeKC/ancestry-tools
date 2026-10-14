# Prime SUSU-LABS/susu-indexer#45

**[Bounty: $70] Stop silently skipping ledgers when INDEXER_START_LEDGER is raised**  
https://github.com/SUSU-LABS/susu-indexer/issues/45

| Champ | Valeur |
|---|---|
| Montant | 70 $ |
| Plateforme | inconnu |
| Langage | TypeScript |
| Étape | livraison |
| Intervention attendue | Valider la soumission |
| Verdict | **NON** (score 0.0/100) |
| Âge de l'issue | 4.8 j |
| Concurrence | 3 réclamation(s), 5 PR ouverte(s), 0 fusionnée(s) |
| Dépôt | 27 étoiles, primes payées : ? |
| Tests | présents |

## Signaux d'alerte
- 3 personnes ont déjà réclamé la tâche (/attempt, /claim, PR)
- 5 PR ouvertes concurrentes

## Détail du score
- montant 70 $ (+3)
- 27 étoiles (+4)
- langage TypeScript dans le profil (+10)
- qualité de la spécification 4/10 (+4)
- suite de tests présente (+5)
- concurrence : 3 réclamation(s), 5 PR ouverte(s) (-105)

## Concurrents identifiés
fixwright, Ljunqiang, urielit1313-creator

## Conditions à respecter
- Acceptance criteria:

## Demande (extrait)

Context: In supabase/functions/_shared/checkpoint.ts (lines 68-70), the start ledger is computed as max(lastProcessedLedger + 1, startLedger). Once a checkpoint exists, raising INDEXER_START_LEDGER (or indexer_checkpoints.start_ledger) moves the starting point forward and skips every ledger in between. This happens with no log, warning, or alert, leaving a permanent, invisible gap.

Proposed change: Use startLedger only when no checkpoint exists. When a checkpoint exists and startLedger is more than one ahead of it, ignore startLedger, or fail and log a warning and raise an alert.

Acceptance criteria:
- With a checkpoint present, computeLedgerRange never advances past lastProcessedLedger + 1 because of a higher startLedger.
- A test covers a raised startLedger and asserts a warning or failure instead of a silent skip.
- The documented rebuild procedure still works.

Suggested label: correctness. ETA: 48 hours.

## Pipeline

| Étape | Travail automatisé | Intervention de l'utilisateur |
|---|---|---|
| recherche | Repérer les primes et analyser les demandes | Choisir une tâche et vérifier ses conditions |
| resolution | Lire le code, reproduire le problème, programmer | Arbitrer les points ambigus |
| verification | Exécuter les tests et examiner les changements | Vérifier que le résultat répond à la demande |
| ➡️ livraison | Préparer la proposition et son explication | Valider la soumission |
| paiement | Suivre le statut | Recevoir le paiement sur son compte |

## Historique
- 2026-10-14T04:48:18+00:00 [recherche] ajoutée au pipeline
- 2026-10-14T04:48:18+00:00 [recherche] analyse : verdict NON (score 0.0)
- 2026-10-14T04:52:18+00:00 [recherche] choix validé par l'utilisateur : L'utilisateur a délégué le choix (message du 14/10) : prime la moins disputée parmi celles visibles, test de bout en bout du pipeline
- 2026-10-14T04:52:19+00:00 [resolution] espace de travail prêt : /home/user/ancestry-tools/.bounty/work/SUSU-LABS__susu-indexer (branche bounty/45-tache sur main)
- 2026-10-14T04:54:01+00:00 [recherche] analyse : verdict NON (score 0.0)
- 2026-10-14T04:54:02+00:00 [recherche] choix validé par l'utilisateur : Branche renommée après correction du titre hors ligne
- 2026-10-14T04:54:02+00:00 [resolution] espace de travail prêt : /home/user/ancestry-tools/.bounty/work/SUSU-LABS__susu-indexer (branche bounty/45-bounty-70-stop-silently-skipping-ledgers sur main)
- 2026-10-14T04:59:32+00:00 [verification] vérification : échec (4 commande(s))
- 2026-10-14T05:00:47+00:00 [verification] vérification : succès (4 commande(s))
- 2026-10-14T05:01:07+00:00 [verification] note : Arbitrage 1 : ignorer le start ledger et avertir plutôt qu'échouer (option explicitement offerte par l'issue ; échouer stopperait l'indexation et ferait croître le retard).
- 2026-10-14T05:01:07+00:00 [verification] note : Arbitrage 2 : 'raise an alert' rendu par un avertissement structuré dans les logs et un champ warnings dans la réponse, sans nouvelle migration (CONTRIBUTING : toute migration RLS exige une revue préalable des mainteneurs).
- 2026-10-14T05:01:07+00:00 [verification] note : Arbitrage 3 : les deux sources sont contrôlées (colonne indexer_checkpoints.start_ledger, qui causait réellement le saut, et INDEXER_START_LEDGER, ignorée en silence) ; aucune PR concurrente ne couvre les deux.
- 2026-10-14T05:01:07+00:00 [verification] note : Commit préalable séparé : CI verte sur main (fmt des SVG exclus, imports inutilisés, stub rpc), car tous les checks échouaient sur main et donc sur chaque PR.
- 2026-10-14T05:01:56+00:00 [livraison] proposition préparée (PR.md, CHECKLIST.md, changes.patch)
- 2026-10-14T06:41:54+00:00 [verification] vérification : succès (4 commande(s))
- 2026-10-14T06:41:54+00:00 [livraison] proposition préparée (PR.md, CHECKLIST.md, changes.patch) ; 0 écart(s) aux règles de publication
