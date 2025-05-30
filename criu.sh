#!/bin/bash

echo "=== CRIU PID-Safe Checkpoint/Restore Demo ==="
echo

# Check CRIU installation
if ! command -v criu &> /dev/null; then
    echo "✗ CRIU not found. Install with: sudo apt install criu"
    exit 1
fi

echo "✓ CRIU version: $(criu --version)"

# Create a simple test program that doesn't daemonize
echo
echo "1. Creating simple test program (no daemonization)..."
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
    // Redirect stdout/stderr to avoid TTY issues but don't fully daemonize
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

# Compile
gcc -o /tmp/simple_test /tmp/simple_test.c
if [ $? -ne 0 ]; then
    echo "✗ Failed to compile test program"
    exit 1
fi
echo "✓ Test program compiled successfully"

# Clean up old log
rm -f /tmp/simple.log

# Start in background with nohup to detach from TTY
echo
echo "2. Starting test program (detached from TTY)..."
nohup /tmp/simple_test </dev/null >/dev/null 2>&1 &
TEST_PID=$!

# Verify it's running
sleep 2
if ! ps -p "$TEST_PID" > /dev/null 2>&1; then
    echo "✗ Test program failed to start"
    exit 1
fi
echo "✓ Test program running with PID: $TEST_PID"

# Let it generate some data
echo "3. Letting it run for 8 seconds..."
sleep 8

echo "4. Current log content:"
if [ -f /tmp/simple.log ]; then
    tail -3 /tmp/simple.log
else
    echo "   No log file yet"
fi

# Create checkpoint directory
echo
echo "5. Creating checkpoint..."
CHECKPOINT_DIR="/tmp/criu-simple-checkpoint"
rm -rf "$CHECKPOINT_DIR"
mkdir -p "$CHECKPOINT_DIR"

# Comprehensive dump with all flags
echo "   Attempting dump with comprehensive flags..."
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
echo "   Dump exit code: $DUMP_RESULT"

if [ $DUMP_RESULT -eq 0 ]; then
    echo "✓ Checkpoint created successfully"
    echo "   Checkpoint files:"
    ls -la "$CHECKPOINT_DIR/" | head -10
else
    echo "✗ Checkpoint failed"
    echo "=== DUMP LOG (last 30 lines) ==="
    tail -30 "$CHECKPOINT_DIR/dump.log" 2>/dev/null || echo "No dump log available"
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

# Method 1: Try restore in new PID namespace
echo
echo "7. Attempting restore (Method 1: new PID namespace)..."
cd "$CHECKPOINT_DIR"

# Clear any zombie processes
sudo pkill -f simple_test 2>/dev/null || true
sleep 1

# Try restore with --restore-detached and --pidfile
sudo criu restore \
    -D . \
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
echo "   Restore exit code: $RESTORE_RESULT"

if [ $RESTORE_RESULT -eq 0 ]; then
    echo "✓ Process restored successfully"
    
    # Get restored PID
    if [ -f /tmp/restored.pid ]; then
        RESTORED_PID=$(cat /tmp/restored.pid)
        echo "   Restored PID: $RESTORED_PID"
    else
        RESTORED_PID=$(pgrep -f simple_test | head -1)
        echo "   Found restored PID: $RESTORED_PID"
    fi
    
    echo "8. Verifying process resumed..."
    sleep 6
    echo "   Latest log entries:"
    if [ -f /tmp/simple.log ]; then
        tail -5 /tmp/simple.log
    else
        echo "   No log file found"
    fi
    
    # Graceful shutdown
    if [ ! -z "$RESTORED_PID" ] && ps -p "$RESTORED_PID" > /dev/null 2>&1; then
        kill "$RESTORED_PID" 2>/dev/null
        sleep 2
        echo "✓ Restored process stopped gracefully"
    fi
    
else
    echo "✗ Restore failed"
    echo "=== CHECKING SYSTEM STATE ==="
    echo "Existing simple_test processes:"
    ps aux | grep simple_test | grep -v grep || echo "None found"
    echo
    echo "=== RESTORE LOG (last 40 lines) ==="
    tail -40 restore.log 2>/dev/null || echo "No restore log"
    echo
    echo "=== DMESG (last 15 lines) ==="
    dmesg | tail -15
    echo
    echo "=== ALTERNATIVE: Try with --restore-sibling ==="
    
    # Method 2: Try with --restore-sibling
    sudo pkill -f simple_test 2>/dev/null || true
    sleep 2
    
    sudo criu restore \
        -D . \
        -v4 \
        --restore-sibling \
        --tcp-established \
        --file-locks \
        --ext-unix-sk \
        -o restore2.log 2>&1
    
    RESTORE2_RESULT=$?
    echo "Alternative restore exit code: $RESTORE2_RESULT"
    
    if [ $RESTORE2_RESULT -eq 0 ]; then
        echo "✓ Alternative restore succeeded!"
        sleep 3
        NEW_PID=$(pgrep -f simple_test | head -1)
        echo "New PID: $NEW_PID"
        if [ ! -z "$NEW_PID" ]; then
            kill "$NEW_PID" 2>/dev/null
        fi
    else
        echo "✗ Alternative restore also failed"
        tail -20 restore2.log 2>/dev/null || echo "No alternative restore log"
    fi
fi

echo
echo "=== Cleanup ==="
sudo pkill -f simple_test 2>/dev/null || true
rm -f /tmp/simple_test /tmp/simple_test.c /tmp/restored.pid
rm -rf "$CHECKPOINT_DIR"

echo "=== Demo Complete ==="
echo
echo "If restore still fails, try these system-level fixes:"
echo "1. sudo sysctl kernel.ns_last_pid=1000"
echo "2. sudo echo 1000 > /proc/sys/kernel/ns_last_pid"
echo "3. Restart in a clean environment"
echo "4. Check: cat /proc/sys/kernel/pid_max"