#!/bin/bash

# Usage: ./new_bench.sh <output_csv>
if [ -z "$1" ]; then
    echo "Usage: $0 <output_csv>"
    exit 1
fi

OUTPUT_CSV="$1"

# Write CSV header
echo "workload,threads,dump_time,restore_time,total_downtime" > "$OUTPUT_CSV"

# Define workloads and thread counts
WORKLOADS=("threaded" "file_stress")
THREAD_COUNTS=(1 2 4 6 8 10 12 14 16 18 20 22 24 26 28 30 32)

for workload in "${WORKLOADS[@]}"; do
    for threads in "${THREAD_COUNTS[@]}"; do
        echo "Running $workload with $threads threads/files..."

        # Run workload.sh and capture output
        OUTPUT=$(./workload.sh "$workload" "$threads" 2>&1)

        # Extract times using regex
        DUMP_TIME=$(echo "$OUTPUT" | grep -i "Dump duration:" | awk '{print $3}')
        RESTORE_TIME=$(echo "$OUTPUT" | grep -i "Restore duration:" | awk '{print $3}')
        TOTAL_DOWNTIME=$(echo "$OUTPUT" | grep -i "Total downtime:" | awk '{print $3}')

        # Fallback to 0.0 if parsing fails
        DUMP_TIME=${DUMP_TIME:-0.0}
        RESTORE_TIME=${RESTORE_TIME:-0.0}
        TOTAL_DOWNTIME=${TOTAL_DOWNTIME:-0.0}

        # Append to CSV
        echo "$workload,$threads,$DUMP_TIME,$RESTORE_TIME,$TOTAL_DOWNTIME" >> "$OUTPUT_CSV"
        echo "✓ Done with $workload $threads"
    done
done

echo "All benchmarks complete. Results saved to $OUTPUT_CSV."
