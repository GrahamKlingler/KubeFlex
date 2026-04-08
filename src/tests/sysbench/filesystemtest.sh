IMG=grahamklingler26/sysbench-testpod:latest
mkdir -p /tmp/img && rm -rf /tmp/img/*
docker image save "$IMG" -o /tmp/img/img.tar
tar -xf /tmp/img/img.tar -C /tmp/img

# Find which layer last touched /dev or /dev/null
grep -R "/dev/null" -n /tmp/img | head