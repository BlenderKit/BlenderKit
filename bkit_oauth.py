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
import time
import webbrowser
from urllib.parse import quote as urlquote

import bpy
import requests

from . import global_vars
from . import paths
from . import reports
from . import search
from . import utils
from . import daemon_lib


bk_logger = logging.getLogger('blenderkit')

from bpy.props import BoolProperty


CLIENT_ID = "IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F"

active_authenticator = None


def login(signup):
  bkit_URL = paths.get_bkit_url()
  daemon_port = bpy.context.preferences.addons['blenderkit'].preferences.daemon_port
  local_landing_URL = f"http://localhost:{daemon_port}/consumer/exchange/"
  authorize_url = f"/o/authorize?client_id={CLIENT_ID}&state=random_state_string&response_type=code&redirect_uri={local_landing_URL}"
  if signup:
    authorize_url = urlquote(authorize_url)
    authorize_url = f"{bkit_URL}/accounts/register/?next={authorize_url}"
  else:
    authorize_url = f"{bkit_URL}{authorize_url}"
  webbrowser.open_new(authorize_url)

  return

def write_tokens(auth_token, refresh_token, oauth_response):
    preferences = bpy.context.preferences.addons['blenderkit'].preferences
    oauth_response["expires_in"] = 60 #REMOVE - ONLY FOR TESTING
    preferences.api_key_timeout = int(time.time() + oauth_response['expires_in'])
    preferences.login_attempt = False
    preferences.refresh_in_progress = False
    preferences.api_key_refresh = refresh_token
    preferences.api_key = auth_token

    props = utils.get_search_props()
    if props is not None:
        props.report = ''
    search.get_profile()
    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.assetbar_on:
        ui_props.turn_off = True
        ui_props.assetbar_on = False
    search.cleanup_search_results()
    #categories.fetch_categories_thread(auth_token, force = False)


def ensure_api_key_freshness():
    preferences = bpy.context.preferences.addons['blenderkit'].preferences
    if preferences.api_key == "":
      return
    
    if preferences.api_key_refresh == "":
      #if we have api_key, we can get refresh token here
      return

    if time.time() + 4000 > preferences.api_key_timeout:
      daemon_lib.refresh_token(preferences.api_key_refresh)
      preferences.refresh_in_progress = True

    if len(preferences.api_key_refresh) > 0 and preferences.refresh_in_progress == False:
        

      reports.add_report('Already Refreshing token, will be ready soon. If this fails, please login again in Login panel.')


def refresh_token_timer():
  """Checks if api_key needs refresh and makes refresh if needed."""

  print("REFRESH TOKEN TIME RUNS...")
  utils.p('refresh timer')

  ensure_api_key_freshness()
  #fetch_server_data()
  #categories.load_categories()

  return 30 #INCREASE, ONLY 30 FOR TESTING


class LoginOnline(bpy.types.Operator):
    """Login or register online on BlenderKit webpage"""

    bl_idname = "wm.blenderkit_login"
    bl_label = "BlenderKit login/signup"
    bl_options = {'REGISTER', 'UNDO'}

    signup: BoolProperty(
        name="create a new account",
        description="True for register, otherwise login",
        default=False,
        options={'SKIP_SAVE'}
    )

    message: bpy.props.StringProperty(
        name="Message",
        description="",
        default="You were logged out from .\n Clicking OK takes you to web login. ")

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        utils.label_multiline(layout, text=self.message, width = 300)

    def execute(self, context):
        preferences = bpy.context.preferences.addons['blenderkit'].preferences
        preferences.login_attempt = True
        login(self.signup)

        return {'FINISHED'}

    def invoke(self, context, event):
        wm = bpy.context.window_manager
        preferences = bpy.context.preferences.addons['blenderkit'].preferences
        preferences.api_key_refresh = ''
        preferences.api_key = ''
        return wm.invoke_props_dialog(self)


class Logout(bpy.types.Operator):
    """Logout from BlenderKit immediately"""

    bl_idname = "wm.blenderkit_logout"
    bl_label = "BlenderKit logout"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        preferences = bpy.context.preferences.addons['blenderkit'].preferences
        preferences.login_attempt = False
        preferences.api_key_refresh = ''
        preferences.api_key = ''
        if global_vars.DATA.get('bkit profile'):
            del (global_vars.DATA['bkit profile'])
        return {'FINISHED'}


class CancelLoginOnline(bpy.types.Operator):
    """Cancel login attempt"""

    bl_idname = "wm.blenderkit_login_cancel"
    bl_label = "BlenderKit login cancel"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        global active_authenticator
        preferences = bpy.context.preferences.addons['blenderkit'].preferences
        preferences.login_attempt = False
        try:
            if active_authenticator is not None:
                session = requests.Session()
                proxy_which = global_vars.PREFS.get('proxy_which')
                proxy_address = global_vars.PREFS.get('proxy_address')
                if proxy_which == 'NONE':
                    session.trust_env = False
                elif proxy_which == 'CUSTOM':
                    session.trust_env = False
                    session.proxies = {'https': proxy_address}
                else:
                    session.trust_env = True
                session.get(active_authenticator.redirect_uri)
                active_authenticator = None
        except Exception as e:
            print('stopped login attempt')
            print(e)
        return {'FINISHED'}


classes = (
    LoginOnline,
    CancelLoginOnline,
    Logout,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
