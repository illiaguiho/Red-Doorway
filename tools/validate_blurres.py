"""Compiles a Blurres shader offline with glslang, the way the engine builds it.

    python tools/validate_blurres.py PBR_GLSL [--surface FILE.glsl] [--glslang PATH]

Expands `#include` lines like blurres::Shader::Reload (one level, next to the
shader, with surface.glsl optionally swapped for FILE.glsl), splits the
`#type vertex` / `#type fragment` sections, prepends `#version 410 core` and
runs glslang on each stage. glslang is looked up in --glslang, $GLSLANG, then PATH.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile


def expand(path, includes):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#include"):
                name = line[line.index('"') + 1:line.rindex('"')]
                inc = includes.get(name, os.path.join(os.path.dirname(path), name))
                with open(inc, encoding="utf-8") as g:
                    out.append(g.read() + "\n")
            else:
                out.append(line)
    return "".join(out)


def split_stages(text):
    stages, current = {}, None
    for line in text.splitlines(keepends=True):
        if line.startswith("#type"):
            current = line.split()[1]
            stages[current] = []
        elif current:
            stages[current].append(line)
    return {k: "".join(v) for k, v in stages.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shader")
    ap.add_argument("--surface")
    ap.add_argument("--glslang", default=os.environ.get("GLSLANG") or shutil.which("glslang") or shutil.which("glslangValidator"))
    a = ap.parse_args()
    if not a.glslang:
        sys.exit("glslang not found: pass --glslang or set GLSLANG")

    includes = {"surface.glsl": a.surface} if a.surface else {}
    stages = split_stages(expand(a.shader, includes))
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for stage, ext in (("vertex", "vert"), ("fragment", "frag")):
            src = os.path.join(tmp, f"shader.{ext}")
            with open(src, "w", encoding="utf-8") as f:
                f.write("#version 410 core\n" + stages[stage])
            r = subprocess.run([a.glslang, src], capture_output=True, text=True)
            ok &= r.returncode == 0
            print(f"{stage}: {'OK' if r.returncode == 0 else 'FAILED'}")
            if r.returncode != 0:
                print(r.stdout.replace(src, f"<{stage}>"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
