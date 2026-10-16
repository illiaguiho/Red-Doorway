"""Blender add-on: exports material node trees for game engines.

Phase 0 only writes the JSON intermediate representation (see extract.py);
the compiler and the GLSL/HLSL/Godot backends come next.
"""

import json

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from . import extract


def write_ir(mat, filepath, target="EEVEE"):
    ir = extract.extract_material(mat, target)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(ir, f, indent=2)
    return ir


class SHADEREXPORT_OT_export_ir(bpy.types.Operator, ExportHelper):
    """Write the active material's node tree as JSON for the shader compiler"""
    bl_idname = "shader_export.export_ir"
    bl_label = "Export Node IR"
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    target: EnumProperty(
        name="Output",
        description="Which Material Output node to use when the tree has one per render engine",
        items=[("EEVEE", "EEVEE", ""), ("CYCLES", "Cycles", ""), ("ALL", "All", "")],
        default="EEVEE",
    )

    @classmethod
    def poll(cls, context):
        return getattr(context, "material", None) is not None

    def invoke(self, context, event):
        self.filepath = bpy.path.clean_name(context.material.name) + self.filename_ext
        return super().invoke(context, event)

    def execute(self, context):
        try:
            ir = write_ir(context.material, self.filepath, self.target)
        except extract.ExtractError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        for w in ir["warnings"]:
            self.report({"WARNING"}, w)
        self.report({"INFO"}, f"Exported {len(ir['nodes'])} nodes to {self.filepath}")
        return {"FINISHED"}


class SHADEREXPORT_PT_material(bpy.types.Panel):
    bl_label = "Shader Exporter"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return getattr(context, "material", None) is not None

    def draw(self, context):
        self.layout.operator(SHADEREXPORT_OT_export_ir.bl_idname, icon="EXPORT")


_classes = (SHADEREXPORT_OT_export_ir, SHADEREXPORT_PT_material)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
