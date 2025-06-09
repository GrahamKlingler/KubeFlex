#!/bin/bash

# Usage Info
if [ -z "$1" ]; then
    echo "Usage: $0 [simple|threaded|file_stress] [thread_count]"
    echo "  simple: Run simple test program"
    echo "  threaded: Run threaded workload with specified thread count (default: 4)"
    echo "  file_stress: Run file-heavy workload with specified thread count (default: 4)"
    exit 1
fi

TEST_TYPE=$1
THREAD_COUNT=${2:-4}  # Default to 4 threads

# Validate thread count
if [[ "$TEST_TYPE" == "threaded" || "$TEST_TYPE" == "file_stress" ]]; then
    if ! [[ "$THREAD_COUNT" =~ ^[0-9]+$ ]] || [ "$THREAD_COUNT" -lt 1 ] || [ "$THREAD_COUNT" -gt 32 ]; then
        echo "Error: Thread count must be between 1 and 32"
        exit 1
    fi
fi

echo "=== CRIU PID-Safe Checkpoint/Restore Demo ($TEST_TYPE) ==="
echo "Thread count: $THREAD_COUNT"
echo

# Check CRIU install
if ! command -v criu &> /dev/null; then
    echo "✗ CRIU not found. Install with: sudo apt install criu"
    exit 1
fi
echo "✓ CRIU version: $(criu --version)"

# Step 1: Create test programs
mkdir -p /tmp/test_build

# Simple program
cat > /tmp/test_build/simple_test.c <<'EOF'
#include <stdio.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
volatile int running = 1;
void handle_signal(int sig) { running = 0; }
int main() {
    signal(SIGTERM, handle_signal);
    FILE *f = fopen("/tmp/simple.log", "a");
    int counter = 0;
    while (running) {
        time_t now = time(NULL);
        fprintf(f, "Simple count: %d, Time: %s", counter++, ctime(&now));
        fflush(f);
        sleep(2);
    }
    return 0;
}
EOF

gcc -o /tmp/simple_test /tmp/test_build/simple_test.c -pthread

# Threaded workload
cp threaded_workload.c /tmp/test_build/threaded_workload.c
gcc -o /tmp/threaded_test /tmp/test_build/threaded_workload.c -pthread

# File stress
cp file_stress.c /tmp/test_build/file_stress.c
gcc -o /tmp/file_stress_test /tmp/test_build/file_stress.c -pthread

echo "✓ Programs compiled"

# Step 2: Launch test program
echo
echo "2. Starting $TEST_TYPE test program..."

if [ "$TEST_TYPE" == "simple" ]; then
    nohup /tmp/simple_test </dev/null >/dev/null 2>&1 &
    TEST_PID=$!
    LOG_FILE="/tmp/simple.log"
elif [ "$TEST_TYPE" == "threaded" ]; then
    nohup /tmp/threaded_test "$THREAD_COUNT" </dev/null >/dev/null 2>&1 &
    TEST_PID=$!
    LOG_FILE="/tmp/threaded.log"
elif [ "$TEST_TYPE" == "file_stress" ]; then
    nohup /tmp/file_stress_test "$THREAD_COUNT" </dev/null >/dev/null 2>&1 &
    TEST_PID=$!
    LOG_FILE="/tmp/file_stress.log"
else
    echo "Invalid test type"
    exit 1
fi

# Verify it's running
sleep 1
if ! ps -p "$TEST_PID" > /dev/null; then
    echo "✗ Test failed to start"
    exit 1
fi

echo "✓ Running PID: $TEST_PID"

# Create checkpoint directory
echo
echo "5. Creating checkpoint..."
CHECKPOINT_DIR="/tmp/criu-${TEST_TYPE}-checkpoint"
rm -rf "$CHECKPOINT_DIR" && mkdir -p "$CHECKPOINT_DIR"

#Dump checkpoint
echo "starting CRIU dump..."

DUMP_START=$(date +%s.%N)
sudo criu dump \
    -t "$TEST_PID" \
    -D "$CHECKPOINT_DIR" \
    -v4 \
    --leave-stopped \
    --tcp-established \
    --file-locks \
    --link-remap \
    --manage-cgroups \
    --ext-unix-sk \
    --shell-job \
    --ghost-limit 1073741824 \
    -o dump.log 2>&1
DUMP_RESULT=$?
DUMP_END=$(date +%s.%N)
DUMP_DURATION=$(echo "$DUMP_END - $DUMP_START" | bc)

if [ $DUMP_RESULT -ne 0 ]; then
    echo "✗ Checkpoint failed"
    exit 1
fi

# Ensure process is stopped
echo
echo "6. Verifying process stopped..."
sleep 2
if ! ps -p "$TEST_PID" > /dev/null 2>&1; then
    echo "✓ Process stopped after checkpoint"
else
    echo "⚠ Process still running, killing it..."
    kill -9 "$TEST_PID" 2>/dev/null
    sleep 1
fi

#  Restore
echo "Starting restore..."
RESTORE_START=$(date +%s.%N)
sudo criu restore \
    -D "$CHECKPOINT_DIR" \
    -v4 \
    --restore-detached \
    --pidfile /tmp/restored.pid \
    --tcp-established \
    --file-locks \
    --shell-job \
    --link-remap \
    --manage-cgroups \
    --ext-unix-sk \
    --ghost-limit 1073741824 \
    -o restore.log 2>&1
RESTORE_RESULT=$?
RESTORE_END=$(date +%s.%N)
RESTORE_DURATION=$(echo "$RESTORE_END - $RESTORE_START" | bc)

if [ $RESTORE_RESULT -ne 0 ]; then
    echo "✗ Restore failed"
    exit 1
fi

# Calculate total downtime
TOTAL_DOWNTIME=$(echo "$RESTORE_END - $DUMP_START" | bc)

# Print timing results
echo
echo "=== Timing Results ==="
echo "Dump duration:    ${DUMP_DURATION} seconds"
echo "Restore duration: ${RESTORE_DURATION} seconds"
echo "Total downtime:   ${TOTAL_DOWNTIME} seconds"

# Cleanup
sudo pkill -f "${TEST_TYPE}_test" 2>/dev/null || true
rm -f /tmp/simple_test /tmp/simple_test.c /tmp/stress_test /tmp/stress_test.c /tmp/threaded_test /tmp/restored.pid /tmp/stress_thread_*.log
rm -rf "$CHECKPOINT_DIR"

echo "=== Demo Complete ==="
echo
echo "If restore still fails, try these system-level fixes:"
echo "1. sudo sysctl kernel.ns_last_pid=1000"
echo "2. sudo echo 1000 > /proc/sys/kernel/ns_last_pid"
echo "3. Restart in a clean environment"
echo "4. Check: cat /proc/sys/kernel/pid_max"
