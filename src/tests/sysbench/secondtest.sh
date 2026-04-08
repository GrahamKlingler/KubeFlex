IMG=grahamklingler26/sysbench-testpod:latest

# Create (no start)
CID=$(docker create "$IMG" true)

# Export the rootfs and inspect /dev/null entry
docker export "$CID" | tar -tvf - | egrep '(^| )dev/(null|ptmx|tty)$|(^| )dev/$' || true

# Clean up
docker rm "$CID" >/dev/null