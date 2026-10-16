# Blender GLSL/HLSL Exporter
```
Author: Elivi Guiho
Date: 16/10/2026
Name: Red Doorway*
```
## Description

A Blender add-on that turns material node trees into shader code for game
engines: GLSL (Blurres, OpenGL), HLSL (Unity, Unreal, DirectX) and Godot
shading language.

It doesn't try to reproduce Cycles or EEVEE lighting. A material is compiled
into a *surface function* that fills in the engine's own PBR inputs (base
colour, metallic, roughness, normal, emission, alpha), and the engine does the
lighting. Nodes that can't run in a fragment shader (Ambient Occlusion, Bevel,
Light Path...) are baked to textures instead, and every export says which
nodes were compiled, approximated or baked.

## Goal

- Procedural materials made in Blender work in-engine without baking:
  animated, world-space and tweakable effects, at any resolution.
- Generated code is readable: one line per node, constants folded and unused
  branches removed. Inputs the artist marks become uniforms.
- Blurres gets a live link: saving the `.blend` recompiles its shaders.

## Stack

- **Add-on:** Python, Blender 4.2+ extension format (tested on 5.1), no dependencies.
- **Pipeline:** Blender node tree → JSON IR → compiler (optimiser) → language backends.
  The IR is the stable contract between the parts.
- **Validation:** [glslang](https://github.com/KhronosGroup/glslang) for compile checks.
  Bake-and-compare image tests against Blender come in Phase 2.

### Layout

| Path | What it is |
|---|---|
| `addon/shader_exporter/` | The add-on. `extract.py` reads node trees into the IR. |
| `cli/export_ir.py` | Headless export of every material in a `.blend`. |
| `tests/test_extract.py` | Extraction tests (run inside Blender). |
| `tools/validate_blurres.py` | Compiles a Blurres shader + surface with glslang. |
| `examples/` | The reference "Stripes" material: `.blend`, IR, and its hand-written Blurres surface. |

### Usage

Install: zip `addon/shader_exporter/` and use *Edit > Preferences > Get Extensions >
Install from Disk*. The exporter is in *Material Properties > Shader Exporter*.

```sh
# export every material of a .blend as IR
blender -b scene.blend --factory-startup --python cli/export_ir.py -- out/

# run the tests (also refreshes examples/stripes.blend and stripes.json)
blender -b --factory-startup --python tests/test_extract.py

# check that a surface compiles inside Blurres' PBR shader
python tools/validate_blurres.py <blurres>/resources/shaders/pbr.glsl --surface examples/blurres/Stripes.surface.glsl --glslang <path to glslang.exe>
```

### The IR

`examples/stripes.json` is a full example. Node groups are inlined (inner
nodes are keyed `Group/Node`). Reroutes, muted nodes and group inputs/outputs
are resolved away. Nodes are listed so each one comes after its inputs. Each
input is either linked, as `{"node", "output", "from_type"}`, or a constant
`{"value"}`.

### Blurres (own game engine) integration

A Blurres material can set `"surfaceShader": "Assets/Shaders/X.surface.glsl"`.
That file defines `Surface EvaluateSurface(SurfaceInput i)` and replaces the
default `resources/shaders/surface.glsl` inside `pbr.glsl`. See
`examples/blurres/` for an example.

## Progress

- [x] **Phase 0:** node tree → JSON IR (groups, reroutes, muted nodes), headless CLI,
      Blurres `surface()` hook, hand-written reference surface
- [ ] **Phase 1:** compiler + GLSL backend, Tier 1 nodes, Blurres live link
- [ ] **Phase 2:** bake-and-compare test harness
- [ ] **Phase 3:** HLSL and Godot backends, Unity/Unreal/Godot wrappers
- [ ] **Phase 4:** procedural textures (Noise, Voronoi, Wave...), written from scratch
- [ ] **Phase 5:** automatic baking of unsupported subgraphs

<!-- ## Copyright -->

*placeholder name
