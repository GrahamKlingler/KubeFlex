#!/bin/bash
docker build -t python-controller:latest -f Dockerfile.main .
docker tag python-controller:latest salamander1223/python-controller:latest
docker push salamander1223/python-controller:latest

docker build -t python-db-upload:latest -f Dockerfile.db .
docker tag python-db-upload:latest salamander1223/python-db-upload:latest
docker push salamander1223/python-db-upload:latest