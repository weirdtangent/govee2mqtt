from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo

def app_log(msg, level='INFO', tz='UTC', hide_ts=False):
    ts = datetime.now(ZoneInfo(tz)).strftime('%Y-%m-%d %H:%M:%S %Z')
    if len(msg) > 102400:
        raise ValueError('Log message exceeds max length')
    if level != 'DEBUG' or os.getenv('DEBUG'):
        print(f'{ts + " " if not hide_ts else ""}[{level}] {msg}')

def number_to_rgb(number, max_value):
    normalized_value = number / max_value
    r = int((1 - normalized_value) * 255)
    g = int(normalized_value * 255)
    b = int((0.5 - abs(normalized_value - 0.5)) * 2 * 255) if normalized_value > 0.5 else 0
    return { 'r': r, 'g': g, 'b': b }

def rgb_to_number(rgb):
    return int(((rgb['r'] & 0xFF) << 16) + ((rgb['g'] & 0xFF) << 8) + (rgb['b'] & 0xFF))        
