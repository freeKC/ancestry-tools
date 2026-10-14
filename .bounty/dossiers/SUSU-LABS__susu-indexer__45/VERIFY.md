# Vérification : SUSU-LABS/susu-indexer#45

| Commande | Code | Durée |
|---|---|---|
| `deno task test` | 0 | 55.6s |
| `deno task check` | 0 | 1.9s |
| `deno task fmt:check` | 0 | 0.0s |
| `deno task lint` | 0 | 0.1s |

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

⚠️ Modifications non commitées présentes.

## Sortie : `deno task test`

```
 [0m[32mok[0m [0m[38;5;245m(283µs)[0m
chunks an evenly divisible watch list without an empty trailing request ... [0m[32mok[0m [0m[38;5;245m(233µs)[0m
sends one request when the watch list fits the limit ... [0m[32mok[0m [0m[38;5;245m(106µs)[0m
de-duplicates the watch list so a repeated ID cannot waste a slot ... [0m[32mok[0m [0m[38;5;245m(203µs)[0m
reads every chunk in full, not just the first ... [0m[32mok[0m [0m[38;5;245m(203µs)[0m
[0m[38;5;245mrunning 16 tests from ./tests/state_test.ts[0m
sums amounts exactly, past what a double can hold ... [0m[32mok[0m [0m[38;5;245m(1ms)[0m
sums an empty set to zero ... [0m[32mok[0m [0m[38;5;245m(167µs)[0m
refuses an amount that is not an integer string ... [0m[32mok[0m [0m[38;5;245m(1ms)[0m
a group with no events is open and zeroed ... [0m[32mok[0m [0m[38;5;245m(437µs)[0m
status follows the lifecycle events the chain emitted ... [0m[32mok[0m [0m[38;5;245m(363µs)[0m
counts members from the recorded joins ... [0m[32mok[0m [0m[38;5;245m(188µs)[0m
rounds come from the events that named them ... [0m[32mok[0m [0m[38;5;245m(206µs)[0m
totals are the sums of the recorded facts ... [0m[32mok[0m [0m[38;5;245m(159µs)[0m
deriving twice from the same facts gives the same state ... [0m[32mok[0m [0m[38;5;245m(367µs)[0m
a group that has never been derived is not reported as divergent ... [0m[32mok[0m [0m[38;5;245m(402µs)[0m
agreement between stored and derived state is silent ... [0m[32mok[0m [0m[38;5;245m(196µs)[0m
a drifted total is reported ... [0m[32mok[0m [0m[38;5;245m(219µs)[0m
every kind of drift is reported ... [0m[32mok[0m [0m[38;5;245m(195µs)[0m
the captured group derives its whole lifecycle from its events ... [0m[32mok[0m [0m[38;5;245m(143µs)[0m
the captured group takes in exactly what it paid out and charged ... [0m[32mok[0m [0m[38;5;245m(266µs)[0m
re-deriving the captured group agrees with itself ... [0m[32mok[0m [0m[38;5;245m(125µs)[0m
[0m[38;5;245mrunning 7 tests from ./tests/stellar_test.ts[0m
parseEventOrdinal reads the ordinal from a real paging token ... [0m[32mok[0m [0m[38;5;245m(1ms)[0m
parseEventOrdinal uses the last separator ... [0m[32mok[0m [0m[38;5;245m(143µs)[0m
parseEventOrdinal refuses tokens it does not understand ... [0m[32mok[0m [0m[38;5;245m(218µs)[0m
getEvents derives the ledger-scoped ordinal, not the page position ... [0m[32mok[0m [0m[38;5;245m(9ms)[0m
getEvents records whether the emitting call succeeded ... [0m[32mok[0m [0m[38;5;245m(657µs)[0m
getEvents skips entries it cannot identify ... [0m[32mok[0m [0m[38;5;245m(472µs)[0m
getEvents fails loudly on a paging token it cannot parse ... [0m[32mok[0m [0m[38;5;245m(919µs)[0m

[0m[32mok[0m | 234 passed | 0 failed [0m[38;5;245m(55s)[0m


[0m[32mTask[0m [0m[36mtest[0m deno test --allow-env --allow-read --allow-net=deno.land,jsr.io,registry.npmjs.org tests/

```

## Sortie : `deno task check`

```

[0m[32mTask[0m [0m[36mcheck[0m deno check supabase/functions/indexer/index.ts
[0m[32mCheck[0m supabase/functions/indexer/index.ts

```

## Sortie : `deno task fmt:check`

```

[0m[32mTask[0m [0m[36mfmt:check[0m deno fmt --check
Checked 63 files

```

## Sortie : `deno task lint`

```

[0m[32mTask[0m [0m[36mlint[0m deno lint
Checked 41 files

```