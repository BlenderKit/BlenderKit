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


import base64
import hashlib
import logging
import random
import string
import time
import webbrowser
from urllib.parse import quote as urlquote

import bpy
from bpy.props import BoolProperty

from . import daemon_lib, global_vars, reports, search, tasks_queue, utils
from .daemon import tasks


CLIENT_ID = "IdFRwa3SGA8eMpzhRVFMg5Ts8sPK93xBjif93x0F"
active_authenticator = None
bk_logger = logging.getLogger(__name__)


def handle_login_task(task: tasks.Task):
    """Handles incoming task of type Login. Writes tokens if it finished successfully, logouts the user on error."""

    if task.status == "finished":
        access_token = task.result["access_token"]
        refresh_token = task.result["refresh_token"]
        oauth_response = task.result
        tasks_queue.add_task((write_tokens, (access_token, refresh_token, oauth_response)))
    elif task.status == "error":
        logout()
        reports.add_report(task.message, 5, 'ERROR')


def logout():
    """Logs out user from add-on."""

    preferences = bpy.context.preferences.addons['blenderkit'].preferences
    preferences.login_attempt = False
    preferences.api_key_refresh = ''
    preferences.api_key = ''
    preferences.api_key_timeout = 0
    if global_vars.DATA.get('bkit profile'):
        del (global_vars.DATA['bkit profile'])


def login(signup):
  """Logs user into the addon.
  Opens a browser with login page. Once user is logged it redirects to daemon handling access code via URL querry parameter.
  Using the access_code daemon then requests api_token and handles the results as a task with status finished/error.
  This is handled by function handle_login_task which saves tokens, or shows error message.
  """
  local_landing_URL = f"http://localhost:{daemon_lib.get_port()}/consumer/exchange/"
  code_verifier, code_challenge = generate_pkce_pair()
  daemon_lib.send_code_verifier(code_verifier)
  authorize_url = f"/o/authorize?client_id={CLIENT_ID}&response_type=code&state=random_state_string&redirect_uri={local_landing_URL}&code_challenge={code_challenge}&code_challenge_method=S256"
  if signup:
    authorize_url = urlquote(authorize_url)
    authorize_url = f"{global_vars.SERVER}/accounts/register/?next={authorize_url}"
  else:
    authorize_url = f"{global_vars.SERVER}{authorize_url}"
  webbrowser.open_new_tab(authorize_url)

  return


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE pair - a code verifier and code challange.
    The challange should be sent first to the server, the verifier is used in next steps to verify identity (handles daemon)."""
    rand = random.SystemRandom()
    code_verifier = ''.join(rand.choices(string.ascii_letters + string.digits, k=128))

    code_sha_256 = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    b64 = base64.urlsafe_b64encode(code_sha_256)
    code_challenge = b64.decode('utf-8').replace('=', '')
    return code_verifier, code_challenge


def write_tokens(auth_token, refresh_token, oauth_response):
    preferences = bpy.context.preferences.addons['blenderkit'].preferences
    preferences.api_key_timeout = int(time.time() + oauth_response['expires_in'])
    preferences.login_attempt = False
    preferences.api_key_refresh = refresh_token
    preferences.api_key = auth_token

    props = utils.get_search_props()
    if props is not None:
        props.report = ''
    daemon_lib.get_user_profile(preferences.api_key)
    # ui_props = bpy.context.window_manager.blenderkitUI
    # if ui_props.assetbar_on:
    #     ui_props.turn_off = True
    #     ui_props.assetbar_on = False
    search.cleanup_search_results() #TODO: is it possible to start this from daemon automatically? probably YEA
    history = global_vars.DATA['search history']
    if len(history)>0:
        search.search(query = history[-1])


def refresh_token_timer():
  """Checks if API token needs refresh and makes it if needed."""
  next_time = 1800
  preferences = bpy.context.preferences.addons['blenderkit'].preferences
  if preferences.api_key == "": # Not logged in
    return next_time

  if preferences.api_key_refresh == "": # Using manually inserted permanent token
    return next_time
  
  if time.time() + 7200 < preferences.api_key_timeout: # Token is not old
    return next_time
  
  # Token is at the end of life, refresh token exists, it is time to refresh
  daemon_lib.refresh_token(preferences.api_key_refresh)
  return next_time


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
        default="You were logged out from BlenderKit.\n Clicking OK takes you to web login. ")

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
        logout()
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
        preferences = bpy.context.preferences.addons['blenderkit'].preferences
        preferences.login_attempt = False
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
