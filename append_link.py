# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####


import logging
import uuid

import bpy

from . import utils, reports


bk_logger = logging.getLogger(__name__)


def find_layer_collection(layer_collection, collection_name):
    """Helper function to find a layer_collection by name"""
    if layer_collection.collection.name == collection_name:
        return layer_collection
    for child in layer_collection.children:
        result = find_layer_collection(child, collection_name)
        if result:
            return result
    return None


def append_brush(file_name, brushname=None, link=False, fake_user=True):
    """append a brush"""
    with bpy.data.libraries.load(file_name, link=link, relative=True) as (
        data_from,
        data_to,
    ):
        for m in data_from.brushes:
            if m == brushname or brushname is None:
                data_to.brushes = [m]
                brushname = m
    brush = bpy.data.brushes[brushname]
    brush.use_fake_user = fake_user
    return brush


def append_nodegroup(
    file_name, nodegroupname=None, link=False, fake_user=True, node_x=0, node_y=0
):
    """Append selected node group. If nodegroupname is None, first node group is appended.
    If node group with the same name is already in the scene, it is not appended again.
    Try to look for a suitable node editor and insert the node group there, in the middle of the area.

    Returns:
        tuple: (nodegroup, added_to_editor) - The nodegroup and whether it was added to an editor
    """
    with bpy.data.libraries.load(file_name, link=link, relative=True) as (
        data_from,
        data_to,
    ):
        for g in data_from.node_groups:
            print(g)
            if g == nodegroupname or nodegroupname is None:
                data_to.node_groups = [g]
                nodegroupname = g
    nodegroup = bpy.data.node_groups[nodegroupname]
    nodegroup.use_fake_user = fake_user

    # Mapping dict for node editor tree types to node group node types
    sdict = {
        "GeometryNodeTree": "GeometryNodeGroup",
        "ShaderNodeTree": "ShaderNodeGroup",
        "CompositorNodeTree": "CompositorNodeGroup",
    }

    # Get the nodegroup type
    nodegroup_type = nodegroup.bl_rna.identifier

    # Find a suitable node editor
    added_to_editor = False

    # First try: exact match for tree type
    for area in bpy.context.screen.areas:
        if area.type != "NODE_EDITOR":
            continue

        if area.spaces.active.tree_type == nodegroup_type:
            nt = area.spaces.active.edit_tree
            if nt is None:
                continue

            # Add node to this editor
            for n in nt.nodes:
                n.select = False

            node_type = sdict.get(nodegroup_type)
            if node_type:
                node = nt.nodes.new(node_type)
                node.node_tree = nodegroup
                node.location = (node_x, node_y)
                node.select = True
                nt.nodes.active = node
                added_to_editor = True
                break

    # If not added yet, try any compatible editor
    if not added_to_editor:
        for area in bpy.context.screen.areas:
            if area.type != "NODE_EDITOR":
                continue

            nt = area.spaces.active.edit_tree
            if nt is None:
                continue

            # Check if this editor type is compatible
            if area.spaces.active.tree_type in sdict:
                # Add node to this editor
                for n in nt.nodes:
                    n.select = False

                node_type = sdict.get(area.spaces.active.tree_type)
                if node_type:
                    # Check if nodegroup is compatible with this editor
                    # For example, don't add shader nodegroups to geometry node editor
                    if (
                        nodegroup_type == "ShaderNodeTree"
                        and area.spaces.active.tree_type != "ShaderNodeTree"
                    ) or (
                        nodegroup_type == "GeometryNodeTree"
                        and area.spaces.active.tree_type != "GeometryNodeTree"
                    ):
                        continue

                    node = nt.nodes.new(node_type)
                    node.node_tree = nodegroup
                    node.location = (node_x, node_y)
                    node.select = True
                    nt.nodes.active = node
                    added_to_editor = True
                    break

    return nodegroup, added_to_editor


def append_material(file_name, matname=None, link=False, fake_user=True):
    """append a material type asset

    first, we have to check if there is a material with same name
    in previous step there's check if the imported material
    is already in the scene, so we know same name != same material
    """

    mats_before = bpy.data.materials[:]
    try:
        with bpy.data.libraries.load(file_name, link=link, relative=True) as (
            data_from,
            data_to,
        ):
            found = False
            for m in data_from.materials:
                if m == matname or matname is None:
                    data_to.materials = [m]
                    matname = m
                    found = True
                    break

            # not found yet? probably some name inconsistency then.
            if not found and len(data_from.materials) > 0:
                data_to.materials = [data_from.materials[0]]
                matname = data_from.materials[0]
                bk_logger.warning(
                    f"the material wasn't found under the exact name, appended another one: {matname}"
                )

    except Exception as e:
        bk_logger.error(f"{e} - failed to open the asset file")
    # we have to find the new material , due to possible name changes
    mat = None
    for m in bpy.data.materials:
        if m not in mats_before:
            mat = m
            break
    # still not found?
    if mat is None:
        mat = bpy.data.materials.get(matname)

    if fake_user:
        mat.use_fake_user = True
    return mat


def append_scene(file_name, scenename=None, link=False, fake_user=False):
    """append a scene type asset"""
    with bpy.data.libraries.load(file_name, link=link, relative=True) as (
        data_from,
        data_to,
    ):
        for s in data_from.scenes:
            if s == scenename or scenename is None:
                data_to.scenes = [s]
                scenename = s
    scene = bpy.data.scenes[scenename]
    if fake_user:
        scene.use_fake_user = True
    # scene has to have a new uuid, so user reports aren't screwed.
    scene["uuid"] = str(uuid.uuid4())

    # reset ui_props of the scene to defaults:
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_props.down_up = "SEARCH"

    return scene


def get_node_sure(node_tree, ntype=""):
    """
    Gets a node of certain type, but creates a new one if not pre
    """
    node = None
    for n in node_tree.nodes:
        if ntype == n.bl_rna.identifier:
            node = n
            return node
    if not node:
        node = node_tree.nodes.new(type=ntype)

    return node


def hdr_swap(name, hdr):
    """
    Try to replace the hdr in current world setup. If this fails, create a new world.
    :param name: Name of the resulting world (renamse the current one if swap is successfull)
    :param hdr: Image type
    :return: None
    """
    w = bpy.context.scene.world
    if w:
        w.use_nodes = True
        w.name = name
        nt = w.node_tree
        for n in nt.nodes:
            if "ShaderNodeTexEnvironment" == n.bl_rna.identifier:
                env_node = n
                env_node.image = hdr
                return
    new_hdr_world(name, hdr)


def new_hdr_world(name, hdr):
    """
    creates a new world, links in the hdr with mapping node, and links the world to scene
    :param name: Name of the world datablock
    :param hdr: Image type
    :return: None
    """
    w = bpy.data.worlds.new(name=name)
    w.use_nodes = True
    bpy.context.scene.world = w

    nt = w.node_tree
    env_node = nt.nodes.new(type="ShaderNodeTexEnvironment")
    env_node.image = hdr
    background = get_node_sure(nt, "ShaderNodeBackground")
    tex_coord = get_node_sure(nt, "ShaderNodeTexCoord")
    mapping = get_node_sure(nt, "ShaderNodeMapping")

    nt.links.new(env_node.outputs["Color"], background.inputs["Color"])
    nt.links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], env_node.inputs["Vector"])
    env_node.location.x = -400
    mapping.location.x = -600
    tex_coord.location.x = -800


def load_HDR(file_name, name):
    """Load a HDR into file and link it to scene world."""
    already_linked = False
    for i in bpy.data.images:
        if i.filepath == file_name:
            hdr = i
            already_linked = True
            break

    if not already_linked:
        hdr = bpy.data.images.load(file_name)

    hdr_swap(name, hdr)
    return hdr


def link_collection(
    file_name,
    obnames=None,
    location=(0, 0, 0),
    link=False,
    parent=None,
    collection="",
    **kwargs,
):
    """link an instanced group - model type asset"""
    if obnames is None:
        obnames = []
    sel = utils.selection_get()
    # Store the original active collection
    orig_active_collection = bpy.context.view_layer.active_layer_collection

    # Activate target collection if specified
    if collection:
        target_collection = bpy.data.collections.get(collection)
        if target_collection:
            # Find and activate the layer collection
            layer_collection = find_layer_collection(
                bpy.context.view_layer.layer_collection, collection
            )
            if layer_collection:
                bpy.context.view_layer.active_layer_collection = layer_collection

    with bpy.data.libraries.load(file_name, link=link, relative=True) as (
        data_from,
        data_to,
    ):
        for col in data_from.collections:
            if col == kwargs["name"]:
                data_to.collections = [col]

    rotation = (0, 0, 0)
    if kwargs.get("rotation") is not None:
        rotation = kwargs["rotation"]

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=location, rotation=rotation)
    main_object = bpy.context.view_layer.objects.active
    main_object.instance_type = "COLLECTION"

    if parent is not None:
        main_object.parent = bpy.data.objects.get(parent)

    main_object.matrix_world.translation = location

    for col in bpy.data.collections:
        if col.library is not None:
            fp = bpy.path.abspath(col.library.filepath)
            fp1 = bpy.path.abspath(file_name)
            if fp == fp1:
                main_object.instance_collection = col
                break

    # sometimes, the lib might already  be without the actual link.
    if not main_object.instance_collection and kwargs["name"]:
        col = bpy.data.collections.get(kwargs["name"])
        if col:
            main_object.instance_collection = col

    main_object.name = main_object.instance_collection.name

    # Restore original active collection
    if orig_active_collection:
        bpy.context.view_layer.active_layer_collection = orig_active_collection

    utils.selection_set(sel)
    return main_object, []


def append_particle_system(
    file_name, obnames=None, location=(0, 0, 0), link=False, **kwargs
):
    """link an instanced group - model type asset"""
    if obnames is None:
        obnames = []
    pss = []
    with bpy.data.libraries.load(file_name, link=link, relative=True) as (
        data_from,
        data_to,
    ):
        for ps in data_from.particles:
            pss.append(ps)
        data_to.particles = pss

    s = bpy.context.scene
    sel = utils.selection_get()

    target_object = bpy.context.scene.objects.get(kwargs["target_object"])
    if target_object is not None and target_object.type == "MESH":
        target_object.select_set(True)
        bpy.context.view_layer.objects.active = target_object

        for ps in pss:
            # now let's tune this ps to the particular objects area:
            totarea = 0
            for p in target_object.data.polygons:
                totarea += p.area
            count = int(ps.count * totarea)

            if ps.child_type in ("INTERPOLATED", "SIMPLE"):
                total_count = count * ps.rendered_child_count
                disp_count = count * ps.child_nbr
            else:
                total_count = count

            bbox_threshold = 25000
            display_threshold = 200000
            total_max_threshold = 2000000
            # emitting too many parent particles just kills blender now.

            # this part tuned child count, we'll leave children to artists only.
            # if count > total_max_threshold:
            #     ratio = round(count / total_max_threshold)
            #
            #     if ps.child_type in ('INTERPOLATED', 'SIMPLE'):
            #         ps.rendered_child_count *= ratio
            #     else:
            #         ps.child_type = 'INTERPOLATED'
            #         ps.rendered_child_count = ratio
            #     count = max(2, int(count / ratio))

            # 1st level of optimizaton - switch t bounding boxes.
            if total_count > bbox_threshold:
                target_object.display_type = "BOUNDS"
            # 2nd level of optimization - reduce percentage of displayed particles.
            ps.display_percentage = min(
                ps.display_percentage,
                max(1, int(100 * display_threshold / total_count)),
            )
            # here we can also tune down number of children displayed.
            # set the count
            ps.count = count
            # add the modifier
            bpy.ops.object.particle_system_add()
            # 3rd level - hide particle system from viewport - is done on the modifier..
            if total_count > total_max_threshold:
                target_object.modifiers[-1].show_viewport = False

            target_object.particle_systems[-1].settings = ps

        target_object.select_set(False)
    utils.selection_set(sel)
    return target_object, []


def append_objects(
    file_name,
    obnames=None,
    location=(0, 0, 0),
    link=False,
    parent=None,
    collection="",
    **kwargs,
):
    """Append object into scene individually. 2 approaches based in definition of name argument.
    TODO: really split this function into 2 functions: kwargs.get('name')==None and else.
    """
    if obnames is None:
        obnames = []
    # simplified version of append
    if kwargs.get("name"):
        scene = bpy.context.scene
        sel = utils.selection_get()
        # Store the original active collection
        orig_active_collection = bpy.context.view_layer.active_layer_collection

        # Activate target collection if specified
        if collection:
            target_collection = bpy.data.collections.get(collection)
            if target_collection:
                # Find and activate the layer collection
                layer_collection = find_layer_collection(
                    bpy.context.view_layer.layer_collection, collection
                )
                if layer_collection:
                    bpy.context.view_layer.active_layer_collection = layer_collection

        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception as e:
            reports.add_report(
                f"append_objects.1: {str(e)}",
                3,
                type="ERROR",
            )
            raise e

        path = file_name + "/Collection"
        collection_name = kwargs.get("name")
        bpy.ops.wm.append(filename=collection_name, directory=path)

        # fc = utils.get_fake_context(bpy.context, area_type='VIEW_3D')
        # bpy.ops.wm.append(fc, filename=collection_name, directory=path)

        return_obs = []
        to_hidden_collection = []
        appended_collection = None
        main_object = None
        # get first at least one parent for sure
        for ob in bpy.context.scene.objects:
            if ob.select_get():
                if not ob.parent:
                    main_object = ob
                    ob.location = location
        # do once again to ensure hidden objects are hidden
        for ob in bpy.context.scene.objects:
            if ob.select_get():
                return_obs.append(ob)
                # check for object that should be hidden
                if ob.users_collection[0].name == collection_name:
                    appended_collection = ob.users_collection[0]
                    appended_collection["is_blenderkit_asset"] = True
                    if not ob.parent:
                        main_object = ob
                        ob.location = location
                else:
                    to_hidden_collection.append(ob)

        assert (
            main_object != None
        ), f"asset {kwargs['name']} not found in scene after appending"
        if kwargs.get("rotation"):
            main_object.rotation_euler = kwargs["rotation"]

        if parent is not None:
            main_object.parent = bpy.data.objects[parent]
            main_object.matrix_world.translation = location

        # move objects that should be hidden to a sub collection
        if len(to_hidden_collection) > 0 and appended_collection is not None:
            hidden_collections = []
            scene_collection = bpy.context.scene.collection
            for ob in to_hidden_collection:
                hide_collection = ob.users_collection[0]

                # objects from scene collection (like rigify widgets go to a new collection
                if (
                    hide_collection == scene_collection
                    or hide_collection.name in scene_collection.children
                ):
                    hidden_collection_name = collection_name + "_hidden"
                    h_col = bpy.data.collections.get(hidden_collection_name)
                    if h_col is None:
                        h_col = bpy.data.collections.new(name=hidden_collection_name)
                        # If target collection is specified, make the hidden collection a child of target collection
                        if collection and bpy.data.collections.get(collection):
                            bpy.data.collections.get(collection).children.link(h_col)
                        else:
                            appended_collection.children.link(h_col)
                        utils.exclude_collection(hidden_collection_name)

                    ob.users_collection[0].objects.unlink(ob)
                    h_col.objects.link(ob)
                    continue
                if hide_collection in hidden_collections:
                    continue
                # All other collections are moved to be children of the model collection
                bk_logger.info(f"{hide_collection}, {appended_collection}")
                # If target collection is specified, move collections there instead
                if collection and bpy.data.collections.get(collection):
                    utils.move_collection(
                        hide_collection, bpy.data.collections.get(collection)
                    )
                else:
                    utils.move_collection(hide_collection, appended_collection)
                utils.exclude_collection(hide_collection.name)
                hidden_collections.append(hide_collection)

        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception as e:
            reports.add_report(
                f"append_objects.2: {str(e)}",
                3,
                type="ERROR",
            )
            raise e

        # Restore original active collection
        if orig_active_collection:
            bpy.context.view_layer.active_layer_collection = orig_active_collection

        utils.selection_set(sel)
        # let collection also store info that it was created by BlenderKit, for purging reasons

        return main_object, return_obs

    # this is used for uploads:
    with bpy.data.libraries.load(file_name, link=link, relative=True) as (
        data_from,
        data_to,
    ):
        sobs = []
        # for col in data_from.collections:
        #     if col == kwargs.get('name'):
        for ob in data_from.objects:
            if ob in obnames or obnames == []:
                sobs.append(ob)
        data_to.objects = sobs
        # data_to.objects = data_from.objects#[name for name in data_from.objects if name.startswith("house")]

    # link them to scene
    scene = bpy.context.scene
    sel = utils.selection_get()
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception as e:
        reports.add_report(
            f"append_objects.3: {str(e)}",
            3,
            type="ERROR",
        )
        raise e

    return_obs = []  # this might not be needed, but better be sure to rewrite the list.
    main_object = None
    hidden_objects = []

    for obj in data_to.objects:
        if obj is not None:
            # if obj.name not in scene.objects:
            scene.collection.objects.link(obj)
            if obj.parent is None:
                obj.location = location
                main_object = obj
            obj.select_set(True)
            # we need to unhide object so make_local op can use those too.
            if link == True:
                if obj.hide_viewport:
                    hidden_objects.append(obj)
                    obj.hide_viewport = False
            return_obs.append(obj)

    # Only after all objects are in scene! Otherwise gets broken relationships
    if link == True:
        bpy.ops.object.make_local(type="SELECT_OBJECT")
        for ob in hidden_objects:
            ob.hide_viewport = True

    if kwargs.get("rotation") is not None:
        main_object.rotation_euler = kwargs["rotation"]

    if parent is not None:
        main_object.parent = bpy.data.objects[parent]
        main_object.matrix_world.translation = location

    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception as e:
        reports.add_report(
            f"append_objects.4: {str(e)}",
            3,
            type="ERROR",
        )
        raise e
    utils.selection_set(sel)

    return main_object, return_obs
