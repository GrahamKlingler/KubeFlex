#!/bin/bash

# Start the migration service
# Migrator pods are now created as part of the deployment process in run.sh
exec python migrate_service.py
