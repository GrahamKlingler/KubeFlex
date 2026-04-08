cid=$(docker create grahamklingler26/sysbench-testpod:latest)
docker export "$cid" | tar -tvf - | egrep '(^| )dev($|/| )|dev/ptmx|dev/pts' | head -n 50
docker rm "$cid"