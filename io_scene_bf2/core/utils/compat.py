"""Blender API compatibility module"""

def set_gn_modifier_input(modifier, identifier, value):
    getattr(modifier.properties.inputs, identifier).value = value

def iter_action_fcurves(action, slot=None):
    if action is None:
        return
    slots = action.slots if slot is None else [slot]
    for slot in slots:
        for layer in action.layers:
            for strip in layer.strips:
                channelbag = strip.channelbag(slot)
                if channelbag is None:
                    continue
                yield from channelbag.fcurves

def eevee_id():
    return 'BLENDER_EEVEE'

def pose_bone_hide(pose_bone, value=True):
    pose_bone.bone.hide = value
