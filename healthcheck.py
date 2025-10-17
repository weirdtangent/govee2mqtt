#!/usr/bin/env python3
# /usr/local/bin/healthcheck.py
import os, sys, time, stat

path = os.getenv("READY_FILE", "/tmp/govee2mqtt.ready")
max_age = int(os.getenv("HEALTH_MAX_AGE", "90"))  # seconds

try:
    st = os.stat(path)
    sys.exit(0 if time.time() - st.st_mtime < max_age else 1)
except FileNotFoundError:
    sys.exit(1)

