# Validation de la soumission : SUSU-LABS/susu-indexer#45

À vérifier avant `python -m bounty submit` :

- [ ] L'issue https://github.com/SUSU-LABS/susu-indexer/issues/45 est toujours ouverte et la prime toujours affichée.
- [ ] Aucune PR concurrente n'a été fusionnée entre-temps.
- [ ] Le diff ne touche que le périmètre de l'issue (voir ci-dessous).
- [ ] Les tests passent (tableau des vérifications dans PR.md).
- [ ] Les règles de contribution du dépôt (CONTRIBUTING) sont respectées.
- [x] Règles de publication : aucun écart (tirets longs, trailers, mots proscrits).
- [ ] Condition : Acceptance criteria:

## Diff

```
.github/workflows/ci.yml                 |   2 +-
 .vscode/extensions.json                  |  12 +--
 .vscode/launch.json                      |  27 +++--
 .vscode/tasks.json                       |   4 +-
 README.md                                |   4 +
 deno.json                                |   2 +-
 docs/RUNBOOK.md                          |  16 +++
 supabase/functions/_shared/checkpoint.ts |  49 ++++++++-
 supabase/functions/indexer/index.ts      |  81 ++++++++++++++-
 tests/checkpoint_test.ts                 |  54 ++++++++++
 tests/indexer_orchestration_test.ts      | 170 ++++++++++++++++++++++++++++++-
 11 files changed, 397 insertions(+), 24 deletions(-)
```

Commits :
- a392bac fix(indexer): never let a raised start ledger skip past the checkpoint
- aea3fa8 chore(ci): make format, lint, typecheck and tests pass on main

⚠️ Des modifications ne sont pas commitées dans l'espace de travail.

Intervention attendue : **Valider la soumission** (`python -m bounty submit <clé>`).