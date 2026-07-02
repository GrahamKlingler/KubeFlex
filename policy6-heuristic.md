# Policy 6 — HeuristicPolicy

The full implementation lives at `src/controller/heuristics/policy_heuristic.py:40-241`. Each hour the controller calls `decide()`, which makes a stay-vs-migrate carbon comparison.

## Inputs

- `app_size_mb` — checkpoint size, drives overhead estimates
- `expected_total_minutes` — nominal workload length
- `deadline_multiplier` (default 1.5) — gives a hard deadline = `expected × 1.5`
- `lookahead_hours` (default 48) — caps the inner forecast loop
- Three ablation toggles (`hw_weighting`, `overhead_cost`, `deadline_gate`)

## Per-call decision flow

**1. Compute migration overhead per candidate** (`policy_heuristic.py:144-152`)

For each destination `r`, sum three calibrated linear-fit functions from `overhead.py`:

- `ckpt_overhead(app_size_mb, src_hw)` — checkpoint on source
- `send_overhead(src_hw, dst_hw, app_size_mb)` — network transfer
- `restore_overhead(app_size_mb, dst_hw)` — restore on destination

Result is `overhead_h[r]` in hours. Stay (`r == current`) is 0.

**2. Hardware-adjusted remaining time** (`runtime.py:39-46`)

`time_left_h = (expected_total_minutes/60 − elapsed_hours) × (src_clock / src_clock)`. For the stay-case this collapses to plain remaining hours; the same scaling logic produces destination runtimes via different hardware specs.

**3. Deadline budget**

`deadline_remaining_h = max(0, expected_hours × multiplier − elapsed)`.

**4. Stay carbon** (`policy_heuristic.py:170-175`)

Sum forecasted intensity at `current_region` for the next `min(time_left, lookahead)` hours, optionally weighted by `hw[current].power_per_core`.

**5. For each candidate destination** (`policy_heuristic.py:185-236`):

- **Deadline gate** — skip if `time_left + mig_time > deadline_remaining`. Sets `last_skip_reason = "deadline_gate"`.
- **Migration carbon** =
  - `ckpt_h × src_power × src_intensity_now`
  - `+ restore_h × dst_power × dst_intensity_now`
  - `+ send_h × network_power × (src_intensity + dst_intensity)/2` (when `include_network_power`)
- **Destination running carbon** — same loop as stay, but offset by `mig_time` and using destination forecast and `dst.power_per_core`.
- **Total** = `migration_carbon + dest_run_carbon`.

**6. Pick the lowest-cost option**

If any candidate's total beats `stay_carbon`, return `(True, that_region)`. Otherwise `(False, None)`.

## Ablation toggles

| Toggle | When False |
|---|---|
| `hw_weighting` | Drop `power_per_core` weight from both stay and dest sums (raw intensity) |
| `overhead_cost` | Zero out `migration_carbon` entirely (network_power becomes irrelevant) |
| `deadline_gate` | Skip the deadline check; long-job migrations are not pre-empted |

These three flags drive Phase 4's 8-cell ablation sweep (HEUR-10).

## Key properties

- **Greedy per-hour**: no multi-step planning; each tick re-evaluates from scratch.
- **Picks the *minimum* total over all candidates**, not the first improvement.
- **Forecast horizon clamp** at `lookahead_hours` is what makes the inner loop O(min(time_left, 48)) rather than O(remaining).
- The current region is always evaluated as "stay"; ties favor stay because the loop only swaps when strictly less.
