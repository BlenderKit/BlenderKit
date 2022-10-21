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
import os
import sys
import time

import bpy
import requests

from blenderkit import (
    append_link,
    global_vars,
    paths,
    reports,
    rerequests,
    tasks_queue,
    utils,
)


BLENDERKIT_EXPORT_DATA = sys.argv[-1]


if __name__ == "__main__":
    try:
        # bg_blender.progress('preparing scene - append data')
        with open(BLENDERKIT_EXPORT_DATA, 'r',encoding='utf-8') as s:
            data = json.load(s)

        bpy.app.debug_value = data.get('debug_value', 0)
        export_data = data['export_data']
        upload_data = data['upload_data']

        bpy.data.scenes.new('upload')
        for s in bpy.data.scenes:
            if s.name != 'upload':
                bpy.data.scenes.remove(s)

        if upload_data['assetType'] == 'model':
            obnames = export_data['models']
            main_source, allobs = append_link.append_objects(file_name=export_data['source_filepath'],
                                                             obnames=obnames,
                                                             rotation=(0, 0, 0))
            g = bpy.data.collections.new(upload_data['name'])
            for o in allobs:
                g.objects.link(o)
            bpy.context.scene.collection.children.link(g)
        elif upload_data['assetType'] == 'scene':
            sname = export_data['scene']
            main_source = append_link.append_scene(file_name=export_data['source_filepath'],
                                                   scenename=sname)
            bpy.data.scenes.remove(bpy.data.scenes['upload'])
            main_source.name = sname
        elif upload_data['assetType'] == 'material':
            matname = export_data['material']
            main_source = append_link.append_material(file_name=export_data['source_filepath'], matname=matname)

        elif upload_data['assetType'] == 'brush':
            brushname = export_data['brush']
            main_source = append_link.append_brush(file_name=export_data['source_filepath'], brushname=brushname)
        try:
            bpy.ops.file.pack_all()
        except Exception as e:
            print(e)

        main_source.blenderkit.uploading = False
        #write ID here.
        main_source.blenderkit.asset_base_id = export_data['assetBaseId']
        main_source.blenderkit.id = export_data['id']

        fpath = os.path.join(export_data['temp_dir'], upload_data['assetBaseId'] + '.blend')

        #if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = 'NONE'

        bpy.ops.wm.save_as_mainfile(filepath=fpath, compress=True, copy=False)
        os.remove(export_data['source_filepath'])


    except Exception as e:
        print(e)
        # bg_blender.progress(e)
        sys.exit(1)
