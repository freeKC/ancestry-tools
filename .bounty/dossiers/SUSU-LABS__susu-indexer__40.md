# Prime SUSU-LABS/susu-indexer#40

**[Bounty: $70] Replace the per-group N+1 updates in upsertGroupState**  
https://github.com/SUSU-LABS/susu-indexer/issues/40

| Champ | Valeur |
|---|---|
| Montant | 70 $ |
| Plateforme | inconnu |
| Langage | TypeScript |
| Étape | recherche |
| Intervention attendue | Choisir une tâche et vérifier ses conditions |
| Verdict | **NON** (score 0.0/100) |
| Âge de l'issue | 4.9 j |
| Concurrence | 3 réclamation(s), 4 PR ouverte(s), 0 fusionnée(s) |
| Dépôt | 27 étoiles, primes payées : ? |
| Tests | présents |

## Signaux d'alerte
- 3 personnes ont déjà réclamé la tâche (/attempt, /claim, PR)
- 4 PR ouvertes concurrentes

## Détail du score
- montant 70 $ (+3)
- 27 étoiles (+4)
- langage TypeScript dans le profil (+10)
- qualité de la spécification 4/10 (+4)
- suite de tests présente (+5)
- concurrence : 3 réclamation(s), 4 PR ouverte(s) (-90)

## Concurrents identifiés
fixwright, mumusama75, urielit1313-creator

## Conditions à respecter
- Acceptance criteria:

## Demande (extrait)

supabase/functions/_shared/db.ts (lines 345-371) awaits one UPDATE per group, using .eq('contract_id', ...) inside a for loop. Each update is a separate HTTP round trip, so runs that touch many groups pay extra latency and failure risk.

Proposed change: a single bulk write, such as an upsert with explicit columns, an RPC, or an UPDATE ... FROM (VALUES ...), while keeping the rule that zero updated rows is an error.

Acceptance criteria:
- Reconciling N groups uses O(1) DB round trips, not N.
- Reconciling a group with no groups row still fails loudly.
- Existing orchestration tests for group state writes still pass.

Suggested label: performance. ETA: 48 hours.

## Pipeline

| Étape | Travail automatisé | Intervention de l'utilisateur |
|---|---|---|
| ➡️ recherche | Repérer les primes et analyser les demandes | Choisir une tâche et vérifier ses conditions |
| resolution | Lire le code, reproduire le problème, programmer | Arbitrer les points ambigus |
| verification | Exécuter les tests et examiner les changements | Vérifier que le résultat répond à la demande |
| livraison | Préparer la proposition et son explication | Valider la soumission |
| paiement | Suivre le statut | Recevoir le paiement sur son compte |

## Historique
- 2026-10-14T04:48:18+00:00 [recherche] ajoutée au pipeline
- 2026-10-14T04:48:18+00:00 [recherche] analyse : verdict NON (score 0.0)
- 2026-10-14T04:54:01+00:00 [recherche] analyse : verdict NON (score 0.0)
- 2026-10-14T06:41:54+00:00 [recherche] analyse : verdict NON (score 0.0)
