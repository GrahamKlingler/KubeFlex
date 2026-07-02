# Argmin-Dominator Filter Report (260519-fhe)

**Threshold:** 50.0% (a grid winning >= this fraction of usable hours is removed)
**Window starts:** [1650121200]
**Window length:** 48 hours per start
**use_hw:** True
**Initial pool (8 grids):** ['PSCO', 'IPCO', 'PNM', 'SWPP', 'LDWP', 'PJM', 'ERCO', 'PACE']

## Per-iteration history

### Iteration 1

Pool size: 8
Total counted hours: 48 of 48 possible

Argmin wins (HW-scaled iff use_hw):

```
  IPCO   ################                 25/  48 (52.1%)
  LDWP   ##########                       16/  48 (33.3%)
  PSCO   ##                                4/  48 (8.3%)
  ERCO   #                                 2/  48 (4.2%)
  SWPP   #                                 1/  48 (2.1%)
  PJM                                      0/  48 (0.0%)
  PACE                                     0/  48 (0.0%)
  PNM                                      0/  48 (0.0%)
```

Action: removed IPCO (won 25/48 = 52.1%); mean intensity over window = 2198.64 gCO2eq (HW-scaled). Next-cheapest grid: LDWP mean = 2203.52.

### Iteration 2

Pool size: 7
Total counted hours: 48 of 48 possible

Argmin wins (HW-scaled iff use_hw):

```
  LDWP   ######################           36/  48 (75.0%)
  PSCO   ####                              7/  48 (14.6%)
  ERCO   ##                                3/  48 (6.2%)
  PJM    #                                 1/  48 (2.1%)
  SWPP   #                                 1/  48 (2.1%)
  PACE                                     0/  48 (0.0%)
  PNM                                      0/  48 (0.0%)
```

Action: removed LDWP (won 36/48 = 75.0%); mean intensity over window = 2203.52 gCO2eq (HW-scaled). Next-cheapest grid: ERCO mean = 2761.33.

### Iteration 3

Pool size: 6
Total counted hours: 48 of 48 possible

Argmin wins (HW-scaled iff use_hw):

```
  PSCO   ############                     20/  48 (41.7%)
  ERCO   ########                         12/  48 (25.0%)
  PACE   #####                             8/  48 (16.7%)
  PJM    ##                                4/  48 (8.3%)
  SWPP   ##                                4/  48 (8.3%)
  PNM                                      0/  48 (0.0%)
```

Action: no dominator (max win-fraction 41.7% < threshold 50.0%). Halting filter.

## Final pool (6 grids):

['PSCO', 'PNM', 'SWPP', 'PJM', 'ERCO', 'PACE']

## Removed in order:

1. IPCO (won 52.1%, mean intensity 2198.64 HW-scaled)
2. LDWP (won 75.0%, mean intensity 2203.52 HW-scaled)
