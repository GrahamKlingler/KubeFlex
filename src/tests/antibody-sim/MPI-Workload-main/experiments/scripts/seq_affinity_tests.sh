#!/bin/bash

nodes=(1 2 3 5 7 9 11 13 15 17 19)

output_dir="results"
mkdir -p "$output_dir"

for n in "${nodes[@]}"; do
    cpu_list=$(seq -s, 0 1 $((n - 1)))

    # For testing jacobi
    result=$(taskset -c "$cpu_list" mpirun -n "$n" ./elastic_jacobi -s 1000 -i 100000 -c 0)

    # For testing cg
    # result=$(taskset -c "$cpu_list" mpirun -n "$n" ./elastic_cg -s 1000 -i 100000 -c 0)

    # For testing nbody
    # result=$(taskset -c "$cpu_list" mpirun -n "$n" ./nbody -b 1000 -i 100000 -c 0)

    echo "Nodes: $n, CPUs: $cpu_list, Result: $result"
    echo "$result" >> "$output_dir/seqresults100.txt"
done