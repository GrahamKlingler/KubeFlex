#!/bin/bash

# # Build and push CRIU container
# docker build -t criu-container:latest -f build/Dockerfile.criu .
# docker tag criu-container:latest salamander1223/criu-container:latest
# docker push salamander1223/criu-container:latest

# docker build -t criu-coordinator-server:latest -f build/Dockerfile.migrate-server .
# docker tag criu-coordinator-server:latest salamander1223/criu-coordinator-server:latest
# docker push salamander1223/criu-coordinator-server:latest

# docker build -t criu-coordinator-client:latest -f build/Dockerfile.migrate-client .
# docker tag criu-coordinator-client:latest salamander1223/criu-coordinator-client:latest
# docker push salamander1223/criu-coordinator-client:latest

# Build and push migration controller
docker build -t python-migrate:latest -f build/Dockerfile.migrate .
docker tag python-migrate:latest salamander1223/python-migrate:latest
docker push salamander1223/python-migrate:latest

# Build and push main controller
docker build -t python-controller:latest -f build/Dockerfile.main .
docker tag python-controller:latest salamander1223/python-controller:latest
docker push salamander1223/python-controller:latest

# Build and push DB upload
docker build -t python-db-upload:latest -f build/Dockerfile.db .
docker tag python-db-upload:latest salamander1223/python-db-upload:latest
docker push salamander1223/python-db-upload:latest

# Build and push data server
docker build -t python-data-server:latest -f build/Dockerfile.data-server .
docker tag python-data-server:latest salamander1223/python-data-server:latest
docker push salamander1223/python-data-server:latest

echo "Build and push completed."