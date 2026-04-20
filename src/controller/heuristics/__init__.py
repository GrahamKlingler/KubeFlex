# Heuristics module
#
# Submodules:
#   hardware         - HW_TABLE, HardwareSpec, get_hardware()
#   data_splits      - check_split_access(), train/val/test boundaries
#   runtime          - estimate_remaining_hours()
#   overhead         - ckpt_overhead(), send_overhead(), restore_overhead()
#   base             - BasePolicy ABC
#   policies         - Policy1..Policy5 classes, lookup_intensity(), get_min_region_at()
#   policy_heuristic - HeuristicPolicy (Policy 6)
