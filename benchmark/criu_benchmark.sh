#!/bin/bash

# Create output CSV file with headers
echo "threads,dump_time,restore_time,total_downtime" > criu_benchmark_results.csv

# Function to extract timing from criu.sh output
extract_timing() {
    local output="$1"
    local metric="$2"
    echo "$output" | grep "$metric:" | awk '{print $3}'
}

# Run tests for thread counts 1 to 32
for threads in {1..32}; do
    echo "Running test with $threads threads..."
    
    # Run criu.sh and capture output
    output=$(./criu.sh stress "$threads" 2>&1)
    
    # Extract timing values
    dump_time=$(extract_timing "$output" "Dump duration")
    restore_time=$(extract_timing "$output" "Restore duration")
    total_time=$(extract_timing "$output" "Total downtime")
    
    # Append results to CSV
    echo "$threads,$dump_time,$restore_time,$total_time" >> criu_benchmark_results.csv
    
    # Small delay between runs to let system settle
    sleep 1
done

echo "Benchmark complete. Results saved to criu_benchmark_results.csv" 