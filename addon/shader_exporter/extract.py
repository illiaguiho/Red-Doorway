"""Reads a material's node tree into the JSON intermediate representation (IR).

The IR is a flat, engine-agnostic description of the graph that the compiler
consumes. Extraction removes everything that only matters inside Blender's
editor, so the compiler only ever sees real shading nodes:

- node groups are inlined (inner nodes get keys like "Group/Math")
- reroutes, muted nodes and group input/output nodes are resolved away
- unlinked inputs carry their constant value
- nodes are listed in dependency order (inputs before the nodes using them)

Nothing here decides what is supported: the IR records every node reachable
from the material output, and the compiler reports what it can't translate.
"""

import os

import bpy

IR_FORMAT = "blender-shader-ir"
IR_VERSION = 0

# Node properties that every node has and that don't affect shading.
_BASE_PROPS = {p.identifier for p in bpy.types.ShaderNode.bl_rna.properties} | {"rna_type"}


class ExtractError(Exception):
    pass


# ------------------------------------------------------------------ values

def _value(v):
    """Converts a bpy property value into plain JSON data."""
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    if hasattr(v, "__len__"):
        try:
            return [_value(x) for x in v]
        except TypeError:
            pass
    return str(v)


def _socket_value(socket):
    if not hasattr(socket, "default_value"):
        return None
    return _value(socket.default_value)


def _color_ramp(ramp):
    return {
        "color_mode": ramp.color_mode,
        "interpolation": ramp.interpolation,
        "hue_interpolation": ramp.hue_interpolation,
        "elements": [{"position": e.position, "color": list(e.color)} for e in ramp.elements],
    }


def _curve_mapping(mapping, lut_size=256):
    mapping.initialize()
    curves = []
    for curve in mapping.curves:
        curves.append({
            "points": [{"location": list(p.location), "handle_type": p.handle_type} for p in curve.points],
            # Sampled after black/white levels, so the compiler can use it as a lookup table directly.
            "lut": [mapping.evaluate(curve, i / (lut_size - 1)) for i in range(lut_size)],
        })
    return {
        "curves": curves,
        "clip": [mapping.clip_min_x, mapping.clip_min_y, mapping.clip_max_x, mapping.clip_max_y],
        "black_level": list(mapping.black_level),
        "white_level": list(mapping.white_level),
        "extend": mapping.extend,
    }


def _image(image, warnings, node_key):
    if image is None:
        return None
    path = bpy.path.abspath(image.filepath, library=image.library) if image.filepath else ""
    info = {
        "name": image.name,
        "filepath": image.filepath,
        "abspath": os.path.normpath(path) if path else "",
        "source": image.source,
        "packed": image.packed_file is not None,
        "colorspace": image.colorspace_settings.name,
        "alpha_mode": image.alpha_mode,
        "size": list(image.size),
    }
    if image.source == "FILE" and not info["packed"] and path and not os.path.exists(path):
        warnings.append(f"{node_key}: image file not found: {image.filepath}")
    return info


def _tex_mapping(m):
    return {
        "vector_type": m.vector_type,
        "translation": list(m.translation),
        "rotation": list(m.rotation),
        "scale": list(m.scale),
        "mapping": [m.mapping_x, m.mapping_y, m.mapping_z],
        "use_min": m.use_min, "min": list(m.min),
        "use_max": m.use_max, "max": list(m.max),
    }


def _color_mapping(m):
    return {
        "brightness": m.brightness,
        "contrast": m.contrast,
        "saturation": m.saturation,
        "blend_type": m.blend_type,
        "blend_factor": m.blend_factor,
        "blend_color": list(m.blend_color),
        "use_color_ramp": m.use_color_ramp,
        "color_ramp": _color_ramp(m.color_ramp) if m.use_color_ramp else None,
    }


def _node_props(node, warnings, node_key):
    props = {}
    for prop in node.bl_rna.properties:
        pid = prop.identifier
        if pid in _BASE_PROPS:
            continue
        value = getattr(node, pid, None)
        if prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            props[pid] = sorted(value) if isinstance(value, set) else _value(value)
        elif prop.type == "POINTER":
            kind = prop.fixed_type.identifier
            if value is None:
                props[pid] = None
            elif kind == "ColorRamp":
                props[pid] = _color_ramp(value)
            elif kind == "CurveMapping":
                props[pid] = _curve_mapping(value)
            elif kind == "Image":
                props[pid] = _image(value, warnings, node_key)
            elif kind == "TexMapping":
                props[pid] = _tex_mapping(value)
            elif kind == "ColorMapping":
                props[pid] = _color_mapping(value)
            elif kind in {"Object", "Text"}:
                props[pid] = value.name
            # ImageUser, NodeTree (inlined) and others carry nothing the compiler needs.
    return props


# ------------------------------------------------------------------ graph

class _Scope:
    """One level of node-group nesting: the tree, the group node that
    instantiated it (None at the root) and the parent scope."""

    def __init__(self, tree, group_node=None, parent=None):
        self.tree = tree
        self.group_node = group_node
        self.parent = parent
        self.prefix = "" if parent is None else parent.prefix + group_node.name + "/"

    def key(self, node):
        return self.prefix + node.name


def _active_group_output(tree):
    outputs = [n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"]
    for n in outputs:
        if n.is_active_output:
            return n
    return outputs[0] if outputs else None


def _incoming(socket):
    for link in socket.links:
        if link.is_valid and not link.is_muted:
            return link
    return None


class _Extractor:
    def __init__(self):
        self.nodes = {}     # key -> IR node, in dependency order (dicts keep insertion order)
        self.visiting = set()
        self.warnings = []

    # Follows a link source back to a real node output, or to a constant.
    def resolve(self, scope, node, socket, depth=0):
        if depth > 256:
            raise ExtractError(f"link chain too deep at {scope.key(node)}")
        kind = node.bl_idname

        if kind == "NodeReroute":
            link = _incoming(node.inputs[0])
            return self.resolve(scope, link.from_node, link.from_socket, depth + 1) if link else None

        if kind == "NodeGroupInput":
            if scope.group_node is None:
                return None
            outer = next((s for s in scope.group_node.inputs if s.identifier == socket.identifier), None)
            return self.resolve_input(scope.parent, outer, depth + 1) if outer else None

        if kind == "ShaderNodeGroup":
            tree = node.node_tree
            out_node = _active_group_output(tree) if tree else None
            if out_node is None:
                self.warnings.append(f"{scope.key(node)}: group has no output node")
                return None
            inner = _Scope(tree, node, scope)
            target = next((s for s in out_node.inputs if s.identifier == socket.identifier), None)
            return self.resolve_input(inner, target, depth + 1) if target else None

        if node.mute:
            for il in node.internal_links:
                if il.to_socket == socket:
                    return self.resolve_input(scope, il.from_socket, depth + 1)
            return None

        key = self.visit(scope, node)
        return {"node": key, "output": socket.identifier}

    # Value feeding one input socket: a link to a node output, or a constant.
    def resolve_input(self, scope, socket, depth=0):
        link = _incoming(socket)
        if link is None:
            v = _socket_value(socket)
            return None if v is None else {"value": v}
        src = self.resolve(scope, link.from_node, link.from_socket, depth)
        if src is None:
            # Linked to nothing usable (empty reroute, muted node without
            # pass-through): Blender then uses the socket's own value.
            v = _socket_value(socket)
            return None if v is None else {"value": v}
        if "node" in src:
            src["from_type"] = link.from_socket.type
        return src

    def visit(self, scope, node):
        key = scope.key(node)
        if key in self.nodes:
            return key
        if key in self.visiting:
            raise ExtractError(f"cycle in node graph at {key}")
        self.visiting.add(key)

        inputs = []
        for s in node.inputs:
            if not s.enabled:
                continue
            entry = {"name": s.name, "identifier": s.identifier, "type": s.type}
            source = self.resolve_input(scope, s)
            if source is not None:
                entry.update(source)
            inputs.append(entry)

        self.visiting.discard(key)
        self.nodes[key] = {
            "key": key,
            "type": node.bl_idname,
            "name": node.name,
            "label": node.label,
            "props": _node_props(node, self.warnings, key),
            "inputs": inputs,
            "outputs": [{"name": s.name, "identifier": s.identifier, "type": s.type}
                        for s in node.outputs if s.enabled],
        }
        return key


def _material_settings(mat):
    settings = {"use_backface_culling": mat.use_backface_culling}
    for attr in ("surface_render_method", "blend_method", "alpha_threshold", "use_transparency_overlap"):
        if hasattr(mat, attr):
            settings[attr] = _value(getattr(mat, attr))
    return settings


def uses_nodes(mat):
    # Blender 5.0 made node trees mandatory and deprecated `use_nodes`.
    if bpy.app.version < (5, 0, 0) and not mat.use_nodes:
        return False
    return mat.node_tree is not None


def extract_material(mat, target="EEVEE"):
    """Returns the IR dict for one material. `target` picks which Material
    Output node is used when the tree has per-engine outputs."""
    if not uses_nodes(mat):
        raise ExtractError(f"material '{mat.name}' does not use nodes")
    tree = mat.node_tree
    out = tree.get_output_node(target) or tree.get_output_node("ALL")
    if out is None:
        raise ExtractError(f"material '{mat.name}' has no active Material Output node")

    ex = _Extractor()
    output_key = ex.visit(_Scope(tree), out)
    return {
        "format": IR_FORMAT,
        "version": IR_VERSION,
        "blender_version": bpy.app.version_string,
        "material": {"name": mat.name, "settings": _material_settings(mat)},
        "output": output_key,
        "nodes": list(ex.nodes.values()),
        "warnings": ex.warnings,
    }
