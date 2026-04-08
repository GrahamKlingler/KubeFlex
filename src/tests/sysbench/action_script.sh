#!/bin/sh
# CRIU action script: logs to /tmp/criu_action.log inside the container
echo "$(date -Iseconds) action=$CRTOOLS_SCRIPT_ACTION pid=$CRTOOLS_SCRIPT_PID stage=$CRTOOLS_SCRIPT_STAGE" >> /tmp/criu_action.log
# For post-resume, capture a snapshot of processes
if [ "$CRTOOLS_SCRIPT_ACTION" = "post-resume" ]; then
  ps -ef >> /tmp/criu_action.log
fi
exit 0
