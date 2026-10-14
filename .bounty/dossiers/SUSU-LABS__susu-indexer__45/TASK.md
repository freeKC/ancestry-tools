# Brief de résolution : SUSU-LABS/susu-indexer#45

Issue : https://github.com/SUSU-LABS/susu-indexer/issues/45
Titre : [Bounty: $70] Stop silently skipping ledgers when INDEXER_START_LEDGER is raised
Montant : 70 $
Plateforme : inconnu
Branche : bounty/45-bounty-70-stop-silently-skipping-ledgers (base : main)

## Règles
- Lire d'abord CONTRIBUTING / README / les tests existants du dépôt.
- Reproduire le problème avant de corriger (test qui échoue, puis qui passe).
- Diff minimal, dans le style du dépôt ; pas de changement hors périmètre.
- Ajouter ou adapter des tests ; ne jamais désactiver un test.
- Noter chaque point ambigu dans `.bounty/dossiers/<clé>.md` (section Arbitrages) et
  s'arrêter pour demander à l'utilisateur quand une interprétation change le résultat.

## Conditions relevées
- Acceptance criteria:

## Pile technique détectée
- stack : deno
- tests : `deno task test`
- lint : `deno task check`
- lint : `deno task fmt:check`
- lint : `deno task lint`

## Demande complète

Context: In supabase/functions/_shared/checkpoint.ts (lines 68-70), the start ledger is computed as max(lastProcessedLedger + 1, startLedger). Once a checkpoint exists, raising INDEXER_START_LEDGER (or indexer_checkpoints.start_ledger) moves the starting point forward and skips every ledger in between. This happens with no log, warning, or alert, leaving a permanent, invisible gap.

Proposed change: Use startLedger only when no checkpoint exists. When a checkpoint exists and startLedger is more than one ahead of it, ignore startLedger, or fail and log a warning and raise an alert.

Acceptance criteria:
- With a checkpoint present, computeLedgerRange never advances past lastProcessedLedger + 1 because of a higher startLedger.
- A test covers a raised startLedger and asserts a warning or failure instead of a silent skip.
- The documented rebuild procedure still works.

Suggested label: correctness. ETA: 48 hours.
