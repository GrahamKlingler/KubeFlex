#!/bin/bash

# Build the Docker image
echo "Building Docker image..."
docker build -t benchmark:latest -f build/Dockerfile.benchmark .

# Run the container with specified thread count
THREAD_COUNT=${1:-4}  # Default to 4 threads if not specified

echo "Running stress test with $THREAD_COUNT threads..."
docker run --rm \
    --privileged \
    -e STRESS_THREAD_COUNT=$THREAD_COUNT \
    criu-stress-test 