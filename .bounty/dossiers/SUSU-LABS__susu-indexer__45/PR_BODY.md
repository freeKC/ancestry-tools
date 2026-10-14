## Summary

Once a checkpoint exists, a start ledger raised above it moved the next range forward and silently skipped every ledger in between (`max(last_processed_ledger + 1, start_ledger)` in `computeLedgerRange`). The range now always resumes at `last_processed_ledger + 1`, and the start ledger is honoured on a first run only. A raised start ledger is reported instead of silently dropped, and the documented rebuild keeps working without a warning.

## Approach

- `computeLedgerRange` no longer consults `startLedger` when a checkpoint exists.
- `startLedgerGap` (pure, in `checkpoint.ts`) classifies a start ledger against the checkpoint: `null` on a first run, for the rebuild (`last_processed_ledger = start_ledger - 1`) and for a lower value; otherwise the exact ledgers that would have been skipped.
- `startLedgerWarnings` in the handler checks both places an operator can raise the value, because they failed differently: `indexer_checkpoints.start_ledger` is what actually moved the range, while `INDEXER_START_LEDGER` is not consulted once a checkpoint exists, so raising it had no effect at all. Each source that is ahead is logged with structured fields (`source`, `startLedger`, `lastProcessedLedger`, `resumeFrom`, `skippedFrom`, `skippedTo`) and returned in a `warnings` array of the run response, on every run until it agrees with the checkpoint again. No migration is needed: the log and the response carry the alert.
- `docs/RUNBOOK.md` gains "Raising the start ledger does not skip ledgers", and the README operations list gets one bullet.
- The first commit makes CI green on `main`. `deno fmt --check` failed on the vendored Font Awesome SVGs (now excluded like `assets/`), `deno lint` failed on two imports left over from #39, three orchestration tests lacked the `derive_group_state` RPC stub and the skip path write from #44, and the workflow ran the tests with `--allow-env` only, so the PGlite suites could not read their data files. The workflow now runs `deno task test`, as CONTRIBUTING.md documents. This overlaps with #81 and can be dropped if that lands first.

## Files changed

- `.github/workflows/ci.yml`
- `.vscode/extensions.json`
- `.vscode/launch.json`
- `.vscode/tasks.json`
- `README.md`
- `deno.json`
- `docs/RUNBOOK.md`
- `supabase/functions/_shared/checkpoint.ts`
- `supabase/functions/indexer/index.ts`
- `tests/checkpoint_test.ts`
- `tests/indexer_orchestration_test.ts`

## Testing

`deno fmt --check`, `deno lint`, `deno check supabase/functions/indexer/index.ts` and `deno task test` all pass: 234 tests, 10 of them new.

- Unit: a raised start ledger never moves the range, a caught-up indexer stays caught up, and the gap classifier handles a first run, the rebuild, a lower value and a one-ledger gap.
- Handler: `start_ledger` raised in the checkpoint row (resumes at `last_processed_ledger + 1`, names the skipped ledgers and the runbook, still advances to the head), a raised `INDEXER_START_LEDGER`, the rebuild (no `warnings` field), the caught-up path (still reports), and `startLedgerWarnings` naming each raised source once.

| Check | Result | Duration |
|---|---|---|
| `deno task test` | ✅ pass | 55.6s |
| `deno task check` | ✅ pass | 1.9s |
| `deno task fmt:check` | ✅ pass | 0.0s |
| `deno task lint` | ✅ pass | 0.1s |

Fixes #45
