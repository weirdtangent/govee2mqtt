from datetime import datetime, timezone

def log(msg, level="INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if level != "DEBUG": # or (config and 'debug' in config and config['debug']):
        print(f"{ts} [{level}] {msg}")