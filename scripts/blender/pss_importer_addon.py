#!/usr/bin/env python3
"""
PSS Importer Addon v2.0 - Factum Arte / Factum Foundation
Importa escaneos photometric-stereo en Blender a partir de 4 imagenes.
"""

bl_info = {
    "name":        "Selene PSS",
    "author":      "Factum Arte / Factum Foundation",
    "version":     (2, 4, 2),
    "blender":     (3, 0, 0),
    "location":    "View3D > Sidebar > PSS",
    "description": "Import photometric stereo scans into Blender (depth, albedo, normal, alpha)",
    "category":    "Import-Export",
}

import bpy
import os
import numpy as np
from bpy.props import (
    StringProperty, FloatProperty, EnumProperty, BoolProperty,
)
from bpy.types import Operator, Panel, PropertyGroup


# ---------------------------------------------------------------------------
# PROPERTIES
# ---------------------------------------------------------------------------

class PSSProperties(PropertyGroup):

    # Imagenes de entrada
    # subtype='NONE' intentional: FILE_PATH would add Blender's own folder
    # button, duplicating our custom browse operator button in the UI.
    path_depth: StringProperty(
        name="Depth map",
        description="32-bit float grayscale TIFF (depth map in metres)",
        default="",
    )
    path_albedo: StringProperty(
        name="Albedo",
        description="16-bit RGB TIFF",
        default="",
    )
    path_normal: StringProperty(
        name="Normal map",
        description="16-bit RGB TIFF",
        default="",
    )
    path_alpha: StringProperty(
        name="Alpha (optional)",
        description="8-bit PNG",
        default="",
    )

    size_mode: EnumProperty(
        name="Size mode",
        items=[
            ('WH',  "W / H",  "Enter real-world width and height in cm"),
            ('DPI', "DPI",    "Calculate size from image resolution and scan DPI"),
        ],
        default='WH',
    )
    width_cm: FloatProperty(
        name="Width (cm)", default=14.0, min=0.01, precision=3,
    )
    height_cm: FloatProperty(
        name="Height (cm)", default=16.0, min=0.01, precision=3,
    )
    dpi: FloatProperty(
        name="DPI", default=600.0, min=1.0, precision=1,
        description="Scanner resolution in dots per inch (dpi). Real-world size = pixels / dpi × 2.54 cm",
    )

    quality: EnumProperty(
        name="Quality",
        items=[
            ('LOW',   "Low",        "Fast, low geometric resolution (n=64)"),
            ('MED',   "Medium",     "Balanced (n=32)"),
            ('HIGH',  "High",       "High resolution (n=16)"),
            ('ULTRA', "Ultra High", "Maximum detail, may be slow (n=8)"),
        ],
        default='MED',
    )

    # Ultimo directorio usado en el file browser (se propaga entre slots)
    last_dir: StringProperty(default="")

    # Resultados (rellenados tras el proceso)
    result_x_cm:    FloatProperty(default=0.0)
    result_y_cm:    FloatProperty(default=0.0)
    result_z_mm:    FloatProperty(default=0.0)
    result_z_min_m: FloatProperty(default=0.0)
    result_z_max_m: FloatProperty(default=0.0)
    result_ok:      BoolProperty(default=False)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

QUALITY_N = {'LOW': 64, 'MED': 32, 'HIGH': 16, 'ULTRA': 8}


def _progress(wm, step, total, label):
    """Actualiza barra de progreso del header y la consola."""
    pct = int(step / total * 100)
    wm.progress_update(pct)
    print(f"[INFO] ({pct:3d}%) {label}")


def _load_image(path, name, colorspace='Non-Color'):
    """Carga imagen en Blender, configura colorspace y devuelve el objeto."""
    img = bpy.data.images.load(bpy.path.abspath(path), check_existing=False)
    img.name = name
    img.colorspace_settings.name = colorspace
    return img


def _convert_depth_32f_to_16b(path_in):
    """
    Loads a 32-bit float TIFF depth map, applies linear min-max stretch,
    saves the result as a 16-bit grayscale TIFF next to the source file,
    then loads it back from disk.

    The Blender Displace modifier uses the legacy texture system which only
    reads images reliably when loaded from disk — in-memory packed images
    do not work with it.

    Returns: (img_disp, depth_range_mm, d_min_m, d_max_m)
    """
    abs_in = bpy.path.abspath(path_in)
    img32  = bpy.data.images.load(abs_in, check_existing=False)
    img32.name = "_pss_depth_32f_tmp"
    # CRITICAL: set Non-Color BEFORE reading pixels.
    # Without this, Blender applies an sRGB->linear transform to the float values,
    # giving pixel values ~13x smaller than the actual metres stored in the TIFF.
    img32.colorspace_settings.name = 'Non-Color'
    w, h = img32.size

    if not img32.is_float:
        bpy.data.images.remove(img32)
        raise ValueError("Depth map is not 32-bit float")

    # Extract R channel; flip vertically (Blender origin = bottom-left)
    px    = np.array(img32.pixels[:], dtype=np.float32).reshape((h, w, 4))
    depth = np.flipud(px[:, :, 0])
    bpy.data.images.remove(img32)

    d_min     = float(depth.min())
    d_max     = float(depth.max())
    d_range_m = d_max - d_min
    if d_range_m == 0.0:
        raise ValueError("Depth map is constant (range = 0), cannot process")

    # Linear stretch to 0..1 (float32)
    norm = (depth - d_min) / d_range_m

    # Save as 16-bit grayscale TIFF next to the source file
    base      = os.path.splitext(abs_in)[0]
    path_out  = base + "_disp16b.tif"

    img_out = bpy.data.images.new("_pss_depth_out_tmp", width=w, height=h,
                                   alpha=False, float_buffer=False)
    rgba = np.zeros((h, w, 4), dtype=np.float32)
    rgba[:, :, 0] = np.flipud(norm)   # flip back to Blender orientation
    rgba[:, :, 1] = rgba[:, :, 0]
    rgba[:, :, 2] = rgba[:, :, 0]
    rgba[:, :, 3] = 1.0
    img_out.pixels = rgba.flatten().tolist()

    scene = bpy.context.scene
    cfg   = scene.render.image_settings
    prev_fmt   = (cfg.file_format, cfg.color_depth, cfg.color_mode)
    prev_vt    = scene.view_settings.view_transform

    cfg.file_format = 'TIFF'
    cfg.color_depth = '16'
    cfg.color_mode  = 'BW'
    # 'Raw' bypasses Filmic/AgX tone mapping — otherwise pixel values are
    # compressed and the displacement Z scale comes out completely wrong.
    scene.view_settings.view_transform = 'Raw'
    img_out.save_render(filepath=path_out)

    cfg.file_format, cfg.color_depth, cfg.color_mode = prev_fmt
    scene.view_settings.view_transform = prev_vt
    bpy.data.images.remove(img_out)

    # Load from disk — required for the Displace modifier legacy texture system
    img_disp = bpy.data.images.load(path_out, check_existing=False)
    img_disp.name = "PSS_depth_disp"
    img_disp.colorspace_settings.name = 'Non-Color'

    print(f"[INFO] Depth range: {d_min:.5f} m -> {d_max:.5f} m  ({d_range_m * 1000:.3f} mm)")
    print(f"[INFO] Displacement TIFF saved: {path_out}")
    return img_disp, d_range_m * 1000.0, d_min, d_max


def _build_scene(width_cm, height_cm, depth_range_mm, n,
                 img_depth, img_albedo, img_normal, img_alpha, wm):
    """Construye el objeto PSS completo en la escena."""

    STEPS = 6

    # 1. Clear scene + force metric units (1 Blender unit = 1 metre)
    _progress(wm, 1, STEPS, "Clearing scene...")
    bpy.context.scene.unit_settings.system       = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = 1.0
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)

    # 2. Create plane - sized in metres, scale applied immediately
    _progress(wm, 2, STEPS, "Building geometry...")
    sx = max(1, int(img_depth.size[0] / n)) if img_depth else int(8000 / n)
    sy = max(1, int(img_depth.size[1] / n)) if img_depth else int(8000 / n)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=sx, y_subdivisions=sy,
                                    size=2, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "PSS_Object"

    # Set real-world dimensions (metres). Z=0 is safe for a flat grid.
    w_m = width_cm  / 100.0
    h_m = height_cm / 100.0
    plane.dimensions = (w_m, h_m, 0.0)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.shade_smooth()
    print(f"[INFO] Grid: {sx}x{sy} subdivisions  |  size: {width_cm:.3f} x {height_cm:.3f} cm  ({w_m:.4f} x {h_m:.4f} m)")

    # 3. Displacement
    # mid_level=0.0 : texture=0 -> Z=0 (scan floor), texture=1 -> Z=+strength
    # strength = depth_range_m : full Z range in metres, no factor needed.
    _progress(wm, 3, STEPS, "Setting up displacement...")
    subdiv = plane.modifiers.new("Subdivision", type='SUBSURF')
    subdiv.levels = 1
    subdiv.render_levels = 2

    tex = bpy.data.textures.new("PSS_Depth_Tex", type='IMAGE')
    tex.image = img_depth

    disp = plane.modifiers.new("Displace", type='DISPLACE')
    disp.texture        = tex
    disp.texture_coords = 'UV'
    disp.strength       = depth_range_mm / 1000.0  # mm -> m
    disp.mid_level      = 0.0   # floor of scan at Z=0, relief rises upward
    print(f"[INFO] Displacement: strength={disp.strength*1000:.3f} mm  mid_level={disp.mid_level}")

    # 4. Material
    _progress(wm, 4, STEPS, "Creating material...")
    mat = bpy.data.materials.new("PSS_Material")
    mat.use_nodes = True
    plane.data.materials.append(mat)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out  = nodes.new('ShaderNodeOutputMaterial'); out.location  = (400, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (0, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    def tex_node(img, label, loc, colorspace='Non-Color'):
        n = nodes.new('ShaderNodeTexImage')
        n.image = img; n.label = label; n.location = loc
        n.image.colorspace_settings.name = colorspace
        return n

    if img_albedo:
        tn = tex_node(img_albedo, "Albedo", (-400, 300), 'sRGB')
        links.new(tn.outputs['Color'], bsdf.inputs['Base Color'])

    if img_normal:
        tn = tex_node(img_normal, "Normal", (-400, 0))
        nm = nodes.new('ShaderNodeNormalMap'); nm.location = (-150, 0)
        links.new(tn.outputs['Color'], nm.inputs['Color'])
        links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])

    if img_alpha:
        tn = tex_node(img_alpha, "Alpha", (-400, -300))
        links.new(tn.outputs['Color'], bsdf.inputs['Alpha'])
        mat.blend_method           = 'BLEND'
        mat.show_transparent_back  = False

    # 5. Basic lighting
    _progress(wm, 5, STEPS, "Setting up lighting...")
    bpy.ops.object.camera_add(location=(0, -0.5, 0.3), rotation=(1.1, 0, 0))
    bpy.ops.object.light_add(type='AREA', location=(0, 0, 0.5))
    bpy.context.active_object.data.energy = 50
    bpy.ops.object.light_add(type='AREA', location=(0.2, -0.2, 0.3))
    bpy.context.active_object.data.energy = 30

    # 6. Final view
    _progress(wm, 6, STEPS, "Adjusting viewport...")
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'

    bpy.context.view_layer.objects.active = plane
    plane.select_set(True)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D': continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if not region: continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_selected()
            break

    return plane


# ---------------------------------------------------------------------------
# OPERADORES DE SELECCION DE ARCHIVO  (propagan el directorio entre slots)
# ---------------------------------------------------------------------------

def _make_browse_op(idname, label, prop_name, glob="*.tif;*.tiff;*.png"):
    """Fabrica un operador file-browser que recuerda el ultimo directorio."""

    class _BrowseOp(Operator):
        bl_idname  = idname
        bl_label   = label
        bl_options = {'REGISTER', 'INTERNAL'}

        filepath:    bpy.props.StringProperty(subtype='FILE_PATH')
        filter_glob: bpy.props.StringProperty(default=glob, options={'HIDDEN'})

        def invoke(self, context, event):
            props = context.scene.pss_props
            # Preset: directorio del slot actual, o last_dir, o home
            current = getattr(props, prop_name, "")
            if current and os.path.exists(bpy.path.abspath(current)):
                self.filepath = bpy.path.abspath(current)
            elif props.last_dir and os.path.isdir(props.last_dir):
                self.filepath = props.last_dir + os.sep
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

        def execute(self, context):
            props = context.scene.pss_props
            setattr(props, prop_name, self.filepath)
            # Actualizar last_dir para los siguientes slots
            d = os.path.dirname(bpy.path.abspath(self.filepath))
            if os.path.isdir(d):
                props.last_dir = d
            return {'FINISHED'}

    _BrowseOp.__name__ = idname.replace(".", "_").upper()
    return _BrowseOp


PSS_OT_BrowseDepth  = _make_browse_op("pss.browse_depth",  "Select depth map",  "path_depth",  "*.tif;*.tiff")
PSS_OT_BrowseAlbedo = _make_browse_op("pss.browse_albedo", "Select albedo",      "path_albedo", "*.tif;*.tiff")
PSS_OT_BrowseNormal = _make_browse_op("pss.browse_normal", "Select normal map",  "path_normal", "*.tif;*.tiff")
PSS_OT_BrowseAlpha  = _make_browse_op("pss.browse_alpha",  "Select alpha mask",  "path_alpha",  "*.png")


# ---------------------------------------------------------------------------
# OPERADOR PRINCIPAL
# ---------------------------------------------------------------------------

class PSS_OT_Process(Operator):
    """Processes the images and builds the 3D model in Blender"""
    bl_idname  = "pss.process"
    bl_label   = "Process scan"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.pss_props
        wm    = context.window_manager
        props.result_ok = False

        if not props.path_depth:
            self.report({'ERROR'}, "Depth map is required (32-bit float TIFF)")
            return {'CANCELLED'}
        if not os.path.exists(bpy.path.abspath(props.path_depth)):
            self.report({'ERROR'}, f"File not found: {props.path_depth}")
            return {'CANCELLED'}

        wm.progress_begin(0, 100)
        print("\n=== PSS IMPORTER v2.0 - START ===")

        try:
            # STEP 1: Convert depth map 32-bit -> 16-bit
            _progress(wm, 0, 10, "Loading 32-bit depth map...")
            img_depth, range_mm, d_min, d_max = _convert_depth_32f_to_16b(
                props.path_depth
            )
            print(f"[INFO] Depth: min={d_min:.5f} m  max={d_max:.5f} m  range={range_mm:.3f} mm")
            self.report({'INFO'}, f"Depth processed: range={range_mm:.3f} mm")

            # STEP 2: Load albedo
            img_albedo = None
            if props.path_albedo and os.path.exists(bpy.path.abspath(props.path_albedo)):
                _progress(wm, 2, 10, "Loading albedo...")
                img_albedo = _load_image(props.path_albedo, "PSS_albedo", 'sRGB')
            else:
                print("[WARN] Albedo not specified or not found")

            # STEP 3: Load normal map
            img_normal = None
            if props.path_normal and os.path.exists(bpy.path.abspath(props.path_normal)):
                _progress(wm, 4, 10, "Loading normal map...")
                img_normal = _load_image(props.path_normal, "PSS_normal")
            else:
                print("[WARN] Normal map not specified or not found")

            # STEP 4: Load alpha (optional)
            img_alpha = None
            if props.path_alpha and os.path.exists(bpy.path.abspath(props.path_alpha)):
                _progress(wm, 5, 10, "Loading alpha mask...")
                img_alpha = _load_image(props.path_alpha, "PSS_alpha")

            # STEP 5: Build scene
            _progress(wm, 6, 10, "Building 3D model...")
            n = QUALITY_N[props.quality]
            if props.size_mode == 'DPI':
                px_w, px_h = img_depth.size
                width_cm  = px_w / props.dpi * 2.54
                height_cm = px_h / props.dpi * 2.54
                print(f"[INFO] DPI mode: {px_w}x{px_h} px @ {props.dpi} dpi -> {width_cm:.3f} x {height_cm:.3f} cm")
            else:
                width_cm  = props.width_cm
                height_cm = props.height_cm
            _build_scene(
                width_cm      = width_cm,
                height_cm     = height_cm,
                depth_range_mm= range_mm,
                n             = n,
                img_depth     = img_depth,
                img_albedo    = img_albedo,
                img_normal    = img_normal,
                img_alpha     = img_alpha,
                wm            = wm,
            )

            props.result_x_cm    = props.width_cm
            props.result_y_cm    = props.height_cm
            props.result_z_mm    = range_mm
            props.result_z_min_m = d_min
            props.result_z_max_m = d_max
            props.result_ok      = True

            wm.progress_update(100)
            print("=== PSS IMPORTER v2.0 - DONE ===\n")
            self.report({'INFO'}, f"[OK] Object: {props.width_cm:.1f} x {props.height_cm:.1f} cm, Z={range_mm:.3f} mm")

        except Exception as e:
            self.report({'ERROR'}, str(e))
            print(f"[ERROR] {e}")
            wm.progress_end()
            return {'CANCELLED'}

        wm.progress_end()
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# PANEL UI
# ---------------------------------------------------------------------------

class PSS_PT_Panel(Panel):
    bl_label       = "PSS Importer"
    bl_idname      = "PSS_PT_main"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'PSS'

    def draw(self, context):
        layout = self.layout
        props  = context.scene.pss_props

        # Version header
        v = bl_info["version"]
        row = layout.row()
        row.label(text=f"Selene PSS  v{v[0]}.{v[1]}.{v[2]}", icon='OUTLINER_DATA_MESH')
        layout.separator(factor=0.5)

        box = layout.box()
        row = box.row()
        row.label(text="Images", icon='IMAGE_DATA')
        row.operator("pss.clear_slots", text="", icon='X')

        def file_row(parent, path_prop, browse_op, label, required=True):
            row = parent.row(align=True)
            row.prop(props, path_prop, text=label)
            row.operator(browse_op, text="", icon='FILE_FOLDER')
            val = getattr(props, path_prop, "")
            if val and os.path.exists(bpy.path.abspath(val)):
                row.label(text="", icon='CHECKMARK')
            elif required and not val:
                row.label(text="", icon='ERROR')

        file_row(box, "path_depth",  "pss.browse_depth",  "Depth (32-bit)",  required=True)
        file_row(box, "path_albedo", "pss.browse_albedo", "Albedo (16-bit)", required=False)
        file_row(box, "path_normal", "pss.browse_normal", "Normal (16-bit)", required=False)
        file_row(box, "path_alpha",  "pss.browse_alpha",  "Alpha (optional)",required=False)

        # ---- Object size ----
        box2 = layout.box()
        box2.label(text="Object size", icon='OBJECT_DATAMODE')
        box2.row().prop(props, "size_mode", expand=True)
        if props.size_mode == 'WH':
            row = box2.row(align=True)
            row.prop(props, "width_cm",  text="Width cm")
            row.prop(props, "height_cm", text="Height cm")
        else:
            box2.prop(props, "dpi", text="Scanner DPI")
            # Show computed size using already-loaded depth image if available
            img = bpy.data.images.get("PSS_depth_disp")
            if img:
                px_w, px_h = img.size
                cm_w = px_w / props.dpi * 2.54
                cm_h = px_h / props.dpi * 2.54
                box2.label(text=f"{px_w} × {px_h} px  →  {cm_w:.2f} × {cm_h:.2f} cm")

        # ---- Geometry quality ----
        box3 = layout.box()
        box3.label(text="Geometry quality", icon='MOD_SUBSURF')
        box3.row().prop(props, "quality", expand=True)

        note_map = {
            'LOW':   "Fast - good for preview",
            'MED':   "Balanced - general use",
            'HIGH':  "High resolution - may take a while",
            'ULTRA': "Maximum detail - may be very slow",
        }
        box3.label(text=note_map[props.quality], icon='INFO')

        # ---- Main button ----
        layout.separator()
        ready = bool(props.path_depth)
        col = layout.column()
        col.enabled = ready
        col.scale_y = 1.8
        col.operator("pss.process", text="Process scan", icon='MESH_GRID')

        if not ready:
            layout.label(text="Depth map required", icon='ERROR')

        # ---- Results ----
        if props.result_ok:
            layout.separator()
            box4 = layout.box()
            box4.label(text="Result", icon='CHECKMARK')
            col = box4.column(align=True)
            col.label(text=f"X (width):  {props.result_x_cm:.3f} cm")
            col.label(text=f"Y (height): {props.result_y_cm:.3f} cm")
            col.separator()
            col.label(text=f"Z (range):  {props.result_z_mm:.3f} mm")
            col.label(text=f"  min: {props.result_z_min_m:.5f} m")
            col.label(text=f"  max: {props.result_z_max_m:.5f} m")


# ---------------------------------------------------------------------------
# DRAG AND DROP  (Blender 4.1+)
# Files dropped onto the 3D viewport are assigned to the first empty slot
# in order: depth -> albedo -> normal -> alpha
# ---------------------------------------------------------------------------

SLOT_ORDER = ["path_depth", "path_albedo", "path_normal", "path_alpha"]

# Keywords to detect which slot a dropped file belongs to (checked against filename)
SLOT_KEYWORDS = {
    "path_depth":  ["depth", "depthmap", "disp"],
    "path_albedo": ["albedo", "color", "colour", "rgb"],
    "path_normal": ["normal", "nrm"],
    "path_alpha":  ["alpha", "mask"],
}


def _detect_slot(filename):
    """Return the best matching slot name based on filename keywords, or None."""
    name_lower = filename.lower()
    for slot, keywords in SLOT_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return slot
    return None


class PSS_OT_DropImage(Operator):
    """Receive a file dropped onto the 3D viewport and assign it to the matching slot"""
    bl_idname  = "pss.drop_image"
    bl_label   = "Drop image into PSS slot"
    bl_options = {'REGISTER', 'INTERNAL'}

    filepath:    bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.tif;*.tiff;*.png", options={'HIDDEN'})

    def execute(self, context):
        props    = context.scene.pss_props
        path     = self.filepath
        filename = os.path.basename(path)

        # Try to match slot by filename keywords, fallback to first empty slot
        slot = _detect_slot(filename)
        if slot is None:
            for s in SLOT_ORDER:
                if not getattr(props, s, ""):
                    slot = s
                    break

        if slot is None:
            self.report({'WARNING'}, "All slots filled and no keyword match — clear a slot first")
            return {'CANCELLED'}

        setattr(props, slot, path)
        d = os.path.dirname(bpy.path.abspath(path))
        if os.path.isdir(d):
            props.last_dir = d
        slot_label = slot.replace("path_", "")
        self.report({'INFO'}, f"[OK] {filename} -> {slot_label}")
        print(f"[INFO] Drop: {filename} -> {slot_label}")
        return {'FINISHED'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None


class PSS_OT_ClearSlots(Operator):
    """Clear all image path slots"""
    bl_idname  = "pss.clear_slots"
    bl_label   = "Clear slots"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        props = context.scene.pss_props
        for slot in SLOT_ORDER:
            setattr(props, slot, "")
        props.result_ok = False
        return {'FINISHED'}


class PSS_FH_DropImages(bpy.types.FileHandler):
    bl_idname          = "PSS_FH_drop_images"
    bl_label           = "Drop PSS images"
    bl_import_operator = "pss.drop_image"
    bl_file_extensions = ".tif;.tiff;.png"

    @classmethod
    def poll_drop(cls, context):
        return context.area and context.area.type == 'VIEW_3D'


# ---------------------------------------------------------------------------
# REGISTRO
# ---------------------------------------------------------------------------

CLASSES = [
    PSSProperties,
    PSS_OT_BrowseDepth,
    PSS_OT_BrowseAlbedo,
    PSS_OT_BrowseNormal,
    PSS_OT_BrowseAlpha,
    PSS_OT_DropImage,
    PSS_OT_ClearSlots,
    PSS_OT_Process,
    PSS_PT_Panel,
]


def _reset_props(props):
    for slot in SLOT_ORDER:
        setattr(props, slot, "")
    props.result_ok = False


@bpy.app.handlers.persistent
def _on_load_post(filepath, *args):
    if hasattr(bpy.context.scene, "pss_props"):
        _reset_props(bpy.context.scene.pss_props)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.utils.register_class(PSS_FH_DropImages)
    bpy.types.Scene.pss_props = bpy.props.PointerProperty(type=PSSProperties)
    bpy.app.handlers.load_post.append(_on_load_post)
    print("[OK] Selene PSS v2.4.2 registered")


def unregister():
    bpy.app.handlers.load_post.remove(_on_load_post)
    bpy.utils.unregister_class(PSS_FH_DropImages)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.pss_props


if __name__ == "__main__":
    register()
