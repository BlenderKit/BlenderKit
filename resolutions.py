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


import json
import logging
import os
import sys
import time

import bpy
import requests

from . import bg_blender, image_utils, paths, rerequests, upload, utils


bk_logger = logging.getLogger(__name__)

resolutions = {
    'resolution_0_5K': 512,
    'resolution_1K': 1024,
    'resolution_2K': 2048,
    'resolution_4K': 4096,
    'resolution_8K': 8192,
}
rkeys = list(resolutions.keys())

resolution_props_to_server = {
    '512': 'resolution_0_5K',
    '1024': 'resolution_1K',
    '2048': 'resolution_2K',
    '4096': 'resolution_4K',
    '8192': 'resolution_8K',
    'ORIGINAL': 'blend',
}


def get_current_resolution():
    actres = 0
    for i in bpy.data.images:
        if i.name != 'Render Result':
            actres = max(actres, i.size[0], i.size[1])
    return actres


def upload_resolutions(files, asset_data, api_key = ''):
    upload_data = {
        "name": asset_data['name'],
        "displayName": asset_data['displayName'],
        "token": api_key,
        "id": asset_data['id']
    }

    uploaded = upload.upload_files(upload_data, files)
    if uploaded:
        bg_blender.progress('upload finished successfully')
    else:
        bg_blender.progress('upload failed.')


def unpack_asset(data):
    utils.p('unpacking asset')
    asset_data = data['asset_data']
    # utils.pprint(asset_data)

    blend_file_name = os.path.basename(bpy.data.filepath)
    ext = os.path.splitext(blend_file_name)[1]

    resolution = asset_data.get('resolution', 'blend')
    # TODO - passing resolution inside asset data might not be the best solution
    tex_dir_path = paths.get_texture_directory(asset_data, resolution=resolution)
    tex_dir_abs = bpy.path.abspath(tex_dir_path)
    if not os.path.exists(tex_dir_abs):
        try:
            os.mkdir(tex_dir_abs)
        except Exception as e:
            print(e)
    bpy.data.use_autopack = False
    for image in bpy.data.images:
        if image.name != 'Render Result':
            # suffix = paths.resolution_suffix(data['suffix'])
            fp = get_texture_filepath(tex_dir_path, image, resolution=resolution)
            utils.p('unpacking file', image.name)
            utils.p(image.filepath, fp)

            for pf in image.packed_files:
                pf.filepath = fp  # bpy.path.abspath(fp)
            image.filepath = fp  # bpy.path.abspath(fp)
            image.filepath_raw = fp  # bpy.path.abspath(fp)
            # image.save()
            if len(image.packed_files) > 0:
                # image.unpack(method='REMOVE')
                image.unpack(method='WRITE_ORIGINAL')

    #mark asset browser asset
    data_block = None
    if asset_data['assetType'] == 'model':
        for ob in bpy.data.objects:
            if ob.parent is None and ob in bpy.context.visible_objects:
                if bpy.app.version>=(3,0,0):
                    ob.asset_mark()
        # for c in bpy.data.collections:
        #     if c.get('asset_data') is not None:
        #         if bpy.app.version >= (3, 0, 0):

        #         c.asset_mark()
        #         data_block = c
    elif asset_data['assetType'] == 'material':
        for m in bpy.data.materials:
            if bpy.app.version >= (3, 0, 0):
                m.asset_mark()
            data_block = m
    elif asset_data['assetType'] == 'scene':
        if bpy.app.version >= (3, 0, 0):
            bpy.context.scene.asset_mark()
    elif asset_data['assetType'] =='brush':
        for b in bpy.data.brushes:
            if b.get('asset_data') is not None:
                if bpy.app.version >= (3, 0, 0):
                    b.asset_mark()
                data_block = b
    if bpy.app.version >= (3, 0, 0) and data_block is not None:
        tags = data_block.asset_data.tags
        for t in tags:
            tags.remove(t)
        tags.new('description: ' + asset_data['description'])
        tags.new('tags: ' + ','.join(asset_data['tags']))
    #
    # if this isn't here, blender crashes when saving file.
    if bpy.app.version >= (3, 0, 0):
        bpy.context.preferences.filepaths.file_preview_type = 'NONE'

    bpy.ops.wm.save_as_mainfile(filepath = bpy.data.filepath, compress=False)
    # now try to delete the .blend1 file
    try:

        os.remove(bpy.data.filepath + '1')
    except Exception as e:
        print(e)
    bpy.ops.wm.quit_blender()
    sys.exit()


def patch_asset_empty(asset_id, api_key):
    """Patch the asset for the purpose of it getting a reindex.
    Should be removed once this is fixed on the server and
    the server is able to reindex after uploads of resolutions.
    """
    upload_data = {}
    url = f'{paths.BLENDERKIT_API}/assets/{asset_id}/'
    headers = utils.get_headers(api_key)
    try:
        r = rerequests.patch(url, json=upload_data, headers=headers, verify=True)  # files = files,
    except requests.exceptions.RequestException as e:
        print(e)
        return {'CANCELLED'}
    return {'FINISHED'}


def get_texture_filepath(tex_dir_path, image, resolution='blend'):
    if len(image.packed_files) > 0:
        image_file_name = bpy.path.basename(image.packed_files[0].filepath)
    else:
        image_file_name = bpy.path.basename(image.filepath)
    if image_file_name == '':
        image_file_name = image.name.split('.')[0]

    suffix = paths.resolution_suffix[resolution]

    fp = os.path.join(tex_dir_path, image_file_name)
    # check if there is allready an image with same name and thus also assigned path
    # (can happen easily with genearted tex sets and more materials)
    done = False
    fpn = fp
    i = 0
    while not done:
        is_solo = True
        for image1 in bpy.data.images:
            if image != image1 and image1.filepath == fpn:
                is_solo = False
                fpleft, fpext = os.path.splitext(fp)
                fpn = fpleft + str(i).zfill(3) + fpext
                i += 1
        if is_solo:
            done = True

    return fpn


def generate_lower_resolutions_hdr(data):
    '''generates lower resolutions for HDR images'''
    asset_data = data['asset_data']
    fpath = data['fpath']
    hdr = bpy.data.images.load(fpath)
    actres = max(hdr.size[0], hdr.size[1])
    p2res = paths.round_to_closest_resolution(actres)
    original_filesize = os.path.getsize(fpath) # for comparison on the original level
    i = 0
    finished = False
    files = []
    while not finished:
        dirn = os.path.dirname(fpath)
        fn_strip, ext = os.path.splitext(fpath)
        ext = '.exr'
        if i>0:
            image_utils.downscale(hdr)


        hdr_resolution_filepath = fn_strip + paths.resolution_suffix[p2res] + ext
        image_utils.img_save_as(hdr, filepath=hdr_resolution_filepath, file_format='OPEN_EXR', quality=20, color_mode='RGB', compression=15,
                    view_transform='Raw', exr_codec = 'DWAA')

        if os.path.exists(hdr_resolution_filepath):
            reduced_filesize = os.path.getsize(hdr_resolution_filepath)

        # compare file sizes
        print(f'HDR size was reduced from {original_filesize} to {reduced_filesize}')
        if reduced_filesize < original_filesize:
            # this limits from uploaidng especially same-as-original resolution files in case when there is no advantage.
            # usually however the advantage can be big also for same as original resolution
            files.append({
                "type": p2res,
                "index": 0,
                "file_path": hdr_resolution_filepath
            })

            print('prepared resolution file: ', p2res)

        if rkeys.index(p2res) == 0:
            finished = True
        else:
            p2res = rkeys[rkeys.index(p2res) - 1]
        i+=1

    print('uploading resolution files')
    print(files)
    upload_resolutions(files, data['asset_data'], api_key=data['api_key'])
    patch_asset_empty(data['asset_data']['id'], api_key=data['api_key'])


def generate_lower_resolutions(data):
    asset_data = data['asset_data']
    actres = get_current_resolution()
    # first let's skip procedural assets
    base_fpath = bpy.data.filepath

    s = bpy.context.scene

    print('current resolution of the asset ', actres)
    if actres > 0:
        p2res = paths.round_to_closest_resolution(actres)
        orig_res = p2res
        print(p2res)
        finished = False
        files = []
        # now skip assets that have lowest possible resolution already
        if p2res != [0]:
            original_textures_filesize = 0
            for i in bpy.data.images:
                abspath = bpy.path.abspath(i.filepath)
                if os.path.exists(abspath):
                    original_textures_filesize += os.path.getsize(abspath)

            while not finished:

                blend_file_name = os.path.basename(base_fpath)

                dirn = os.path.dirname(base_fpath)
                fn_strip, ext = os.path.splitext(blend_file_name)

                fn = fn_strip + paths.resolution_suffix[p2res] + ext
                fpath = os.path.join(dirn, fn)

                tex_dir_path = paths.get_texture_directory(asset_data, resolution=p2res)

                tex_dir_abs = bpy.path.abspath(tex_dir_path)
                if not os.path.exists(tex_dir_abs):
                    os.mkdir(tex_dir_abs)

                reduced_textures_filessize = 0
                for i in bpy.data.images:
                    if i.name != 'Render Result':

                        print('scaling ', i.name, i.size[0], i.size[1])
                        fp = get_texture_filepath(tex_dir_path, i, resolution=p2res)

                        if p2res == orig_res:
                            # first, let's link the image back to the original one.
                            i['blenderkit_original_path'] = i.filepath
                            # first round also makes reductions on the image, while keeping resolution
                            image_utils.make_possible_reductions_on_image(i, fp, do_reductions=True, do_downscale=False)

                        else:
                            # lower resolutions only downscale
                            image_utils.make_possible_reductions_on_image(i, fp, do_reductions=False, do_downscale=True)

                        abspath = bpy.path.abspath(i.filepath)
                        if os.path.exists(abspath):
                            reduced_textures_filessize += os.path.getsize(abspath)

                        i.pack()
                # save
                print(fpath)
                # if this isn't here, blender crashes.
                if bpy.app.version>=(3,0,0):
                    bpy.context.preferences.filepaths.file_preview_type = 'NONE'

                # save the file
                bpy.ops.wm.save_as_mainfile(filepath=fpath, compress=True, copy=True)
                # compare file sizes
                print(f'textures size was reduced from {original_textures_filesize} to {reduced_textures_filessize}')
                if reduced_textures_filessize < original_textures_filesize:
                    # this limits from uploaidng especially same-as-original resolution files in case when there is no advantage.
                    # usually however the advantage can be big also for same as original resolution
                    files.append({
                        "type": p2res,
                        "index": 0,
                        "file_path": fpath
                    })

                print('prepared resolution file: ', p2res)
                if rkeys.index(p2res) == 0:
                    finished = True
                else:
                    p2res = rkeys[rkeys.index(p2res) - 1]
            print('uploading resolution files')
            print(files)

            upload_resolutions(files, data['asset_data'], api_key=data['api_key'])
            patch_asset_empty(data['asset_data']['id'], api_key=data['api_key'])
        return


def regenerate_thumbnail_material(data):
    # this should re-generate material thumbnail and re-upload it.
    # first let's skip procedural assets
    base_fpath = bpy.data.filepath
    blend_file_name = os.path.basename(base_fpath)
    bpy.ops.mesh.primitive_cube_add()
    aob = bpy.context.active_object
    bpy.ops.object.material_slot_add()
    aob.material_slots[0].material = bpy.data.materials[0]
    props = aob.active_material.blenderkit
    props.thumbnail_generator_type = 'BALL'
    props.thumbnail_background = False
    props.thumbnail_resolution = '256'
    # layout.prop(props, 'thumbnail_generator_type')
    # layout.prop(props, 'thumbnail_scale')
    # layout.prop(props, 'thumbnail_background')
    # if props.thumbnail_background:
    #     layout.prop(props, 'thumbnail_background_lightness')
    # layout.prop(props, 'thumbnail_resolution')
    # layout.prop(props, 'thumbnail_samples')
    # layout.prop(props, 'thumbnail_denoising')
    # layout.prop(props, 'adaptive_subdivision')
    # preferences = bpy.context.preferences.addons['blenderkit'].preferences
    # layout.prop(preferences, "thumbnail_use_gpu")
    # TODO: here it should call start_material_thumbnailer , but with the wait property on, so it can upload afterwards.
    bpy.ops.object.blenderkit_generate_material_thumbnail()
    time.sleep(130)
    # save
    # this does the actual job

    return


def run_bg(datafile):
    print('background file operation')
    with open(datafile, 'r',encoding='utf-8') as f:
        data = json.load(f)
    bpy.app.debug_value = data['debug_value']
    if data['command'] == 'generate_resolutions':
        print('asset type is ', data['asset_data']['assetType'])

        if data['asset_data']['assetType']=='hdr':
            generate_lower_resolutions_hdr(data)
        else:
            generate_lower_resolutions(data)
    elif data['command'] == 'unpack':
        unpack_asset(data)
    elif data['command'] == 'regen_thumbnail':
        regenerate_thumbnail_material(data)

# load_assets_list()
# generate_lower_resolutions()
# class TestOperator(bpy.types.Operator):
#     """Tooltip"""
#     bl_idname = "object.test_anything"
#     bl_label = "Test Operator"
#
#     @classmethod
#     def poll(cls, context):
#         return True
#
#     def execute(self, context):
#         iterate_for_resolutions()
#         return {'FINISHED'}
#
#
# def register():
#     bpy.utils.register_class(TestOperator)
#
#
# def unregister():
#     bpy.utils.unregister_class(TestOperator)
