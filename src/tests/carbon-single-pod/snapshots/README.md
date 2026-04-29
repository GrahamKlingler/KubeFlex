# Pre-Refactor Baseline Snapshot

**Purpose:** Plan 02 of Phase 4 refactors `run_expected_simulation()` into a pure
`simulate_one_run(intensity_lookup, cfg) -> dict` function. This snapshot is the
byte-identical reference output the refactor MUST reproduce.

**Generated:** 2026-04-28
**Git SHA at snapshot:** 0a0d09d2e0f34862c4dea04aa7071ebc84158239
**Phase:** 04-evaluation-harness-simulation-results
**Plan:** 00 (Wave 0 scaffolding)

## Canonical invocation

```
cd src && python3 tests/carbon-single-pod/run_carbon_migration_test.py --expected \
  --policy 6 \
  --scheduler-time 1609459200 \
  --source-region NE \
  --expected-completion 2880 \
  --expected-migration 5 \
  --app-size-mb 64 \
  --deadline-multiplier 1.5 \
  --forecast-cache ../data/carbon-single-pod/best_run/forecast_cache.json \
  --out-dir tests/carbon-single-pod/snapshots/_pre_refactor_run
```

## Files

- `_pre_refactor_run/` — Full output directory from the canonical run
  (`carbon_log.csv`, `migration_events.csv`, `results.csv`, `forecast_cache.json`).
- `refactor_baseline_results.csv` — Frozen copy of `_pre_refactor_run/results.csv`;
  this is the file Plan 02's regression test diffs against.

## Notes on the forecast cache

The canonical invocation references `data/carbon-single-pod/best_run/forecast_cache.json`.
At the time this snapshot was generated, the worktree's local `data/` directory did
not contain a `best_run/` subdirectory, so the 240-hour forecast cache from a known-good
Phase-3 Policy-6 run (`data/carbon-single-pod/20260421_165150_policy6_expected/forecast_cache.json`
in the parent repo) was copied into `data/carbon-single-pod/best_run/forecast_cache.json`.
That cache contains all three regions (NE, TEN, CENT) and 241 hourly points starting at
2021-01-01 00:00 UTC, which is sufficient to cover the 48-hour run plus the 72-hour
forecast lookahead buffer the harness adds.

## Re-running

DO NOT regenerate this snapshot after Plan 02 lands — that defeats its purpose.
If the snapshot must be regenerated (e.g., a deliberate behavior change ships),
document the reason and bump the snapshot version.
