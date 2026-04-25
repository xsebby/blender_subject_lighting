# Subject Lighting Rig

Blender add-on that creates a simple subject-lighting setup:

- `1` front **Point** light
- `2` rear **Area** lights at about `45°` (left/right)
- quick warm/cold presets
- live editing of light color, power, and area size from the add-on panel

## Features

- One-click rig creation with `Add Lights`
- Rear area lights always aim at the subject center via a target empty
- Optional rig following with `Parent to subject`
- Light controls in the panel (no need to open per-light data panels)

## Install

1. In Blender, open `Edit > Preferences > Add-ons`.
2. Click `Install...`.
3. Select this folder (or a zip containing `__init__.py`).
4. Enable **Subject Lighting Rig**.

## Use

1. Select your subject object in **Object Mode**.
2. Open the `N` sidebar in the 3D View.
3. Go to the **Subject Lights** tab.
4. Click **Add Lights**.

## Notes

- `Parent to subject` controls whether the rig root follows the subject transforms.
- The target empty is used so the area lights keep facing the subject.
- If you update the add-on code, disable/enable the add-on to reload it.