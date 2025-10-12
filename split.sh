#!/usr/bin/env bash
set -euo pipefail

MONO="govee_mqtt.py"
PKG_DIR="govee_mqtt"
MIXIN_DIR="$PKG_DIR/mixins"
BACKUP="${MONO%.py}._backup_$(date +%Y%m%d_%H%M%S).py"

if [[ ! -f "$MONO" ]]; then
  echo "ERROR: $MONO not found in current directory." >&2
  exit 1
fi

echo "==> Creating package structure..."
mkdir -p "$MIXIN_DIR"

echo "==> Backing up $MONO -> $BACKUP"
cp "$MONO" "$BACKUP"

# 1) Extract import block into a shared _imports.py
echo "==> Building shared imports..."
python3 - <<'PY'
import re, sys, io, os, shutil
mono = "govee_mqtt.py"
pkg = "govee_mqtt"
mixins = os.path.join(pkg, "mixins")

with open(mono, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Everything from the top until the *first* "class GoveeMqtt" line (exclusive)
imports = []
for ln in lines:
    if ln.strip().startswith("class GoveeMqtt"):
        break
    # keep only import lines or blank/comment lines from the header
    if ln.startswith("import ") or ln.startswith("from "):
        imports.append(ln)
    elif ln.strip().startswith("#") or ln.strip() == "":
        imports.append(ln)

# De-duplicate while preserving order
seen=set(); cleaned=[]
for ln in imports:
    if ln not in seen:
        cleaned.append(ln); seen.add(ln)

with open(os.path.join(pkg, "_imports.py"), "w", encoding="utf-8") as f:
    f.write("# Auto-generated shared imports from monolith header\n")
    f.writelines(cleaned)
PY

# 2) Split the class body into mixins by section headers
echo "==> Splitting class into mixins..."

python3 - <<'PY'
import os, re

MONO = "govee_mqtt.py"
PKG = "govee_mqtt"
MIXINS = os.path.join(PKG, "mixins")

with open(MONO, "r", encoding="utf-8") as f:
    src = f.readlines()

# Find the class header
cls_pat = re.compile(r'^\s*class\s+GoveeMqtt\s*\(')
cls_idx = None
for i, ln in enumerate(src):
    if cls_pat.match(ln):
        cls_idx = i
        break

if cls_idx is None:
    raise SystemExit("Could not find class GoveeMqtt(...) in govee_mqtt.py")

# Class body starts after the header line
body = src[cls_idx+1:]

# Section markers (ordered). We match lines *containing* these titles.
markers = [
    ("mqtt",              "# MQTT Functions"),
    ("topics",            "# MQTT Topics"),
    ("service",           "# Service Device"),
    ("govee",             "# Govee interactions"),
    ("refresh",           "# refresh all devices"),
    ("helpers",           "# other helpers"),
    ("loops",             "# Background loops"),
]

# Find indices of markers within body
idxs = []
for name, needle in markers:
    found = None
    for i, ln in enumerate(body):
        if needle in ln:
            found = i
            break
    if found is None:
        # If a marker isn't found, still record None; we'll handle gracefully
        idxs.append((name, None))
    else:
        idxs.append((name, found))

# Build ranges:
# base = start of body -> first marker (or end if none)
# then chunk[i] = marker[i] -> marker[i+1]
# loops = last marker -> end
def at(name):
    for n, v in idxs:
        if n == name:
            return v
    return None

positions = [v for _, v in idxs if v is not None]
first_marker = min(positions) if positions else None

chunks = {}
# base chunk
if first_marker is None:
    chunks["base"] = body[:]  # entire body
else:
    chunks["base"] = body[:first_marker]

# subsequent chunks by marker windows
ordered = [n for n,_ in idxs]
for i, (name, pos) in enumerate(idxs):
    if pos is None:
        # create empty chunk placeholder so file gets created
        chunks[name] = []
        continue
    # next valid marker (pos > current)
    nxt = None
    for j in range(i+1, len(idxs)):
        if idxs[j][1] is not None:
            nxt = idxs[j][1]
            break
    if nxt is None:
        chunks[name] = body[pos:]  # until end
    else:
        chunks[name] = body[pos:nxt]

# Helper to write a mixin file
def write_mixin(name, code_lines):
    path = os.path.join(MIXINS, f"{name}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write("from .._imports import *\n\n")
        clsname = name.capitalize() + "Mixin"
        f.write(f"class {clsname}:\n")
        # Ensure there is at least a pass if empty
        payload = code_lines[:]
        # Drop leading comments marker to keep file tidy
        while payload and payload[0].strip().startswith("#"):
            payload.pop(0)
        if not payload:
            f.write("    pass\n")
            return
        # Ensure the block is *already* indented at class level (it was inside original class)
        # If not, indent by 4 spaces as a fallback.
        def already_class_indented(ln):
            return ln.startswith("    ") or ln.strip() == ""
        needs_indent = not all(already_class_indented(ln) for ln in payload if ln.strip())
        if needs_indent:
            payload = ["    " + ln for ln in payload]
        f.writelines(payload)

# Write each mixin
for name, _ in idxs:
    write_mixin(name, chunks.get(name, []))

# Base: everything before first marker (constructor, attributes, helpers defined at top)
write_mixin("base", chunks["base"])

# Generate core.py that composes the full class
core_path = os.path.join(PKG, "core.py")
with open(core_path, "w", encoding="utf-8") as f:
    f.write("from ._imports import *\n")
    f.write("from .mixins.base import BaseMixin\n")
    f.write("from .mixins.mqtt import MqttMixin\n")
    f.write("from .mixins.topics import TopicsMixin\n")
    f.write("from .mixins.service import ServiceMixin\n")
    f.write("from .mixins.govee import GoveeMixin\n")
    f.write("from .mixins.refresh import RefreshMixin\n")
    f.write("from .mixins.helpers import HelpersMixin\n")
    f.write("from .mixins.loops import LoopsMixin\n\n")
    f.write("class GoveeMqtt(BaseMixin, MqttMixin, TopicsMixin, ServiceMixin, GoveeMixin, RefreshMixin, HelpersMixin, LoopsMixin):\n")
    f.write("    pass\n")

# __init__.py to preserve public API
with open(os.path.join(PKG, "__init__.py"), "w", encoding="utf-8") as f:
    f.write("from .core import GoveeMqtt\n")
PY

# 3) Keep the monolith for diffing but stop importing it as top-level module
#    (Users now do: from govee_mqtt import GoveeMqtt)
echo "==> Leaving backup of the original as: $BACKUP"
echo "==> NOTE: Your import stays the same: 'from govee_mqtt import GoveeMqtt'"

# 4) Quick sanity check: can we import the new package?
echo "==> Sanity check: importing package..."
python3 - <<'PY'
import importlib
m = importlib.import_module("govee_mqtt")
print("Imported:", m)
print("Class:", m.GoveeMqtt)
PY

echo "==> Done!"
echo
echo "Next steps:"
echo "  - Run your service exactly as before (imports unchanged)."
echo "  - Commit changes and use 'git diff' to inspect splits."
echo "  - We can now iterate to move/rename specific methods between mixins as desired."

