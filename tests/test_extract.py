"""Extraction tests. Runs inside Blender:

    blender -b --factory-startup --python tests/test_extract.py

Builds the reference "Stripes" material from code, extracts it and checks the
IR. Also refreshes examples/stripes.blend and examples/stripes.json, which the
hand-written Blurres surface in examples/blurres/ reproduces.
"""

import json
import os
import sys
import traceback

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "addon"))

import bpy  # noqa: E402

from shader_exporter import extract  # noqa: E402


# ------------------------------------------------------------------ fixtures

def new_material(name):
    mat = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    return mat


def make_wave_group():
    """Group "Wave": X -> sin(X * pi) * 0.5 + 0.5"""
    g = bpy.data.node_groups.new("Wave", "ShaderNodeTree")
    g.interface.new_socket("X", in_out="INPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("Wave", in_out="OUTPUT", socket_type="NodeSocketFloat")
    n = g.nodes
    gin, gout = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    mul = n.new("ShaderNodeMath"); mul.name = "Scale"; mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 3.14159265
    sin = n.new("ShaderNodeMath"); sin.name = "Sine"; sin.operation = "SINE"
    remap = n.new("ShaderNodeMath"); remap.name = "Remap"; remap.operation = "MULTIPLY_ADD"
    remap.inputs[1].default_value = 0.5
    remap.inputs[2].default_value = 0.5
    g.links.new(gin.outputs["X"], mul.inputs[0])
    g.links.new(mul.outputs[0], sin.inputs[0])
    g.links.new(sin.outputs[0], remap.inputs[0])
    g.links.new(remap.outputs[0], gout.inputs["Wave"])
    return g


def make_stripes():
    mat = new_material("Stripes")
    t = mat.node_tree
    n, L = t.nodes, t.links
    bsdf = n["Principled BSDF"]

    coord = n.new("ShaderNodeTexCoord")
    mapping = n.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (8.0, 8.0, 1.0)
    sep = n.new("ShaderNodeSeparateXYZ")
    wave = n.new("ShaderNodeGroup"); wave.name = "Wave"; wave.node_tree = make_wave_group()

    ramp = n.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.25, 0.05, 0.04, 1.0)
    ramp.color_ramp.elements[1].position = 0.5
    ramp.color_ramp.elements[1].color = (0.9, 0.8, 0.6, 1.0)

    hue = n.new("ShaderNodeHueSaturation"); hue.mute = True   # must vanish, passing the colour through
    rng = n.new("ShaderNodeMapRange")
    rng.inputs["To Min"].default_value = 0.7
    rng.inputs["To Max"].default_value = 0.3
    reroute = n.new("NodeReroute")                             # must vanish
    bump = n.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.4
    bump.inputs["Distance"].default_value = 0.05

    L.new(coord.outputs["UV"], mapping.inputs["Vector"])
    L.new(mapping.outputs["Vector"], sep.inputs["Vector"])
    L.new(sep.outputs["X"], wave.inputs["X"])
    L.new(wave.outputs["Wave"], ramp.inputs["Fac"])
    L.new(ramp.outputs["Color"], hue.inputs["Color"])
    L.new(hue.outputs["Color"], bsdf.inputs["Base Color"])
    L.new(wave.outputs["Wave"], rng.inputs["Value"])
    L.new(rng.outputs["Result"], bsdf.inputs["Roughness"])
    L.new(wave.outputs["Wave"], reroute.inputs[0])
    L.new(reroute.outputs[0], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# ------------------------------------------------------------------ tests

def by_key(ir):
    return {node["key"]: node for node in ir["nodes"]}


def input_of(node, name):
    return next(i for i in node["inputs"] if i["name"] == name)


def test_stripes(ir):
    nodes = by_key(ir)
    types = {node["type"] for node in ir["nodes"]}
    for gone in ("NodeReroute", "ShaderNodeGroup", "NodeGroupInput", "NodeGroupOutput", "ShaderNodeHueSaturation"):
        assert gone not in types, f"{gone} should have been resolved away"

    assert ir["output"] == "Material Output"
    assert ir["nodes"][-1]["key"] == "Material Output", "output must come last (dependency order)"
    order = [node["key"] for node in ir["nodes"]]
    for node in ir["nodes"]:
        for i in node["inputs"]:
            if "node" in i:
                assert order.index(i["node"]) < order.index(node["key"]), f"{node['key']} listed before its input {i['node']}"

    bsdf = nodes["Principled BSDF"]
    assert input_of(bsdf, "Base Color")["node"] == "Color Ramp", "muted Hue/Saturation should pass the ramp through"
    assert input_of(bsdf, "Roughness")["node"] == "Map Range"
    assert input_of(bsdf, "Normal")["node"] == "Bump"
    assert input_of(bsdf, "Metallic")["value"] == 0.0

    assert input_of(nodes["Bump"], "Height") == {
        "name": "Height", "identifier": "Height", "type": "VALUE",
        "node": "Wave/Remap", "output": "Value", "from_type": "VALUE",
    }, "reroute should resolve to the group's last node"
    assert input_of(nodes["Wave/Scale"], "Value")["node"] == "Separate XYZ", "group input should resolve to the outer link"
    assert input_of(nodes["Wave/Scale"], "Value")["output"] == "X"
    assert abs(input_of(nodes["Mapping"], "Scale")["value"][0] - 8.0) < 1e-6

    ramp = nodes["Color Ramp"]["props"]["color_ramp"]
    assert ramp["interpolation"] == "LINEAR" and len(ramp["elements"]) == 2
    assert nodes["Wave/Remap"]["props"]["operation"] == "MULTIPLY_ADD"
    assert nodes["Texture Coordinate"]["type"] == "ShaderNodeTexCoord"
    assert ir["warnings"] == []


def test_unlinked_reroute_uses_socket_value():
    mat = new_material("LooseReroute")
    t = mat.node_tree
    bsdf = t.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.25
    r = t.nodes.new("NodeReroute")
    t.links.new(r.outputs[0], bsdf.inputs["Roughness"])
    ir = extract.extract_material(mat)
    assert input_of(by_key(ir)["Principled BSDF"], "Roughness")["value"] == 0.25


def test_missing_output_raises():
    mat = new_material("NoOutput")
    mat.node_tree.nodes.remove(mat.node_tree.nodes["Material Output"])
    try:
        extract.extract_material(mat)
    except extract.ExtractError:
        return
    raise AssertionError("expected ExtractError")


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    stripes = make_stripes()
    ir = extract.extract_material(stripes)
    json.dumps(ir)  # must be serialisable

    failures = 0
    tests = [("stripes", lambda: test_stripes(ir)),
             ("unlinked reroute", test_unlinked_reroute_uses_socket_value),
             ("missing output", test_missing_output_raises)]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()

    if not failures:
        examples = os.path.join(ROOT, "examples")
        os.makedirs(examples, exist_ok=True)
        with open(os.path.join(examples, "stripes.json"), "w", encoding="utf-8") as f:
            json.dump(ir, f, indent=2)
        for m in [m for m in bpy.data.materials if m != stripes]:
            bpy.data.materials.remove(m)
        bpy.ops.mesh.primitive_plane_add()
        bpy.context.active_object.data.materials.append(stripes)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(examples, "stripes.blend"), compress=True)

    print(f"{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


main()
