#!/bin/bash

# Simple test script for migration testing
# This script runs a basic counter and logs output
# Simplified version without signal handlers for better CRIU compatibility
# Redirects output to files instead of pipes to avoid CRIU issues

# Initialize counter
counter=0
start_time=$(date)

echo "Test container started at: $start_time" > /script-data/container.log
echo "Process ID: $$" >> /script-data/container.log

# Main loop - simple counter
while true; do
    echo "Counter: $counter, Time: $(date), PID: $$" >> /script-data/container.log
    counter=$((counter + 1))
    sleep 30  # Check every 30 seconds
done