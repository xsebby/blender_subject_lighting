# Subject Lighting Rig - Blender add-on
# Adds a front point light and two 45-degree back area lights around the active object.

import math

import bpy
from mathutils import Vector

bl_info = {
    "name": "Subject Lighting Rig",
    "author": "",
    "version": (1, 0, 1),
    "blender": (3, 0, 0),
    "location": "View3D > N-panel > Subject Lights",
    "description": "Add and edit a front point light plus two aimed 45-degree back area lights",
    "category": "Lighting",
}

COLLECTION_NAME = "SubjectRig"
ROOT_NAME = "SubjectRig_Root"
TARGET_NAME = "SubjectRig_Target"
FRONT_NAME = "SubjectRig_Front"
BACK_LEFT_NAME = "SubjectRig_Back_L"
BACK_RIGHT_NAME = "SubjectRig_Back_R"
AIM_CONSTRAINT = "SubjectRig_Aim"


def get_subject_center(obj) -> Vector:
    """World-space center: mesh bounds center when possible, else object origin."""
    if obj.type == "MESH" and obj.data:
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        return sum(corners, Vector()) * (1.0 / 8.0)
    return obj.matrix_world.translation.copy()


# Clearance added past the subject's outer surface so lights never start inside the mesh
_RIG_OUTSIDE_MARGIN = 1.0
_RIG_MIN_HALF = 0.5


def subject_light_offset_radius(obj) -> float:
    """
    World-space distance from the subject's bounds center to its outermost point,
    plus a margin. Uses BOTH the bound-box corner distance and obj.dimensions so
    we never under-shoot for objects with offset geometry or unusual bounds.
    """
    half = _RIG_MIN_HALF

    if obj.type == "MESH" and obj.data:
        center = get_subject_center(obj)
        try:
            corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            if corners:
                half = max(half, max((c - center).length for c in corners))
        except Exception:
            pass

    try:
        d = obj.dimensions
        if d.length > 1e-8:
            half = max(half, 0.5 * max(d.x, d.y, d.z))
    except Exception:
        pass

    return half + _RIG_OUTSIDE_MARGIN


def ensure_collection(context, name: str):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        context.scene.collection.children.link(collection)
    return collection


def link_to_collection_only(obj, collection):
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for user_collection in list(obj.users_collection):
        if user_collection != collection:
            user_collection.objects.unlink(obj)


def parent_keep_world(child, parent):
    """
    Parent child to parent while keeping the child's current world transform.
    Forces a depsgraph update first so just-set locations are reflected in matrix_world.
    """
    if child is None or parent is None:
        return
    if child.parent is parent:
        return
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    saved_world = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    child.matrix_world = saved_world


def clear_parent_keep_world(child):
    if child is None or child.parent is None:
        return
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    saved_world = child.matrix_world.copy()
    child.parent = None
    child.matrix_parent_inverse.identity()
    child.matrix_world = saved_world


def set_world_location(obj, location):
    matrix_world = obj.matrix_world.copy()
    matrix_world.translation = location
    obj.matrix_world = matrix_world


def apply_color(light_data, color):
    light_data.color = (color[0], color[1], color[2])


# Fixed multiplier of subject_light_offset_radius for the default rig spread
RIG_DISTANCE_MULTIPLIER = 3.0


def rig_vector_offsets(subject):
    radius = subject_light_offset_radius(subject) * RIG_DISTANCE_MULTIPLIER
    half = math.sqrt(0.5)
    return {
        "front": Vector((0.0, -1.0, 0.0)) * radius,
        "back_left": Vector((-half, half, 0.0)) * radius,
        "back_right": Vector((half, half, 0.0)) * radius,
    }


def get_pointer_or_named(settings, attr, name):
    obj = getattr(settings, attr, None)
    if obj and obj.name in bpy.data.objects:
        return obj
    obj = bpy.data.objects.get(name)
    if obj:
        setattr(settings, attr, obj)
    return obj


def is_rig_object(obj):
    return obj and obj.name in {
        ROOT_NAME,
        TARGET_NAME,
        FRONT_NAME,
        BACK_LEFT_NAME,
        BACK_RIGHT_NAME,
    }


def get_subject_for_add(context, settings):
    active = context.active_object
    if active and not is_rig_object(active):
        return active
    if settings.subject and settings.subject.name in bpy.data.objects:
        return settings.subject
    return active


def add_track_to_subject(light_obj, target_obj):
    constraint = light_obj.constraints.get(AIM_CONSTRAINT)
    if constraint is None:
        constraint = light_obj.constraints.new(type="TRACK_TO")
        constraint.name = AIM_CONSTRAINT
    constraint.target = target_obj
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"
    constraint.owner_space = "WORLD"
    constraint.target_space = "WORLD"


def remove_track_constraint(light_obj):
    if not light_obj:
        return
    constraint = light_obj.constraints.get(AIM_CONSTRAINT)
    if constraint:
        light_obj.constraints.remove(constraint)


def cleanup_existing_rig(settings):
    names = (FRONT_NAME, BACK_LEFT_NAME, BACK_RIGHT_NAME, TARGET_NAME, ROOT_NAME)
    attrs = ("front_light", "back_left_light", "back_right_light", "target", "root")
    seen = set()
    for attr, name in zip(attrs, names):
        obj = getattr(settings, attr, None) or bpy.data.objects.get(name)
        if obj and obj.name not in seen:
            seen.add(obj.name)
            data = obj.data if obj.type == "LIGHT" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if data and data.users == 0:
                bpy.data.lights.remove(data, do_unlink=True)
        setattr(settings, attr, None)


def sync_target_to_subject(settings):
    subject = settings.subject
    target = get_pointer_or_named(settings, "target", TARGET_NAME)
    if subject and target:
        set_world_location(target, get_subject_center(subject))


def update_parenting(self, context):
    """Toggling Parent-to-subject only changes whether the rig root follows the subject."""
    root = get_pointer_or_named(self, "root", ROOT_NAME)
    subject = self.subject
    if not root:
        return

    if self.parent_to_subject and subject:
        parent_keep_world(root, subject)
    else:
        clear_parent_keep_world(root)


def set_light_defaults(settings, preset):
    presets = {
        "NEUTRAL": {
            "point": (1.0, 1.0, 1.0),
            "left": (1.0, 1.0, 1.0),
            "right": (1.0, 1.0, 1.0),
            "point_energy": 400.0,
            "area_energy": 200.0,
        },
        "WARM": {
            "point": (1.0, 0.84, 0.58),
            "left": (1.0, 0.58, 0.34),
            "right": (1.0, 0.70, 0.42),
            "point_energy": 420.0,
            "area_energy": 240.0,
        },
        "COLD": {
            "point": (0.72, 0.84, 1.0),
            "left": (0.42, 0.60, 1.0),
            "right": (0.58, 0.76, 1.0),
            "point_energy": 380.0,
            "area_energy": 220.0,
        },
    }
    values = presets[preset]
    settings.color_point = values["point"]
    settings.color_area_left = values["left"]
    settings.color_area_right = values["right"]
    settings.energy_point = values["point_energy"]
    settings.energy_area = values["area_energy"]


def apply_preset_to_existing_lights(settings):
    front = get_pointer_or_named(settings, "front_light", FRONT_NAME)
    left = get_pointer_or_named(settings, "back_left_light", BACK_LEFT_NAME)
    right = get_pointer_or_named(settings, "back_right_light", BACK_RIGHT_NAME)

    if front and front.type == "LIGHT":
        apply_color(front.data, settings.color_point)
        front.data.energy = settings.energy_point
    if left and left.type == "LIGHT":
        apply_color(left.data, settings.color_area_left)
        left.data.energy = settings.energy_area
    if right and right.type == "LIGHT":
        apply_color(right.data, settings.color_area_right)
        right.data.energy = settings.energy_area


class SUBJECT_RIG_OT_add_lights(bpy.types.Operator):
    bl_idname = "subject_rig.add_lights"
    bl_label = "Add Lights"
    bl_description = "Create or replace the subject lighting rig around the active object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.mode == "OBJECT"

    def execute(self, context):
        settings = context.scene.subject_rig
        subject = get_subject_for_add(context, settings)
        if subject is None:
            self.report({"ERROR"}, "Select a subject object first")
            return {"CANCELLED"}

        collection = ensure_collection(context, COLLECTION_NAME)
        center = get_subject_center(subject)
        radius = subject_light_offset_radius(subject)
        offsets = rig_vector_offsets(subject)

        cleanup_existing_rig(settings)

        # Always-present root for organization + optional follow
        root = bpy.data.objects.new(ROOT_NAME, None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = max(0.35, radius * 0.2)
        collection.objects.link(root)
        root.location = center

        # Always-present target empty so area lights can Track To it
        target = bpy.data.objects.new(TARGET_NAME, None)
        target.empty_display_type = "SPHERE"
        target.empty_display_size = max(0.2, radius * 0.12)
        collection.objects.link(target)
        target.location = center

        def new_light(name, light_type, world_location):
            light_data = bpy.data.lights.new(name, type=light_type)
            light_obj = bpy.data.objects.new(name, light_data)
            collection.objects.link(light_obj)
            light_obj.location = world_location
            return light_obj

        front = new_light(FRONT_NAME, "POINT", center + offsets["front"])
        front.data.energy = settings.energy_point
        apply_color(front.data, settings.color_point)

        left = new_light(BACK_LEFT_NAME, "AREA", center + offsets["back_left"])
        left.data.energy = settings.energy_area
        left.data.size = settings.area_size
        apply_color(left.data, settings.color_area_left)

        right = new_light(BACK_RIGHT_NAME, "AREA", center + offsets["back_right"])
        right.data.energy = settings.energy_area
        right.data.size = settings.area_size
        apply_color(right.data, settings.color_area_right)

        # Make Blender flush the just-set locations into matrix_world
        context.view_layer.update()

        # Track To target so area lights always face the subject
        add_track_to_subject(left, target)
        add_track_to_subject(right, target)

        # Group everything under the rig root, preserving world transforms
        for obj in (target, front, left, right):
            parent_keep_world(obj, root)

        # Optional: have the rig follow the subject
        if settings.parent_to_subject:
            parent_keep_world(root, subject)

        settings.subject = subject
        settings.root = root
        settings.target = target
        settings.front_light = front
        settings.back_left_light = left
        settings.back_right_light = right

        for obj in (front, left, right):
            obj.select_set(True)
        context.view_layer.objects.active = front
        self.report(
            {"INFO"},
            f"Lights placed at radius {radius * RIG_DISTANCE_MULTIPLIER:.2f} (subject half {radius - _RIG_OUTSIDE_MARGIN:.2f})",
        )
        return {"FINISHED"}


class SUBJECT_RIG_OT_apply_preset(bpy.types.Operator):
    bl_idname = "subject_rig.apply_preset"
    bl_label = "Apply Lighting Preset"
    bl_description = "Apply a color and power preset to the defaults and existing rig lights"
    bl_options = {"REGISTER", "UNDO"}

    preset: bpy.props.EnumProperty(
        items=(
            ("NEUTRAL", "Neutral", "Clean white studio lighting"),
            ("WARM", "Warm", "Soft orange/gold lighting"),
            ("COLD", "Cold", "Cool blue lighting"),
        ),
        default="NEUTRAL",
    )

    def execute(self, context):
        settings = context.scene.subject_rig
        set_light_defaults(settings, self.preset)
        apply_preset_to_existing_lights(settings)
        return {"FINISHED"}


class SUBJECT_RIG_PT_panel(bpy.types.Panel):
    bl_label = "Subject Lights"
    bl_idname = "SUBJECT_RIG_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Subject Lights"

    def draw_live_light(self, layout, obj, title):
        box = layout.box()
        box.label(text=title, icon="LIGHT")
        if not obj or obj.type != "LIGHT":
            box.label(text="Missing - press Add Lights to rebuild", icon="ERROR")
            return
        box.prop(obj.data, "color", text="Color")
        box.prop(obj.data, "energy", text="Power (W)")
        if obj.data.type == "AREA":
            box.prop(obj.data, "size", text="Size")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.subject_rig

        can_run = context.active_object is not None and context.mode == "OBJECT"
        row = layout.row()
        row.operator("subject_rig.add_lights", icon="LIGHT")
        if not can_run:
            layout.row().label(
                text="Select a subject in Object mode, then add lights", icon="INFO"
            )

        row = layout.row(align=True)
        warm = row.operator("subject_rig.apply_preset", text="Warm")
        warm.preset = "WARM"
        cold = row.operator("subject_rig.apply_preset", text="Cold")
        cold.preset = "COLD"
        neutral = row.operator("subject_rig.apply_preset", text="Neutral")
        neutral.preset = "NEUTRAL"

        front = get_pointer_or_named(settings, "front_light", FRONT_NAME)
        left = get_pointer_or_named(settings, "back_left_light", BACK_LEFT_NAME)
        right = get_pointer_or_named(settings, "back_right_light", BACK_RIGHT_NAME)

        layout.separator()
        if front or left or right:
            layout.label(text="Live Light Properties")
            self.draw_live_light(layout, front, "Front Point")
            self.draw_live_light(layout, left, "Back Left Area")
            self.draw_live_light(layout, right, "Back Right Area")
        else:
            box = layout.box()
            box.label(text="Defaults For Next Rig")
            box.prop(settings, "color_point", text="Front color")
            box.prop(settings, "color_area_left", text="Back left color")
            box.prop(settings, "color_area_right", text="Back right color")
            box.prop(settings, "energy_point", text="Point power (W)")
            box.prop(settings, "energy_area", text="Area power (W)")
            box.prop(settings, "area_size", text="Area size")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Rig")
        col.prop(settings, "parent_to_subject", text="Parent to subject")
        if settings.parent_to_subject:
            col.label(text="Rig follows subject; lights still aim via target", icon="INFO")
        else:
            col.label(text="Lights stay in world but aim at the target empty", icon="INFO")


class SubjectRigSettings(bpy.types.PropertyGroup):
    subject: bpy.props.PointerProperty(type=bpy.types.Object)
    root: bpy.props.PointerProperty(type=bpy.types.Object)
    target: bpy.props.PointerProperty(type=bpy.types.Object)
    front_light: bpy.props.PointerProperty(type=bpy.types.Object)
    back_left_light: bpy.props.PointerProperty(type=bpy.types.Object)
    back_right_light: bpy.props.PointerProperty(type=bpy.types.Object)

    color_point: bpy.props.FloatVectorProperty(
        name="Front point color",
        subtype="COLOR",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )
    color_area_left: bpy.props.FloatVectorProperty(
        name="Back left area color",
        subtype="COLOR",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )
    color_area_right: bpy.props.FloatVectorProperty(
        name="Back right area color",
        subtype="COLOR",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )
    energy_point: bpy.props.FloatProperty(
        name="Point power",
        default=400.0,
        min=0.0,
        soft_max=2000.0,
    )
    energy_area: bpy.props.FloatProperty(
        name="Area power",
        default=200.0,
        min=0.0,
        soft_max=2000.0,
    )
    area_size: bpy.props.FloatProperty(
        name="Area size",
        default=1.0,
        min=0.01,
        max=100.0,
        description="Width/height of each area light in Blender units",
    )
    parent_to_subject: bpy.props.BoolProperty(
        name="Parent to subject",
        default=False,
        description="Parent the rig root to the subject while preserving the light spread",
        update=update_parenting,
    )


classes = (
    SubjectRigSettings,
    SUBJECT_RIG_OT_add_lights,
    SUBJECT_RIG_OT_apply_preset,
    SUBJECT_RIG_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.subject_rig = bpy.props.PointerProperty(type=SubjectRigSettings)


def unregister():
    if hasattr(bpy.types.Scene, "subject_rig"):
        del bpy.types.Scene.subject_rig
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
