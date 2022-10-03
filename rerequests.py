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

import bpy
import requests

from . import global_vars, reports, tasks_queue, utils


bk_logger = logging.getLogger(__name__)


class FakeResponse():
    def __init__(self, text='', status_code = 400):
        self.text = text
        self.status_code = status_code
    def json(self):
        return {}

def rerequest(method, url, recursion=0, **kwargs):
    # first get any additional args from kwargs
    immediate = False
    if kwargs.get('immediate'):
        immediate = kwargs['immediate']
        kwargs.pop('immediate')
    # first normal attempt
    try:
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
        response = session.request(method, url, **kwargs)
    except Exception as e:
        print(e)
        tasks_queue.add_task((reports.add_report, (
            'Connection error.', 10)))
        return FakeResponse()

    bk_logger.debug(url + str(kwargs))
    bk_logger.debug(response.status_code)

    if response.status_code == 401:
        try:
            rdata = response.json()
        except:
            rdata = {}

        tasks_queue.add_task((reports.add_report, (method + ' request Failed.' + str(rdata.get('detail')),)))

    return response


def get(url, **kwargs):
    response = rerequest('get', url, **kwargs)
    return response


def post(url, **kwargs):
    response = rerequest('post', url, **kwargs)
    return response


def put(url, **kwargs):
    response = rerequest('put', url, **kwargs)
    return response


def patch(url, **kwargs):
    response = rerequest('patch', url, **kwargs)
    return response
