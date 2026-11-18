import bpy # type: ignore


def get_or_create_collection(context, name, hidden=False):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)

    if context.scene.collection.children.get(collection.name) is None:
        context.scene.collection.children.link(collection)

    collection.hide_render = hidden
    collection.hide_viewport = hidden

    return collection


def move_object_to_collection(obj, collection):
    if collection.objects.get(obj.name) is None:
        collection.objects.link(obj)
    for source_collection in tuple(obj.users_collection):
        if source_collection != collection:
            source_collection.objects.unlink(obj)


def move_object_hierarchy_to_collection(
    obj,
    collection,
    skip_subtree=None,
):
    if skip_subtree is not None and skip_subtree(obj):
        return

    move_object_to_collection(obj, collection)
    for child in tuple(obj.children):
        move_object_hierarchy_to_collection(
            child,
            collection,
            skip_subtree=skip_subtree,
        )
