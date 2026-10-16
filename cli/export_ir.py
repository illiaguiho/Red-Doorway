"""Exports material node trees as JSON IR without opening Blender's UI.

    blender -b scene.blend --factory-startup --python cli/export_ir.py -- OUT_DIR [MATERIAL ...]

With no material names, every material that uses nodes is exported.
Writes OUT_DIR/<material>.json and exits non-zero if any export failed.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "addon"))

import bpy  # noqa: E402

from shader_exporter import extract, write_ir  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not args:
    print(__doc__)
    sys.exit(2)

out_dir, names = args[0], args[1:]
os.makedirs(out_dir, exist_ok=True)

materials = [bpy.data.materials[n] for n in names] if names else [m for m in bpy.data.materials if extract.uses_nodes(m)]
failed = 0
for mat in materials:
    path = os.path.join(out_dir, bpy.path.clean_name(mat.name) + ".json")
    try:
        ir = write_ir(mat, path)
    except extract.ExtractError as e:
        print(f"ERROR {mat.name}: {e}")
        failed += 1
        continue
    for w in ir["warnings"]:
        print(f"WARN {mat.name}: {w}")
    print(f"OK {mat.name}: {len(ir['nodes'])} nodes -> {path}")

sys.exit(1 if failed else 0)
