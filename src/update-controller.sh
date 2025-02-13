#!/bin/bash
docker build -t python-controller:latest .
docker tag python-controller:latest salamander1223/python-controller:latest
docker push salamander1223/python-controller:latest