# Subject Lighting Rig - Blender add-on
# Adds a front point light and two 45-degree back area lights around the active object.

import math

import bpy
from mathutils import Vector

bl_info = {
    "name": "Subject Lighting Rig",
    "author": "",
    "version": (1, 4, 0),
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


def world_radius_for_offset(obj) -> float:
    """Approximate size for default light distance."""
    if obj.type == "MESH" and obj.data:
        corners = [Vector(c) for c in obj.bound_box]
        radius = max((corner.length for corner in corners), default=1.0)
        scale = max(obj.scale.x, obj.scale.y, obj.scale.z)
        return max(0.5, radius * scale)
    return 2.0


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
    """Parent child to parent while preserving world transform."""
    if child is None or parent is None:
        return
    if child.parent is parent:
        return
    matrix_world = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    child.matrix_world = matrix_world


def clear_parent_keep_world(child):
    if child is None or child.parent is None:
        return
    matrix_world = child.matrix_world.copy()
    child.parent = None
    child.matrix_parent_inverse.identity()
    child.matrix_world = matrix_world


def set_world_location(obj, location):
    matrix_world = obj.matrix_world.copy()
    matrix_world.translation = location
    obj.matrix_world = matrix_world


def apply_color(light_data, color):
    light_data.color = (color[0], color[1], color[2])


def rig_vector_offsets(subject, distance_scale):
    radius = world_radius_for_offset(subject) * distance_scale
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


def bake_rotation_toward(light_obj, world_target: Vector):
    """Rotate light so its local -Z points at world_target. Used when no target empty exists."""
    if not light_obj:
        return
    direction = world_target - light_obj.matrix_world.translation
    if direction.length < 1e-7:
        return
    quat = direction.to_track_quat("-Z", "Y")
    light_obj.rotation_mode = "QUATERNION"
    light_obj.rotation_quaternion = quat


def remove_target_empty(settings):
    target = get_pointer_or_named(settings, "target", TARGET_NAME)
    if target:
        bpy.data.objects.remove(target, do_unlink=True)
    settings.target = None


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


def scale_lights_from_subject(settings, ratio):
    """Scale each light's offset from the subject center by ratio.

    Preserves the current direction of each light so manual moves (e.g. raised
    overhead lights) stay in place when only the distance scale changes.
    """
    subject = settings.subject
    if not subject or ratio <= 0 or abs(ratio - 1.0) < 1e-9:
        return
    center = get_subject_center(subject)
    for attr, name in (
        ("front_light", FRONT_NAME),
        ("back_left_light", BACK_LEFT_NAME),
        ("back_right_light", BACK_RIGHT_NAME),
    ):
        light = get_pointer_or_named(settings, attr, name)
        if not light:
            continue
        current = light.matrix_world.translation.copy()
        offset = current - center
        if offset.length < 1e-7:
            continue
        set_world_location(light, center + offset * ratio)


def update_distance(self, context):
    new_scale = self.light_distance
    old_scale = self.last_distance_scale
    if old_scale <= 0:
        old_scale = new_scale
    ratio = new_scale / old_scale if old_scale > 0 else 1.0
    scale_lights_from_subject(self, ratio)
    sync_target_to_subject(self)
    self.last_distance_scale = new_scale


def update_parenting(self, context):
    root = get_pointer_or_named(self, "root", ROOT_NAME)
    subject = self.subject
    if not root:
        return

    left = get_pointer_or_named(self, "back_left_light", BACK_LEFT_NAME)
    right = get_pointer_or_named(self, "back_right_light", BACK_RIGHT_NAME)
    collection = ensure_collection(context, COLLECTION_NAME)
    center = get_subject_center(subject) if subject else root.matrix_world.translation

    if self.parent_to_subject and subject:
        parent_keep_world(root, subject)
        target = get_pointer_or_named(self, "target", TARGET_NAME)
        if target is None:
            target = bpy.data.objects.new(TARGET_NAME, None)
            target.empty_display_type = "SPHERE"
            target.empty_display_size = max(0.2, world_radius_for_offset(subject) * 0.12)
            collection.objects.link(target)
            self.target = target
        set_world_location(target, center)
        parent_keep_world(target, root)
        if left:
            add_track_to_subject(left, target)
        if right:
            add_track_to_subject(right, target)
    else:
        clear_parent_keep_world(root)
        if left:
            remove_track_constraint(left)
            bake_rotation_toward(left, center)
        if right:
            remove_track_constraint(right)
            bake_rotation_toward(right, center)
        remove_target_empty(self)


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
        offsets = rig_vector_offsets(subject, settings.light_distance)

        cleanup_existing_rig(settings)

        root = bpy.data.objects.new(ROOT_NAME, None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = max(0.35, world_radius_for_offset(subject) * 0.2)
        root.location = center
        collection.objects.link(root)

        target = None
        if settings.parent_to_subject:
            target = bpy.data.objects.new(TARGET_NAME, None)
            target.empty_display_type = "SPHERE"
            target.empty_display_size = max(0.2, world_radius_for_offset(subject) * 0.12)
            target.location = center
            collection.objects.link(target)

        def new_light(name, light_type, location):
            light_data = bpy.data.lights.new(name, type=light_type)
            light_obj = bpy.data.objects.new(name, light_data)
            light_obj.location = location
            collection.objects.link(light_obj)
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

        if target is not None:
            add_track_to_subject(left, target)
            add_track_to_subject(right, target)
        else:
            bake_rotation_toward(left, center)
            bake_rotation_toward(right, center)

        rig_children = [front, left, right]
        if target is not None:
            rig_children.insert(0, target)
        for obj in rig_children:
            parent_keep_world(obj, root)

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
        col.prop(settings, "light_distance", text="Distance scale")
        col.prop(settings, "parent_to_subject", text="Parent to subject")
        if settings.parent_to_subject:
            col.label(text="Target empty added so lights track the subject", icon="INFO")
        else:
            col.label(text="No target empty; lights face subject from fixed pose", icon="INFO")


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
    light_distance: bpy.props.FloatProperty(
        name="Distance",
        default=2.0,
        min=0.1,
        max=100.0,
        description="Multiple of the subject size for light placement",
        update=update_distance,
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
