#!/bin/bash

# Check if test type is provided
if [ -z "$1" ]; then
    echo "Usage: $0 [simple|stress] [thread_count]"
    echo "  simple: Run simple test program"
    echo "  stress: Run stress test program with specified thread count (default: 4)"
    exit 1
fi

TEST_TYPE=$1
THREAD_COUNT=${2:-4}  # Default to 4 threads if not specified

# Validate thread count for stress test
if [ "$TEST_TYPE" = "stress" ]; then
    if ! [[ "$THREAD_COUNT" =~ ^[0-9]+$ ]] || [ "$THREAD_COUNT" -lt 1 ] || [ "$THREAD_COUNT" -gt 32 ]; then
        echo "Error: Thread count must be between 1 and 32"
        exit 1
    fi
fi

echo "=== CRIU PID-Safe Checkpoint/Restore Demo ($TEST_TYPE) ==="
if [ "$TEST_TYPE" = "stress" ]; then
    echo "Thread count: $THREAD_COUNT"
fi
echo

# Check CRIU installation
if ! command -v criu &> /dev/null; then
    echo "✗ CRIU not found. Install with: sudo apt install criu"
    exit 1
fi

echo "✓ CRIU version: $(criu --version)"

# Create test programs
echo
echo "1. Creating test programs..."

# Simple test program
cat > /tmp/simple_test.c << 'EOF'
#include <stdio.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <sys/types.h>
#include <fcntl.h>

volatile int running = 1;

void handle_signal(int sig) {
    running = 0;
}

int main() {
    freopen("/dev/null", "w", stdout);
    freopen("/dev/null", "w", stderr);
    
    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    
    FILE *f = fopen("/tmp/simple.log", "a");
    if (!f) return 1;
    
    int counter = 0;
    while (running) {
        time_t now = time(NULL);
        fprintf(f, "Simple test count: %d, Time: %s", counter++, ctime(&now));
        fflush(f);
        sleep(2);
    }
    
    fprintf(f, "Simple test shutting down\n");
    fclose(f);
    return 0;
}
EOF

# Stress test program
cat > /tmp/stress_test.c << 'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <sys/types.h>
#include <fcntl.h>
#include <string.h>
#include <pthread.h>

#define ARRAY_SIZE 1000000
#define MEMORY_SIZE (1024 * 1024 * 100) // 100MB per thread

volatile int running = 1;
pthread_t* threads;
int** memory_arrays;
int num_threads;

void handle_signal(int sig) {
    running = 0;
}

void* stress_thread(void* arg) {
    int thread_id = *(int*)arg;
    int* array = memory_arrays[thread_id];
    char filename[64];
    FILE* file = NULL;
    
    // Create a unique file for this thread
    snprintf(filename, sizeof(filename), "/tmp/stress_thread_%d.log", thread_id);
    file = fopen(filename, "a");
    if (file) {
        fprintf(file, "Thread %d started\n", thread_id);
        fflush(file);
    }
    
    while (running) {
        // CPU stress
        for (int i = 0; i < ARRAY_SIZE; i++) {
            array[i] = array[i] * array[i] + array[i];
        }
        
        // Memory stress
        for (int i = 0; i < MEMORY_SIZE / sizeof(int); i++) {
            array[i] = array[i] ^ array[i + 1];
        }
        
        // Log progress
        if (file) {
            time_t now = time(NULL);
            fprintf(file, "Thread %d: CPU and memory operations completed at %s", 
                    thread_id, ctime(&now));
            fflush(file);
        }
        
        usleep(100000); // 100ms delay
    }
    
    if (file) {
        fprintf(file, "Thread %d shutting down\n", thread_id);
        fclose(file);
    }
    
    return NULL;
}

int main(int argc, char* argv[]) {
    freopen("/dev/null", "w", stdout);
    freopen("/dev/null", "w", stderr);
    
    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    
    // Get thread count from environment variable
    char* thread_count_str = getenv("STRESS_THREAD_COUNT");
    num_threads = thread_count_str ? atoi(thread_count_str) : 4;
    
    if (num_threads < 1 || num_threads > 32) {
        fprintf(stderr, "Invalid thread count: %d\n", num_threads);
        return 1;
    }
    
    FILE *f = fopen("/tmp/stress.log", "a");
    if (!f) return 1;
    
    fprintf(f, "Starting stress test with %d threads\n", num_threads);
    
    // Allocate arrays for threads and memory
    threads = (pthread_t*)malloc(num_threads * sizeof(pthread_t));
    memory_arrays = (int**)malloc(num_threads * sizeof(int*));
    
    if (!threads || !memory_arrays) {
        fprintf(f, "Failed to allocate thread arrays\n");
        return 1;
    }
    
    // Allocate memory for each thread
    for (int i = 0; i < num_threads; i++) {
        memory_arrays[i] = (int*)malloc(MEMORY_SIZE);
        if (!memory_arrays[i]) {
            fprintf(f, "Failed to allocate memory for thread %d\n", i);
            return 1;
        }
        memset(memory_arrays[i], i, MEMORY_SIZE);
    }
    
    // Create threads
    int* thread_ids = (int*)malloc(num_threads * sizeof(int));
    for (int i = 0; i < num_threads; i++) {
        thread_ids[i] = i;
        if (pthread_create(&threads[i], NULL, stress_thread, &thread_ids[i]) != 0) {
            fprintf(f, "Failed to create thread %d\n", i);
            return 1;
        }
        fprintf(f, "Created thread %d\n", i);
    }
    
    // Main loop
    int counter = 0;
    while (running) {
        time_t now = time(NULL);
        fprintf(f, "Stress test count: %d, Time: %s", counter++, ctime(&now));
        fflush(f);
        sleep(2);
    }
    
    // Cleanup
    fprintf(f, "Stress test shutting down\n");
    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
        free(memory_arrays[i]);
    }
    free(threads);
    free(memory_arrays);
    free(thread_ids);
    fclose(f);
    return 0;
}
EOF

# Compile both programs
gcc -o /tmp/simple_test /tmp/simple_test.c -pthread
gcc -o /tmp/stress_test /tmp/stress_test.c -pthread

if [ $? -ne 0 ]; then
    echo "✗ Failed to compile test programs"
    exit 1
fi
echo "✓ Test programs compiled successfully"

# Clean up old logs
rm -f /tmp/simple.log /tmp/stress.log /tmp/stress_thread_*.log

# Start the appropriate test program
echo
echo "2. Starting $TEST_TYPE test program..."
if [ "$TEST_TYPE" = "simple" ]; then
    nohup /tmp/simple_test </dev/null >/dev/null 2>&1 &
    TEST_PID=$!
    LOG_FILE="/tmp/simple.log"
else
    # Set thread count for stress test
    export STRESS_THREAD_COUNT=$THREAD_COUNT
    nohup /tmp/stress_test </dev/null >/dev/null 2>&1 &
    TEST_PID=$!
    LOG_FILE="/tmp/stress.log"
fi

# Verify it's running
sleep 1
if ! ps -p "$TEST_PID" > /dev/null 2>&1; then
    echo "✗ Test program failed to start"
    exit 1
fi
echo "✓ Test program running with PID: $TEST_PID"

# Create checkpoint directory
echo
echo "5. Creating checkpoint..."
CHECKPOINT_DIR="/tmp/criu-$TEST_TYPE-checkpoint"
rm -rf "$CHECKPOINT_DIR"
mkdir -p "$CHECKPOINT_DIR"

# Time the dump operation
echo "Starting dump..."
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

# Time the restore operation
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
rm -f /tmp/simple_test /tmp/simple_test.c /tmp/stress_test /tmp/stress_test.c /tmp/restored.pid /tmp/stress_thread_*.log
rm -rf "$CHECKPOINT_DIR"

echo "=== Demo Complete ==="
echo
echo "If restore still fails, try these system-level fixes:"
echo "1. sudo sysctl kernel.ns_last_pid=1000"
echo "2. sudo echo 1000 > /proc/sys/kernel/ns_last_pid"
echo "3. Restart in a clean environment"
echo "4. Check: cat /proc/sys/kernel/pid_max"