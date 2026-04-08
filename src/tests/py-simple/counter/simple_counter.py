# Python script to log PID, count, and time to /script-data/container.log every 20 seconds
import os
import time
from datetime import datetime

log_path = "/script-data/container.log"
counter = 0

while True:
    pid = os.getpid()
    now = datetime.now().strftime("%a %b %d %H:%M:%S %Y")
    with open(log_path, "a") as f:
        f.write(f"PID: {pid}, Count: {counter}, Time: {now}\n")
    counter += 1
    time.sleep(20)
