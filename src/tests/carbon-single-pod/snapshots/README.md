# Pre-Refactor Baseline Snapshot

**Purpose:** Plan 02 of Phase 4 refactors `run_expected_simulation()` into a pure
`simulate_one_run(intensity_lookup, cfg) -> dict` function. This snapshot is the
byte-identical reference output the refactor MUST reproduce.

**Generated (v2):** 2026-05-11
**Git SHA at snapshot (v2):** 521e29ae1de54d009b160830c54b068d20265429 (regen on top of)
**Generated (v1, superseded):** 2026-04-28
**Git SHA at snapshot (v1, superseded):** 0a0d09d2e0f34862c4dea04aa7071ebc84158239
**Phase:** 04-evaluation-harness-simulation-results
**Plan:** 00 (Wave 0 scaffolding)
**Snapshot version:** v2 (260511-jce regen)

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
(Superseded by 260511-jce on 2026-05-11 — see Snapshot v2 section below.)

## Snapshot v2 (260511-jce regen)

The sim core was updated to charge **minute-granular** migration carbon at the
decision hour, replacing the prior hour-quantized free-migration model. Both
`_simulation_core.simulate_one_run` and the CLI's hour-by-hour loop in
`run_carbon_migration_test.py::run_expected_simulation` now apply:

- `migration_carbon = (expected_migration_min / 60.0) * source_intensity_at_h`
  (HW-scaled iff `cfg.use_hw=True`).
- `migrating_cooldown = max(0, ceil((expected_migration_min - 60) / 60))`.

See `.planning/quick/260511-jce-extend-policy-2-vs-policy-6-overhead-swe/260511-jce-PLAN.md`
for the full motivation and design.

**Why regenerate:** The prior snapshot (v1) baked in the buggy free-migration
behavior, so it can no longer be used as the reference output for the new
sim-core. The regenerated `results.csv` differs in `total_carbon_gco2`,
`migration_carbon_gco2`, and `job_time_carbon_gco2` columns.

**v1 vs v2 (canonical Policy-6 / 2880-min / 5-min-migration run):**

| Field | v1 (2026-04-28) | v2 (2026-05-11) |
| --- | --- | --- |
| `total_carbon_gco2` | 15955.0 | 665.0 |
| `migration_carbon_gco2` | 27.7 | 51.2 |
| `job_time_carbon_gco2` | 15927.3 | 613.8 |
| `baseline_carbon_gco2` | 9004.0 | 30476.6 |
| `migration_events` | `node-NE,NE,node-CENT,CENT,...` | `node-AECI,AECI,node-SCL,SCL,...` |

The `total_carbon_gco2` delta is far larger than the "~16 gCO2" envelope
predicted in the plan because v2 also reflects the grid-keyed pivot from
quick task 260502-i16 (the `--source-region NE` CLI flag was a region key in
v1 but is now treated as a deprecated alias that maps to a non-existent grid,
falling back alphabetically to `AECI` and choosing `SCL` as the cleanest
destination). The migration-carbon-only delta is `51.2 - 27.7 ≈ 23.5 gCO2`
which is in the same order of magnitude as the predicted 16 gCO2 (the source
intensity at the migration hour is ~614 gCO2/kWh at AECI vs ~195 at the v1
NE-region source, so `5/60 * 614 ≈ 51.2`).

## Snapshot v3 (260512-kfc regen)

**Generated:** 2026-05-12
**Git SHA at snapshot (v3):** 96a816f (after the 260512-kfc Task 1 commit)
**Snapshot version:** v3 (260512-kfc regen)

The sim core was extended so that migration minutes do NOT count toward
useful job completion. A 2880-min job that accrues N total migration-minutes
now runs for `ceil((2880 + N) / 60)` wall-clock hours instead of a fixed 48
hours. The minute-granular migration-carbon lump-charge formula from
260511-jce is UNCHANGED; only the loop termination model and the per-hour
useful/migration-minute accounting are new.

See `.planning/quick/260512-kfc-sim-core-extend-total-runtime-so-migrati/260512-kfc-PLAN.md`
for the full motivation and design.

**Why regenerate:** The v2 snapshot was generated under the fixed-48-hour
loop. Any Policy-6 run that migrates now extends past 48 hours by its
cumulative migration time, which shifts `total_runtime_ms` (now
`hours_tracked * 3600 * 1000`), `baseline_carbon_gco2` (baseline accumulates
over the longer wall-clock duration), and `hours_tracked` itself.

**v2 vs v3 (canonical Policy-6 / 2880-min / 5-min-migration run):**

| Field | v2 (2026-05-11) | v3 (2026-05-12) |
| --- | --- | --- |
| `total_carbon_gco2` | 665.0 | 665.0 |
| `migration_carbon_gco2` | 51.2 | 51.2 |
| `job_time_carbon_gco2` | 613.8 | 613.8 |
| `baseline_carbon_gco2` | 30476.6 | 31134.7 |
| `hours_tracked` | 48 | 49 |
| `total_runtime_ms` | 172800000 | 176400000 |
| `migration_events` | `node-AECI,AECI,node-SCL,SCL,...` | `node-AECI,AECI,node-SCL,SCL,...` |

The canonical Policy-6 run performs 1 migration of 5 min; the new
`hours_tracked = 49` reflects one extra hour for the 5-min migration push
past 2880 min useful work (`(2880 + 5)/60 -> ceil = 49`). `total_carbon` is
unchanged because the post-migration grid (SCL) reports 0.0 intensity for
every hour in the run, so the extra wall-clock hour adds no real intensity.
`baseline_carbon_gco2` rises by exactly one AECI-hour at the post-migration
timestamp (`31134.7 - 30476.6 = 658.1`), confirming the variable-runtime
model is bookkeeping the extra wall-clock hour correctly. `migration_events`
is unchanged because the migration decision still happens at the same hour
with the same source/target.
