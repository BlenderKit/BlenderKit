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
import math
import os
import platform
import unicodedata

import bpy
from bpy.app.handlers import persistent
from bpy.props import (  # TODO only keep the ones actually used when cleaning
    BoolProperty,
    StringProperty,
)
from bpy.types import Operator

from . import (
    asset_bar_op,
    bkit_oauth,
    daemon_lib,
    global_vars,
    image_utils,
    paths,
    ratings_utils,
    reports,
    resolutions,
    tasks_queue,
    utils,
    version_checker,
)
from .daemon import tasks


bk_logger = logging.getLogger(__name__)


def check_errors(rdata):
  if rdata.get('statusCode') and int(rdata.get('statusCode')) > 299:
    utils.p(rdata)
    if rdata.get('detail') == 'Invalid token.':
      bkit_oauth.logout()
      return False, "Invalid token. You've been logged out. Use login panel to connect your profile."
    else:
      return False, rdata.get('detail')
  if rdata.get('statusCode') is None and rdata.get('results') is None:
    return False, 'Connection error'
  return True, ''


search_tasks = {}


def update_ad(ad):
  if not ad.get('assetBaseId'):
    try:
      ad['assetBaseId'] = ad['asset_base_id']  # this should stay ONLY for compatibility with older scenes
      ad['assetType'] = ad['asset_type']  # this should stay ONLY for compatibility with older scenes
      ad['verificationStatus'] = ad[
        'verification_status']  # this should stay ONLY for compatibility with older scenes
      ad['author'] = {}
      ad['author']['id'] = ad['author_id']  # this should stay ONLY for compatibility with older scenes
      ad['canDownload'] = ad['can_download']  # this should stay ONLY for compatibility with older scenes
    except Exception as e:
      bk_logger.error('BlenderKit failed to update older asset data')
  return ad


def update_assets_data():  # updates assets data on scene load.
  '''updates some properties that were changed on scenes with older assets.
  The properties were mainly changed from snake_case to CamelCase to fit the data that is coming from the server.
  '''
  datablocks = [
    bpy.data.objects,
    bpy.data.materials,
    bpy.data.brushes,
  ]
  for dtype in datablocks:
    for block in dtype:
      if block.get('asset_data') is not None:
        update_ad(block['asset_data'])

  dicts = [
    'assets used',
  ]
  for s in bpy.data.scenes:
    for bkdict in dicts:

      d = s.get(bkdict)
      if not d:
        continue

      for asset_id in d.keys():
        update_ad(d[asset_id])
        # bpy.context.scene['assets used'][ad] = ad


@persistent
def undo_post_reload_previews(context):
  load_previews()


@persistent
def undo_pre_end_assetbar(context):
  ui_props = bpy.context.window_manager.blenderkitUI

  ui_props.turn_off = True
  ui_props.assetbar_on = False


@persistent
def scene_load(context):
  """Load categories , check timers registration, and update scene asset data.
  Should (probably) also update asset data from server (after user consent).
  """
  if not bpy.app.timers.is_registered(bkit_oauth.refresh_token_timer) and not bpy.app.background:
    bpy.app.timers.register(bkit_oauth.refresh_token_timer, persistent=True, first_interval=5)
    #bpy.app.timers.register(bkit_oauth.refresh_token_timer, persistent=True, first_interval=36000)

  update_assets_data()


last_clipboard = ''
def check_clipboard():
  """Check clipboard for an exact string containing asset ID.
  The string is generated on www.blenderkit.com as for example here:
  https://www.blenderkit.com/get-blenderkit/54ff5c85-2c73-49e9-ba80-aec18616a408/
  """
  # clipboard monitoring to search assets from web
  if platform.system() != 'Linux':
    global last_clipboard
    if bpy.context.window_manager.clipboard != last_clipboard:
      last_clipboard = bpy.context.window_manager.clipboard
      instr = 'asset_base_id:'
      # first check if contains asset id, then asset type
      if last_clipboard[:len(instr)] == instr:
        atstr = 'asset_type:'
        ati = last_clipboard.find(atstr)
        # this only checks if the asset_type keyword is there but let's the keywords update function do the parsing.
        if ati > -1:
          search_props = utils.get_search_props()
          search_props.search_keywords = last_clipboard
          # don't run search after this - assigning to keywords runs the search_update function.
        # bpy.context.window_manager.clipboard = ''


def parse_result(r):
  """Needed to generate some extra data in the result(by now)
  Parameters
  ----------
  r - search result, also called asset_data
  """
  scene = bpy.context.scene
  # TODO remove this fix when filesSize is fixed.
  # this is a temporary fix for too big numbers from the server.
  # can otherwise get the Python int too large to convert to C int
  try:
      r['filesSize'] = int(r['filesSize'] / 1024)
  except:
      utils.p('asset with no files-size')

  asset_type = r['assetType']
  #TODO: REVERSE THIS CONDITION AND RETURN
  if len(r['files']) > 0:  # TODO remove this condition so all assets are parsed.
    generate_author_profile(r['author'])

    r['available_resolutions'] = []
    use_webp = True
    if bpy.app.version < (3,4,0) or r.get('webpGeneratedTimestamp') == None:
      use_webp = False #WEBP was optimized in Blender 3.4.0

    # BIG THUMB - HDR CASE
    if r['assetType'] == 'hdr':
      if use_webp:
        thumb_url = r.get('thumbnailLargeUrlNonsquaredWebp')
      else:
        thumb_url = r.get('thumbnailLargeUrlNonsquared')
    # BIG THUMB - NON HDR CASE
    else:
      if use_webp:
        thumb_url = r.get('thumbnailMiddleUrlWebp')
      else:
        thumb_url = r.get('thumbnailMiddleUrl')
    
    # SMALL THUMB
    if use_webp:
      small_thumb_url = r.get('thumbnailSmallUrlWebp')
    else:
      small_thumb_url = r.get('thumbnailSmallUrl')

    tname = paths.extract_filename_from_url(thumb_url)
    small_tname = paths.extract_filename_from_url(small_thumb_url)
    for f in r['files']:
      # if f['fileType'] == 'thumbnail':
      #     tname = paths.extract_filename_from_url(f['fileThumbnailLarge'])
      #     small_tname = paths.extract_filename_from_url(f['fileThumbnail'])
      #     allthumbs.append(tname)  # TODO just first thumb is used now.

      if f['fileType'] == 'blend':
        durl = f['downloadUrl'].split('?')[0]
        # fname = paths.extract_filename_from_url(f['filePath'])

      if f['fileType'].find('resolution') > -1:
        r['available_resolutions'].append(resolutions.resolutions[f['fileType']])

    # code for more thumbnails
    # tdict = {}
    # for i, t in enumerate(allthumbs):
    #     tdict['thumbnail_%i'] = t

    r['max_resolution'] = 0
    if r['available_resolutions']:  # should check only for non-empty sequences
      r['max_resolution'] = max(r['available_resolutions'])

    # tooltip = generate_tooltip(r)
    # for some reason, the id was still int on some occurances. investigate this.
    r['author']['id'] = str(r['author']['id'])

    # some helper props, but generally shouldn't be renaming/duplifiying original properties,
    # so blender's data is same as on server.
    asset_data = {'thumbnail': tname,
                  'thumbnail_small': small_tname,
                  # 'tooltip': tooltip,
                  }
    asset_data['downloaded'] = 0

    # parse extra params needed for blender here
    params = r['dictParameters']  # utils.params_to_dict(r['parameters'])

    if asset_type == 'model':
      if params.get('boundBoxMinX') != None:
        bbox = {
          'bbox_min': (
            float(params['boundBoxMinX']),
            float(params['boundBoxMinY']),
            float(params['boundBoxMinZ'])),
          'bbox_max': (
            float(params['boundBoxMaxX']),
            float(params['boundBoxMaxY']),
            float(params['boundBoxMaxZ']))
        }

      else:
        bbox = {
          'bbox_min': (-.5, -.5, 0),
          'bbox_max': (.5, .5, 1)
        }
      asset_data.update(bbox)
    if asset_type == 'material':
      asset_data['texture_size_meters'] = params.get('textureSizeMeters', 1.0)

    # asset_data.update(tdict)

    au = scene.get('assets used', {})
    if au == {}:
      scene['assets used'] = au
    if r['assetBaseId'] in au.keys():
      asset_data['downloaded'] = 100
      # transcribe all urls already fetched from the server
      r_previous = au[r['assetBaseId']]
      if r_previous.get('files'):
        for f in r_previous['files']:
          if f.get('url'):
            for f1 in r['files']:
              if f1['fileType'] == f['fileType']:
                f1['url'] = f['url']

    # attempt to switch to use original data gradually, since the parsing as itself should become obsolete.
    asset_data.update(r)
    return asset_data


def clear_searches():
  global search_tasks
  search_tasks.clear()


def cleanup_search_results():
  dicts = (
    'search results','bkit model search',
    'bkit scene search',
    'bkit hdr search',
    'bkit material search',
    'bkit texture search',
    'bkit brush search',
  )
  for sr in dicts:
    global_vars.DATA.pop(sr, None)
    global_vars.DATA.pop(f'{sr} orig', None)

def handle_search_task(task: tasks.Task) -> bool:
  """Parse search results, try to load all available previews."""
  global search_tasks
  if len(search_tasks) == 0:
    # utils.p('end search timer')
    props = utils.get_search_props()
    props.is_searching = False
    return True

  # don't do anything while dragging - this could switch asset during drag, and make results list length different,
  # causing a lot of throuble.
  if bpy.context.window_manager.blenderkitUI.dragging:
    # utils.p('end search timer')
    return False
  # if original task was already removed (because user initiated another search), results are dropped- Returns True
  # because that's OK.
  orig_task = search_tasks.get(task.task_id)
  if orig_task is None:
    print('search task result not from active search', task.task_id, len(search_tasks), list(search_tasks.keys()))
    return True

  search_tasks.pop(task.task_id)

  # this fixes black thumbnails in asset bar, test if this bug still persist in blender and remove if it's fixed
  if bpy.app.version < (3, 3, 0):
    sys_prefs = bpy.context.preferences.system
    sys_prefs.gl_texture_limit = 'CLAMP_OFF'

  ###################

  asset_type = task.data['asset_type']
  props = utils.get_search_props()
  search_name = f'bkit {asset_type} search'

  if not task.data.get('get_next'):
    result_field = []
  else:
    result_field = []
    for r in global_vars.DATA[search_name]:
      result_field.append(r)

  ok, error = check_errors(task.result)
  if ok:
    ui_props = bpy.context.window_manager.blenderkitUI

    for ri, r in enumerate(task.result['results']):
      asset_data = parse_result(r)
      if asset_data is not None:
        result_field.append(asset_data)

    # Get ratings from BlenderKit server TODO: do this in daemon
    if utils.profile_is_validator():
      for result in task.result['results']:
        ratings_utils.ensure_rating(result['id'])

    global_vars.DATA[search_name] = result_field
    global_vars.DATA[f'{search_name} orig'] = task.result

    if result_field and result_field[0]['assetType'] == ui_props.asset_type.lower():
      global_vars.DATA['search results'] = result_field
      global_vars.DATA['search results orig'] = task.result

    if len(result_field) < ui_props.scroll_offset or not (task.data.get('get_next')):
      # jump back
      ui_props.scroll_offset = 0
    props.report = f"Found {global_vars.DATA['search results orig']['count']} results."
    if len(global_vars.DATA['search results']) == 0:
      tasks_queue.add_task((reports.add_report, ('No matching results found.',)))
    else:
      tasks_queue.add_task((reports.add_report, (f"Found {global_vars.DATA['search results orig']['count']} results.",)))
    # show asset bar automatically, but only on first page - others are loaded also when asset bar is hidden.
    if not ui_props.assetbar_on and not task.data.get('get_next'):
      bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)

  else:
    props.report = error
    reports.add_report(error, 15, 'ERROR')

  if len(search_tasks) == 0:
    props.is_searching = False
  return True


def handle_preview_task(task: tasks.Task) -> bool:
  """Parse search results, try to load all available previews."""

  global_vars.DATA['images available'][task.data['image_path']] = True
  if asset_bar_op.asset_bar_operator is not None:
    if task.data['thumbnail_type'] =='small':
      asset_bar_op.asset_bar_operator.update_image(task.data['assetBaseId'])
    if task.data['thumbnail_type'] == 'full':
      asset_bar_op.asset_bar_operator.update_tooltip_image(task.data['assetBaseId'])
  return True


def load_preview(asset):
  # FIRST START SEARCH
  props = bpy.context.window_manager.blenderkitUI
  directory = paths.get_temp_dir('%s_search' % props.asset_type.lower())

  tpath = os.path.join(directory, asset['thumbnail_small'])
  tpath_exists = os.path.exists(tpath)
  if not asset['thumbnail_small'] or asset['thumbnail_small'] == '' or not tpath_exists:
    # tpath = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')
    asset['thumb_small_loaded'] = False

  iname = f".{asset['thumbnail_small']}"
  # if os.path.exists(tpath):  # sometimes we are unlucky...
  img = bpy.data.images.get(iname)

  if img is None or len(img.pixels) == 0:
    if not tpath_exists:
      return False
    # wrap into try statement since sometimes
    try:
      img = bpy.data.images.load(tpath, check_existing=True)

      img.name = iname
      if len(img.pixels) > 0:
        return True
    except:
      pass
    return False
  elif img.filepath != tpath:
    if not tpath_exists:
      # unload loaded previews from previous results
      bpy.data.images.remove(img)
      return False
    # had to add this check for autopacking files...
    if bpy.data.use_autopack and img.packed_file is not None:
      img.unpack(method='USE_ORIGINAL')
    img.filepath = tpath
    try:
      img.reload()
    except:
      return False

  if asset['assetType'] == 'hdr':
    # to display hdr thumbnails correctly, we use non-color, otherwise looks shifted
    image_utils.set_colorspace(img, 'Non-Color')
  else:
    image_utils.set_colorspace(img, 'sRGB')
  asset['thumb_small_loaded'] = True
  return True


def load_previews():
  results = global_vars.DATA.get('search results')
  if results is not None:
    for i, result in enumerate(results):
      load_preview(result)


#  line splitting for longer texts...
def split_subs(text, threshold=40):
  if text == '':
    return []
  # temporarily disable this, to be able to do this in drawing code

  text = text.rstrip()
  text = text.replace('\r\n', '\n')

  lines = []

  while len(text) > threshold:
    # first handle if there's an \n line ending
    i_rn = text.find('\n')
    if 1 < i_rn < threshold:
      i = i_rn
      text = text.replace('\n', '', 1)
    else:
      i = text.rfind(' ', 0, threshold)
      i1 = text.rfind(',', 0, threshold)
      i2 = text.rfind('.', 0, threshold)
      i = max(i, i1, i2)
      if i <= 0:
        i = threshold
    lines.append(text[:i])
    text = text[i:]
  lines.append(text)
  return lines


def list_to_str(input):
  output = ''
  for i, text in enumerate(input):
    output += text
    if i < len(input) - 1:
      output += ', '
  return output


def writeblock(t, input, width=40):  # for longer texts
  dlines = split_subs(input, threshold=width)
  for i, l in enumerate(dlines):
    t += '%s\n' % l
  return t


def writeblockm(tooltip, mdata, key='', pretext=None, width=40):  # for longer texts
  if mdata.get(key) == None:
    return tooltip
  else:
    intext = mdata[key]
    if type(intext) == list:
      intext = list_to_str(intext)
    if type(intext) == float:
      intext = round(intext, 3)
    intext = str(intext)
    if intext.rstrip() == '':
      return tooltip
    if pretext == None:
      pretext = key
    if pretext != '':
      pretext = pretext + ': '
    text = pretext + intext
    dlines = split_subs(text, threshold=width)
    for i, l in enumerate(dlines):
      tooltip += '%s\n' % l

  return tooltip


def has(mdata, prop):
  if mdata.get(prop) is not None and mdata[prop] is not None and mdata[prop] is not False:
    return True
  else:
    return False


def generate_tooltip(mdata):
  col_w = 40
  if type(mdata['parameters']) == list:
    mparams = utils.params_to_dict(mdata['parameters'])
  else:
    mparams = mdata['parameters']
  t = ''
  t = writeblock(t, mdata['displayName'], width=int(col_w * .6))
  # t += '\n'

  # t = writeblockm(t, mdata, key='description', pretext='', width=col_w)
  return t


def generate_author_textblock(adata):
  t = ''
  if adata not in (None, ''):
    col_w = 2000
    if len(adata['firstName'] + adata['lastName']) > 0:
      t = '%s %s\n' % (adata['firstName'], adata['lastName'])
      t += '\n'
      if adata.get('aboutMe') is not None:
        t = writeblockm(t, adata, key='aboutMe', pretext='', width=col_w)
  return t


def handle_fetch_gravatar_task(task: tasks.Task):
  """Handle incomming fetch_gravatar_task which contains path to author's image on the disk."""
  if task.status == 'finished':
    author_id = str(task.data['id'])
    gravatar_path = task.result['gravatar_path']
    global_vars.DATA['bkit authors'][author_id]['gravatarImg'] = gravatar_path


def generate_author_profile(author_data):
  """Generate author profile by creating author textblock and fetching gravatar image if needed.
  Gravatar dokkjjwnload is started in daemon and handled later."""
  author_id = str(author_data['id'])
  if author_id in global_vars.DATA['bkit authors']:
    return
  daemon_lib.fetch_gravatar_image(author_data)
  author_data['tooltip'] = generate_author_textblock(author_data)
  global_vars.DATA['bkit authors'][author_id] = author_data
  return


def handle_get_user_profile(task: tasks.Task):
  """Handle incomming get_user_profile task which contains data about current logged-in user."""
  if task.status == 'finished':
    user_data = task.result
    global_vars.DATA['bkit profile'] = user_data


def query_to_url(query={}, params={}):
  # build a new request
  url = f'{paths.BLENDERKIT_API}/search/'

  # build request manually
  # TODO use real queries
  requeststring = '?query='
  #
  if query.get('query') not in ('', None):
    requeststring += query['query'].lower()
  for i, q in enumerate(query):
    if q != 'query' and q!='free_first':
      requeststring += '+'
      requeststring += q + ':' + str(query[q]).lower()

  # add dict_parameters to make results smaller
  # result ordering: _score - relevance, score - BlenderKit score
  order = []
  if query.get('free_first', False):
    order = ['-is_free', ]
  if query.get('query') is None and query.get('category_subtree') == None:
    # assumes no keywords and no category, thus an empty search that is triggered on start.
    # orders by last core file upload
    if query.get('verification_status') == 'uploaded':
      # for validators, sort uploaded from oldest
      order.append('created')
    else:
      order.append('-last_upload')
  elif query.get('author_id') is not None and utils.profile_is_validator():

    order.append('-created')
  else:
    if query.get('category_subtree') is not None:
      order.append('-score,_score')
    else:
      order.append('_score')
  if requeststring.find('+order:') == -1:
    requeststring += '+order:' + ','.join(order)
  requeststring += '&dict_parameters=1'

  requeststring += '&page_size=' + str(params['page_size'])
  requeststring += '&addon_version=%s' % params['addon_version']
  if not (query.get('query') and query.get('query').find('asset_base_id')>-1):
    requeststring += '&blender_version=%s' % params['blender_version']
  if params.get('scene_uuid') is not None:
    requeststring += '&scene_uuid=%s' % params['scene_uuid']
  urlquery = url + requeststring
  return urlquery


def build_query_common(query, props):
  """Add shared parameters to query."""
  query_common = {}
  if props.search_keywords != '':
    # keywords = urllib.parse.urlencode(props.search_keywords)
    keywords = props.search_keywords.replace('&', '%26')
    query_common["query"] = keywords

  if props.search_verification_status != 'ALL' and utils.profile_is_validator():
    query_common['verification_status'] = props.search_verification_status.lower()

  if props.unrated_only and utils.profile_is_validator():
    query["quality_count"] = 0

  if props.search_file_size:
    query_common["files_size_gte"] = props.search_file_size_min * 1024 * 1024
    query_common["files_size_lte"] = props.search_file_size_max * 1024 * 1024

  if props.quality_limit > 0:
    query["quality_gte"] = props.quality_limit

  query.update(query_common)


def build_query_model():
  """Use all search input to request results from server."""
  props = bpy.context.window_manager.blenderkit_models
  query = {
    "asset_type": 'model',
    # "engine": props.search_engine,
    # "adult": props.search_adult,
  }
  if props.search_style != 'ANY':
    if props.search_style != 'OTHER':
      query["model_style"] = props.search_style
    else:
      query["model_style"] = props.search_style_other

  # the 'free_only' parametr gets moved to the search command and is used for ordering the assets as free first
  # if props.free_only:
  #     query["is_free"] = True

  if props.search_condition != 'UNSPECIFIED':
    query["condition"] = props.search_condition

  if props.search_design_year:
    query["designYear_gte"] = props.search_design_year_min
    query["designYear_lte"] = props.search_design_year_max
  if props.search_polycount:
    query["faceCount_gte"] = props.search_polycount_min
    query["faceCount_lte"] = props.search_polycount_max
  if props.search_texture_resolution:
    query["textureResolutionMax_gte"] = props.search_texture_resolution_min
    query["textureResolutionMax_lte"] = props.search_texture_resolution_max
  if props.search_animated:
    query["animated"] = True
  if props.search_geometry_nodes:
    query["modifiers"] = 'nodes'

  build_query_common(query, props)

  return query


def build_query_scene():
  """Use all search input to request results from server."""
  props = bpy.context.window_manager.blenderkit_scene
  query = {
    "asset_type": 'scene',
    # "engine": props.search_engine,
    # "adult": props.search_adult,
  }
  build_query_common(query, props)
  return query


def build_query_HDR():
  """Use all search input to request results from server."""
  props = bpy.context.window_manager.blenderkit_HDR
  query = {
    "asset_type": 'hdr',
    # "engine": props.search_engine,
    # "adult": props.search_adult,
  }
  if props.true_hdr:
    query["trueHDR"] = props.true_hdr
  build_query_common(query, props)
  return query


def build_query_material():
  props = bpy.context.window_manager.blenderkit_mat
  query = {"asset_type": 'material'}
  # if props.search_engine == 'NONE':
  #     query["engine"] = ''
  # if props.search_engine != 'OTHER':
  #     query["engine"] = props.search_engine
  # else:
  #     query["engine"] = props.search_engine_other
  if props.search_style != 'ANY':
    if props.search_style != 'OTHER':
      query["style"] = props.search_style
    else:
      query["style"] = props.search_style_other
  if props.search_procedural == 'TEXTURE_BASED':
    # todo this procedural hack should be replaced with the parameter
    query["textureResolutionMax_gte"] = 0
    # query["procedural"] = False
    if props.search_texture_resolution:
      query["textureResolutionMax_gte"] = props.search_texture_resolution_min
      query["textureResolutionMax_lte"] = props.search_texture_resolution_max
  elif props.search_procedural == "PROCEDURAL":
    # todo this procedural hack should be replaced with the parameter
    query["files_size_lte"] = 1024 * 1024
    # query["procedural"] = True

  build_query_common(query, props)
  return query


def build_query_texture():
  props = bpy.context.scene.blenderkit_tex
  query = {"asset_type": 'texture'}

  if props.search_style != 'ANY':
    if props.search_style != 'OTHER':
      query["search_style"] = props.search_style
    else:
      query["search_style"] = props.search_style_other

  build_query_common(query, props)
  return query


def build_query_brush():
  props = bpy.context.window_manager.blenderkit_brush
  brush_type = ''
  if bpy.context.sculpt_object is not None:
    brush_type = 'sculpt'

  elif bpy.context.image_paint_object:  # could be just else, but for future p
    brush_type = 'texture_paint'

  query = {
    "asset_type": 'brush',
    "mode": brush_type
  }

  build_query_common(query, props)
  return query


def add_search_process(query, params):
  global search_tasks
  if len(search_tasks) > 0:
    # just remove all running search tasks.
    # we can also kill them in daemon, but not so urgent now
    # TODO stop tasks in daemon?
    bk_logger.debug('Removing old search tasks')
    search_tasks = dict()

  tempdir = paths.get_temp_dir('%s_search' % query['asset_type'])
  if params.get('get_next'):
    urlquery = params['next']
  else:
    urlquery = query_to_url(query, params)

  data = {
    'PREFS': utils.get_prefs_dir(),
    'tempdir': tempdir,
    'urlquery': urlquery,
    'asset_type': query['asset_type'],
  }
  data.update(params)
  response = daemon_lib.search_asset(data)
  search_tasks[response['task_id']] = data


def get_search_simple(parameters, filepath=None, page_size=100, max_results=100000000, api_key=''):
  """Searches and returns the search results.

  Parameters
  ----------
  parameters - dict of blenderkit elastic parameters
  filepath - a file to save the results. If None, results are returned
  page_size - page size for retrieved results
  max_results - max results of the search
  api_key - BlenderKit api key

  Returns
  -------
  Returns search results as a list, and optionally saves to filepath
  """
  headers = utils.get_headers(api_key)
  url = f'{paths.BLENDERKIT_API}/search/'
  requeststring = url + '?query='
  for p in parameters.keys():
    requeststring += f'+{p}:{parameters[p]}'

  requeststring += '&page_size=' + str(page_size)
  requeststring += '&dict_parameters=1'

  bk_logger.debug(requeststring)
  response = daemon_lib.blocking_request(requeststring, 'GET', headers)

  # print(response.json())
  search_results = response.json()

  results = []
  results.extend(search_results['results'])
  page_index = 2
  page_count = math.ceil(search_results['count'] / page_size)
  while search_results.get('next') and len(results) < max_results:
    bk_logger.info(f'getting page {page_index} , total pages {page_count}')
    response = daemon_lib.blocking_request(search_results['next'], 'GET', headers)
    search_results = response.json()
    results.extend(search_results['results'])
    page_index += 1

  if not filepath:
    return results

  with open(filepath, 'w', encoding='utf-8') as s:
    json.dump(results, s, ensure_ascii=False, indent=4)
  bk_logger.info(f'retrieved {len(results)} assets from elastic search')
  return results


def search(category='', get_next=False, query = None, author_id=''):
  """Initialize searching
  query : submit an already built query from search history
  """
  if global_vars.DAEMON_ACCESSIBLE != True:
    reports.add_report('Cannot search, daemon is not accessible.', timeout = 2, type='ERROR')
    return

  user_preferences = bpy.context.preferences.addons['blenderkit'].preferences

  wm = bpy.context.window_manager
  ui_props = bpy.context.window_manager.blenderkitUI

  props = utils.get_search_props()
  # it's possible get_next was requested more than once.
  if props.is_searching and get_next == True:
    # search already running, skipping
    return

  if not query:
    if ui_props.asset_type == 'MODEL':
      if not hasattr(wm, 'blenderkit_models'):
        return
      query = build_query_model()

    if ui_props.asset_type == 'SCENE':
      if not hasattr(wm, 'blenderkit_scene'):
        return
      query = build_query_scene()

    if ui_props.asset_type == 'HDR':
      if not hasattr(wm, 'blenderkit_HDR'):
        return
      query = build_query_HDR()

    if ui_props.asset_type == 'MATERIAL':
      if not hasattr(wm, 'blenderkit_mat'):
        return
      query = build_query_material()

    if ui_props.asset_type == 'TEXTURE':
      if not hasattr(wm, 'blenderkit_tex'):
        return
      # props = scene.blenderkit_tex
      # query = build_query_texture()

    if ui_props.asset_type == 'BRUSH':
      if not hasattr(wm, 'blenderkit_brush'):
        return
      query = build_query_brush()

    # crop long searches
    if query.get('query'):
      if len(query['query']) > 50:
        query['query'] = strip_accents(query['query'])

      if len(query['query']) > 150:
        idx = query['query'].find(' ', 142)
        query['query'] = query['query'][:idx]

    if category != '':
      if utils.profile_is_validator() and user_preferences.categories_fix:
        query['category'] = category
      else:
        query['category_subtree'] = category

    if author_id != '':
      query['author_id'] = author_id

    elif props.own_only:
      # if user searches for [another] author, 'only my assets' is invalid. that's why in elif.
      profile = global_vars.DATA.get('bkit profile')
      if profile is not None:
        query['author_id'] = str(profile['user']['id'])

    # free first has to by in query to be evaluated as changed as another search, otherwise the filter is not updated.
    query['free_first'] = props.free_only

    if not get_next:
      #write to search history and check history length
      if len(global_vars.DATA['search history'])>0 and global_vars.DATA['search history'][-1] == query:
        # don't send same query again, when user clicks multiple times and waits e.t.c.
        return

      global_vars.DATA['search history'].append(query)
  # utils.p('searching')
  props.is_searching = True

  page_size = min(40, ui_props.wcount * user_preferences.max_assetbar_rows + 5)
  params = {
    'scene_uuid': bpy.context.scene.get('uuid', None),
    'addon_version': version_checker.get_addon_version(),
    'blender_version': version_checker.get_blender_version(),
    'api_key': user_preferences.api_key,
    'get_next': get_next,
    'page_size': page_size,
  }

  orig_results = global_vars.DATA.get(f'bkit {ui_props.asset_type.lower()} search orig')
  if orig_results is not None and get_next:
    params['next'] = orig_results['next']
  add_search_process(query, params)
  props.report = 'BlenderKit searching....'

def clean_filters():
  """Cleanup filters in case search needs to be reset, typicaly when asset id is copy pasted."""
  sprops = utils.get_search_props()
  ui_props = bpy.context.window_manager.blenderkitUI
  sprops.property_unset('own_only')
  sprops.property_unset('search_texture_resolution')
  sprops.property_unset('search_file_size')
  sprops.property_unset('search_procedural')
  sprops.property_unset('free_only')
  sprops.property_unset('quality_limit')
  if ui_props.asset_type == 'MODEL':
    sprops.property_unset('search_style')
    sprops.property_unset('search_condition')
    sprops.property_unset('search_design_year')
    sprops.property_unset('search_polycount')
    sprops.property_unset('search_animated')
    sprops.property_unset('search_geometry_nodes')
  if ui_props.asset_type == 'HDR':
    sprops.true_hdr = False


def update_filters():
  sprops = utils.get_search_props()
  ui_props = bpy.context.window_manager.blenderkitUI
  fcommon = sprops.own_only or \
            sprops.search_texture_resolution or \
            sprops.search_file_size or \
            sprops.search_procedural != 'BOTH' or \
            sprops.free_only or \
            sprops.quality_limit > 0

  if ui_props.asset_type == 'MODEL':
    sprops.use_filters = fcommon or \
                         sprops.search_style != 'ANY' or \
                         sprops.search_condition != 'UNSPECIFIED' or \
                         sprops.search_design_year or \
                         sprops.search_polycount or \
                         sprops.search_animated or \
                         sprops.search_geometry_nodes
  elif ui_props.asset_type == 'MATERIAL':
    sprops.use_filters = fcommon
  elif ui_props.asset_type == 'HDR':
    sprops.use_filters = sprops.true_hdr

def search_update_delayed(self,context):
  '''run search after user changes a search parameter,
  but with a delay.
  This reduces number of calls during slider UI interaction (like texture resolution, polycount)
  '''
  tasks_queue.add_task((search_update, (None, None)), wait=0.5, only_last=True)

def search_update(self, context):
  '''run search after user changes a search parameter'''
  # if self.search_keywords != '':
  update_filters()
  ui_props = bpy.context.window_manager.blenderkitUI
  if ui_props.down_up != 'SEARCH':
    ui_props.down_up = 'SEARCH'

  # here we tweak the input if it comes form the clipboard. we need to get rid of asset type and set it in UI
  sprops = utils.get_search_props()
  instr = 'asset_base_id:'
  atstr = 'asset_type:'
  kwds = sprops.search_keywords
  id_index = kwds.find(instr)
  if id_index>-1:
    asset_type_index = kwds.find(atstr)
    # if the asset type already isn't there it means this update function
    # was triggered by it's last iteration and needs to cancel
    if asset_type_index > -1:
      asset_type_string = kwds[asset_type_index:].lower()
      # uncertain length of the remaining string -  find as better method to check the presence of asset type
      if asset_type_string.find('model') > -1:
        target_asset_type = 'MODEL'
      elif asset_type_string.find('material') > -1:
        target_asset_type = 'MATERIAL'
      elif asset_type_string.find('brush') > -1:
        target_asset_type = 'BRUSH'
      elif asset_type_string.find('scene') > -1:
        target_asset_type = 'SCENE'
      elif asset_type_string.find('hdr') > -1:
        target_asset_type = 'HDR'
      if ui_props.asset_type != target_asset_type:
        sprops.search_keywords = ''
        ui_props.asset_type = target_asset_type

      # now we trim the input copypaste by anything extra that is there,
      # this is also a way for this function to recognize that it already has parsed the clipboard
      # the search props can have changed and this needs to transfer the data to the other field
      # this complex behaviour is here for the case where the user needs to paste manually into blender,
      # Otherwise it could be processed directly in the clipboard check function.
      sprops = utils.get_search_props()
      clean_filters()
      sprops.search_keywords = kwds[:asset_type_index].rstrip()
      # return here since writing into search keywords triggers this update function once more.
      return

  if global_vars.DAEMON_ACCESSIBLE:
    reports.add_report(f"Searching for: '{kwds}'", 2)
  search()


# accented_string is of type 'unicode'
def strip_accents(s):
  return ''.join(c for c in unicodedata.normalize('NFD', s)
                 if unicodedata.category(c) != 'Mn')

#TODO: fix the tooltip?
class SearchOperator(Operator):
  """Tooltip"""
  bl_idname = "view3d.blenderkit_search"
  bl_label = "BlenderKit asset search"
  bl_description = "Search online for assets"
  bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

  esc: BoolProperty(name="Escape window",
                    description="Escape window right after start",
                    default=False,
                    options={'SKIP_SAVE'}
                    )

  own: BoolProperty(name="own assets only",
                    description="Find all own assets",
                    default=False,
                    options={'SKIP_SAVE'})

  category: StringProperty(
    name="category",
    description="search only subtree of this category",
    default="",
    options={'SKIP_SAVE'}
  )

  author_id: StringProperty(
    name="Author ID",
    description="Author ID - search only assets by this author",
    default="",
    options={'SKIP_SAVE'}
  )

  get_next: BoolProperty(name="next page",
                         description="get next page from previous search",
                         default=False,
                         options={'SKIP_SAVE'}
                         )

  keywords: StringProperty(
    name="Keywords",
    description="Keywords",
    default="",
    options={'SKIP_SAVE'}
  )

  # close_window: BoolProperty(name='Close window',
  #                            description='Try to close the window below mouse before download',
  #                            default=False)

  tooltip: bpy.props.StringProperty(default='Runs search and displays the asset bar at the same time')

  @classmethod
  def description(cls, context, properties):
    return properties.tooltip

  @classmethod
  def poll(cls, context):
    return True

  def execute(self, context):
    # TODO ; this should all get transferred to properties of the search operator, so sprops don't have to be fetched here at all.
    if self.esc:
      bpy.ops.view3d.close_popup_button('INVOKE_DEFAULT')
    sprops = utils.get_search_props()
    if self.author_id != '':
      sprops.search_keywords = ''
    if self.keywords != '':
      sprops.search_keywords = self.keywords

    search(category=self.category, get_next=self.get_next, author_id=self.author_id)
    # bpy.ops.view3d.blenderkit_asset_bar_widget()

    return {'FINISHED'}

  # def invoke(self, context, event):
  #     if self.close_window:
  #         context.window.cursor_warp(event.mouse_x, event.mouse_y - 100);
  #         context.area.tag_redraw()
  #
  #         context.window.cursor_warp(event.mouse_x, event.mouse_y);
  #     return self. execute(context)


class UrlOperator(Operator):
  """"""
  bl_idname = "wm.blenderkit_url"
  bl_label = ""
  bl_description = "Search online for assets"
  bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

  tooltip: bpy.props.StringProperty(default='Open a web page')
  url: bpy.props.StringProperty(default='Runs search and displays the asset bar at the same time')

  @classmethod
  def description(cls, context, properties):
    return properties.tooltip

  def execute(self, context):
    bpy.ops.wm.url_open(url=self.url)
    return {'FINISHED'}


class TooltipLabelOperator(Operator):
  """"""
  bl_idname = "wm.blenderkit_tooltip"
  bl_label = ""
  bl_description = "Empty operator to be able to create tooltips on labels in UI"
  bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

  tooltip: bpy.props.StringProperty(default='Open a web page')

  @classmethod
  def description(cls, context, properties):
    return properties.tooltip

  def execute(self, context):
    return {'FINISHED'}


classes = [
  SearchOperator,
  UrlOperator,
  TooltipLabelOperator
]


def register_search():
  bpy.app.handlers.load_post.append(scene_load)
  bpy.app.handlers.load_post.append(undo_post_reload_previews)
  bpy.app.handlers.undo_post.append(undo_post_reload_previews)
  bpy.app.handlers.undo_pre.append(undo_pre_end_assetbar)

  for c in classes:
    bpy.utils.register_class(c)


def unregister_search():
  bpy.app.handlers.load_post.remove(scene_load)

  for c in classes:
    bpy.utils.unregister_class(c)

