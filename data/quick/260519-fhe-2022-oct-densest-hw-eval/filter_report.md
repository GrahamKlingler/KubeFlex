# Argmin-Dominator Filter Report (260519-fhe)

**Threshold:** 50.0% (a grid winning >= this fraction of usable hours is removed)
**Window starts:** [1666576800]
**Window length:** 48 hours per start
**use_hw:** True
**Initial pool (8 grids):** ['PNM', 'LDWP', 'TEPC', 'IPCO', 'PSCO', 'NEVP', 'ERCO', 'SWPP']

## Per-iteration history

### Iteration 1

Pool size: 8
Total counted hours: 48 of 48 possible

Argmin wins (HW-scaled iff use_hw):

```
  ERCO   ##########                       16/  48 (33.3%)
  PNM    #########                        14/  48 (29.2%)
  SWPP   #####                             8/  48 (16.7%)
  IPCO   ####                              6/  48 (12.5%)
  NEVP   ##                                3/  48 (6.2%)
  PSCO   #                                 1/  48 (2.1%)
  TEPC                                     0/  48 (0.0%)
  LDWP                                     0/  48 (0.0%)
```

Action: no dominator (max win-fraction 33.3% < threshold 50.0%). Halting filter.

## Final pool (8 grids):

['PNM', 'LDWP', 'TEPC', 'IPCO', 'PSCO', 'NEVP', 'ERCO', 'SWPP']

## Removed in order:

- (none — no grid exceeded the threshold)
