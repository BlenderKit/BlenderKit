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
import threading

# mainly update functions and callbacks for ratings properties, here to avoid circular imports.
import bpy

from . import global_vars, paths, rerequests, search, tasks_queue, utils


bk_logger = logging.getLogger(__name__)


def upload_comment_thread(asset_id, comment_id=0, comment='', api_key=None):
  ''' Upload comment thread function / disconnected from blender data.'''
  headers = utils.get_headers(api_key)
  url = f'{paths.BLENDERKIT_API}/comments/asset-comment/{asset_id}/'
  r = rerequests.get(url, headers=headers)
  comment_data = r.json()
  url = f'{paths.BLENDERKIT_API}/comments/comment/'
  data = {
    "name": "",
    "email": "",
    "url": "",
    "followup": comment_id > 0,
    "reply_to": comment_id,
    "honeypot": "",
    "content_type": "assets.uuidasset",
    "object_pk": asset_id,
    "timestamp": comment_data['form']['timestamp'],
    "security_hash": comment_data['form']['securityHash'],
    "comment": comment,
  }

  r = rerequests.post(url, data=data, verify=True, headers=headers)

  get_comments(asset_id, api_key)


def upload_comment_flag_thread(asset_id='', comment_id='', flag='like', api_key=None):
  ''' Upload rating thread function / disconnected from blender data.'''
  headers = utils.get_headers(api_key)

  bk_logger.debug('upload comment flag' + str(comment_id))

  # rating_url = url + rating_name + '/'
  data = {
    "comment": comment_id,
    "flag": flag,
  }
  url = paths.BLENDERKIT_API + '/comments/feedback/'
  r = rerequests.post(url, data=data, verify=True, headers=headers)
  bk_logger.info(f'{r.text}')
  # here it's important we read back, so likes are updated accordingly:
  get_comments(asset_id, api_key)

def upload_comment_is_private_thread(asset_id='', comment_id='', is_private=False, api_key=None):
  ''' Upload rating thread function / disconnected from blender data.'''
  headers = utils.get_headers(api_key)

  bk_logger.debug('upload comment is private' + str(comment_id))

  # rating_url = url + rating_name + '/'
  data = {
    "is_private": is_private,
  }
  url = f"{paths.BLENDERKIT_API}/comments/is_private/{comment_id}/"
  r = rerequests.post(url, data=data, verify=True, headers=headers)
  bk_logger.debug(r.text)
  
  # here it's important we read back, so likes are updated accordingly:
  get_comments(asset_id, api_key)

# def comment_delete_thread(asset_id='', comment_id='', api_key=None):
#   ''' Upload rating thread function / disconnected from blender data.'''
#   headers = utils.get_headers(api_key)
#   bk_logger.debug('delete comment ' + str(comment_id))
# 
#   # rating_url = url + rating_name + '/'
#   data = {
#     "comment": comment_id,
#   }
#   url = paths.BLENDERKIT_API + '/comments/delete/0/'
#   r = rerequests.post(url, data=data, verify=True, headers=headers)
#   if len(r.text)<1000:
#   # here it's important we read back, so likes are updated accordingly:
#   get_comments(asset_id, api_key)

def send_comment_flag_to_thread(asset_id='', comment_id='', flag='like', api_key=None):
  '''Sens rating into thread rating, main purpose is for tasks_queue.
  One function per property to avoid lost data due to stashing.'''
  thread = threading.Thread(target=upload_comment_flag_thread, args=(asset_id, comment_id, flag, api_key))
  thread.start()


def send_comment_is_private_to_thread(asset_id='', comment_id='', is_private=False, api_key=None):
  '''Sens rating into thread rating, main purpose is for tasks_queue.
  One function per property to avoid lost data due to stashing.'''
  thread = threading.Thread(target=upload_comment_is_private_thread, args=(asset_id, comment_id, is_private, api_key))
  thread.start()

def send_comment_to_thread(asset_id, comment_id, comment, api_key):
  '''Sens rating into thread rating, main purpose is for tasks_queue.
  One function per property to avoid lost data due to stashing.'''
  thread = threading.Thread(target=upload_comment_thread, args=(asset_id, comment_id, comment, api_key))
  thread.start()

# def send_comment_delete_to_thread(asset_id='', comment_id='', flag='like', api_key=None):
#   '''Sens rating into thread rating, main purpose is for tasks_queue.
#   One function per property to avoid lost data due to stashing.'''
#   # thread = threading.Thread(target=comment_delete_thread, args=(asset_id, comment_id,  api_key))
#   thread = threading.Thread(target=comment_delete_thread, args=(asset_id, comment_id,  api_key))
#   thread.start()

def store_comments_local(asset_id, comments):
  context = bpy.context
  ac = global_vars.DATA.get('asset comments', {})
  ac[asset_id] = comments
  global_vars.DATA['asset comments'] = ac


def get_comments_local(asset_id):
  context = bpy.context
  global_vars.DATA['asset comments'] = global_vars.DATA.get('asset comments', {})
  comments = global_vars.DATA['asset comments'].get(asset_id)
  if comments:
    return comments
  return None


def get_comments_thread(asset_id, api_key):
  thread = threading.Thread(target=get_comments, args=([asset_id, api_key]), daemon=True)
  thread.start()


def get_comments(asset_id, api_key):
  '''
  Retrieve comments  from BlenderKit server. Can be run from a thread
  Parameters
  ----------
  asset_id
  headers

  Returns
  -------
  ratings - dict of type:value ratings
  '''
  headers = utils.get_headers(api_key)

  url = paths.BLENDERKIT_API + '/comments/assets-uuidasset/' + asset_id + '/'
  params = {}
  r = rerequests.get(url, params=params, verify=True, headers=headers)
  if r is None:
    return
  if r.status_code == 200:
    rj = r.json()
    # store comments - send them to task queue
    tasks_queue.add_task((store_comments_local, (asset_id, rj['results'])))

    # if len(rj['results'])==0:
    #     # store empty ratings too, so that server isn't checked repeatedly
    #     tasks_queue.add_task((store_rating_local_empty,(asset_id,)))
    # return ratings

def check_notifications():
 # check for notifications only for users that actually use the add-on
  # TODO move notifications elsewhere?
  
  user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
  all_notifications_count = count_all_notifications()
  get_notifications_thread(user_preferences.api_key, all_count=all_notifications_count)
  if utils.experimental_enabled() and not bpy.app.timers.is_registered(
          refresh_notifications_timer) and not bpy.app.background:
    bpy.app.timers.register(refresh_notifications_timer, persistent=True, first_interval=5)

def refresh_notifications_timer():
  ''' this timer gets notifications.'''
  preferences = bpy.context.preferences.addons['blenderkit'].preferences
  search.fetch_server_data()
  all_notifications_count = count_all_notifications()
  get_notifications_thread(preferences.api_key, all_count=all_notifications_count)
  return 7200

def store_notifications_count_local(all_count):
  '''Store total count of notifications on server in preferences'''
  user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
  user_preferences.notifications_counter = all_count


def store_notifications_local(notifications):
  '''Store notifications in Blender'''
  global_vars.DATA['bkit notifications'] = notifications


def count_all_notifications():
  '''Return count of all notifications on server'''
  user_preferences = bpy.context.preferences.addons['blenderkit'].preferences
  return user_preferences.notifications_counter


def check_notifications_read():
  '''checks if all notifications were already read, and removes them if so'''
  notifications = global_vars.DATA.get('bkit notifications')
  if notifications is None or notifications.get('count') == 0:
    return True
  for n in notifications['results']:
    if n['unread'] == 1:
      return False
  global_vars.DATA['bkit notifications'] = None
  return True


def get_notifications_thread(api_key, all_count=1000):
  if api_key!='':
    thread = threading.Thread(target=get_notifications, args=([api_key, all_count]), daemon=True)
    thread.start()


def get_notifications(api_key, all_count=1000):
  '''
  Retrieve notifications from BlenderKit server. Can be run from a thread.

  Parameters
  ----------
  api_key
  all_count

  Returns
  -------
  '''
  headers = utils.get_headers(api_key)

  params = {}

  url = paths.BLENDERKIT_API + '/notifications/all_count/'
  r = rerequests.get(url, params=params, verify=True, headers=headers)
  if r.status_code == 200:
    rj = r.json()
    # no new notifications?
    if all_count >= rj['allCount']:
      tasks_queue.add_task((store_notifications_count_local, ([rj['allCount']])))

      return
  url = paths.BLENDERKIT_API + '/notifications/unread/'
  r = rerequests.get(url, params=params, verify=True, headers=headers)
  if r is None:
    return
  if r.status_code == 200:
    rj = r.json()
    # store notifications - send them to task queue
    tasks_queue.add_task((store_notifications_local, ([rj])))


def mark_notification_read_thread(api_key, notification_id):
  thread = threading.Thread(target=mark_notification_read, args=([api_key, notification_id]), daemon=True)
  thread.start()


def mark_notification_read(api_key, notification_id):
  '''
  mark notification as read
  '''
  headers = utils.get_headers(api_key)

  url = f'{paths.BLENDERKIT_API}/notifications/mark-as-read/{notification_id}/'
  params = {}
  r = rerequests.get(url, params=params, verify=True, headers=headers)
  if r is None:
    return
  # if r.status_code == 200:
  #     rj = r.json()
  #     # store notifications - send them to task queue
  #     tasks_queue.add_task((mark_notification_read_local, ([notification_id])))
