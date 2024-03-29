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

import os
import time
import unittest
from urllib.parse import urlparse

import bpy
import requests

from blenderkit import daemon_lib, download, global_vars, paths, utils


def client_is_responding() -> tuple[bool, str]:
    """Check whether blenderkit-client is responding."""
    address = daemon_lib.get_address()
    try:
        with requests.Session() as session:
            with session.get(
                address, timeout=daemon_lib.TIMEOUT, proxies=daemon_lib.NO_PROXIES
            ) as resp:
                if resp.status_code != 200:
                    return False, f"Server response not 200: {resp.status_code}"
                return True, f"Server alive, PID: {resp.text}"
    except requests.exceptions.ConnectionError as err:
        return False, f'EXCEPTION OCCURED:", {err}, {type(err)}'


### DAEMON IS NOT RUNNING ###


class Test01ClientNotRunning(unittest.TestCase):
    def test01_client_not_running(self):
        """Tests run in background (bpy.app.background == True), so blednerkit-client is not started during registration.
        Also the daemon_communication_timer() and all other timers are not registered.
        So we expect blenderkit-client to be not running.
        """
        alive, pid = client_is_responding()
        self.assertFalse(alive)
        self.assertIsInstance(alive, bool)
        self.assertIsInstance(pid, str)

    def test02_get_reports_not_running(self):
        app_id = os.getpid()
        try:
            daemon_lib.get_reports(app_id)
            self.fail("got report but blenderkit-client should be offline")
        except requests.exceptions.ConnectionError as err:
            type(err)
            return
        except Exception as err:
            self.fail(f"expected requests.exceptions.ConnectionError, got {err}")


### CLIENT IS RUNNING ###


class Test02ClientRunning(unittest.TestCase):
    def test01_start_daemon_server(self):
        daemon_lib.start_blenderkit_client()
        for i in range(10):
            time.sleep(i * 0.5)
            alive, _ = client_is_responding()
            if alive == True:
                break
        self.assertTrue(alive)


class Test03ClientUtilFunctions(unittest.TestCase):
    def test_get_port(self):
        ports = ["62485", "65425", "55428", "49452", "35452", "25152", "5152", "1234"]
        self.assertIn(daemon_lib.get_port(), ports)

    def test_get_address(self):
        address = daemon_lib.get_address()
        parsed = urlparse(address)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, int(daemon_lib.get_port()))

    def test_daemon_directory_path(self):
        dir_path = daemon_lib.get_client_directory()
        self.assertTrue(os.path.exists(dir_path))


class Test04GetReportsClientRunning(unittest.TestCase):
    def test_get_reports_running(self):
        """Get reports for current Blender PID (app_id)."""
        app_id = os.getpid()
        reports = daemon_lib.get_reports(app_id)
        self.assertEqual(1, len(reports))
        self.assertEqual(reports[0]["app_id"], app_id)
        self.assertEqual(reports[0]["task_type"], "client_status")

    def test_get_reports_another_app_id(self):
        """Get reports for non-existing Blender PID (app_id)."""
        app_id = os.getpid() + 10
        reports = daemon_lib.get_reports(app_id)
        self.assertEqual(1, len(reports))
        self.assertEqual(reports[0]["app_id"], app_id)
        self.assertEqual(reports[0]["task_type"], "client_status")


class Test05SearchAndDownloadAsset(unittest.TestCase):
    assets_to_download = []

    def _asset_search(self, search_word, asset_type):
        addon_version = f"{global_vars.VERSION[0]}.{global_vars.VERSION[1]}.{global_vars.VERSION[2]}.{global_vars.VERSION[3]}"
        blender_version = (
            f"{bpy.app.version[0]}.{bpy.app.version[1]}.{bpy.app.version[2]}"
        )
        urlquery = f"https://www.blenderkit.com/api/v1/search/?query={search_word}+asset_type:{asset_type}+order:_score&dict_parameters=1&page_size=15&addon_version={addon_version}&blender_version={blender_version}"
        tempdir = paths.get_temp_dir(f"{asset_type}_search")
        data = {
            "PREFS": utils.get_preferences_as_dict(),
            "tempdir": tempdir,
            "urlquery": urlquery,
            "asset_type": asset_type,
            "blender_version": blender_version,
        }
        response = daemon_lib.asset_search(data)
        search_task_id = response["task_id"]

        to_download = None
        for i in range(10):
            reports = daemon_lib.get_reports(os.getpid())
            for task in reports:
                if search_task_id != task["task_id"]:
                    continue
                if task["status"] == "error":
                    self.fail(f'Search task failed {task["message"]}')
                if task["status"] != "finished":
                    continue
                if task["result"] != {}:
                    for result in task["result"]["results"]:
                        if result["canDownload"] == True:
                            if to_download == None:
                                to_download = result
                                continue
                            result_size = result.get("filesSize", 9999999)
                            if result_size == None:
                                result_size = 9999999
                            to_download_size = to_download.get("filesSize", 9999999)
                            if to_download_size == None:
                                to_download_size = 9999999
                            if result_size < to_download_size:
                                to_download = result
                    return to_download

            time.sleep(i * 0.1)
        self.fail("Error waiting for search task to be reported as finished")

    def _asset_download(self, asset_data):
        if asset_data == None:
            self.fail("Asset data from search are None")

        download.start_download(
            asset_data,
            resolution=512,
            model_location=(0.0, 0.0, 0.0),
            model_rotation=(0.0, 0.0, 0.0),
        )

        for _ in range(100):
            reports = daemon_lib.get_reports(os.getpid())
            for task in reports:
                if task["task_type"] != "asset_download":
                    continue
                if task["status"] != "finished":
                    continue
                return
            time.sleep(1)

    # small assets are chosen here
    def test00Search(self):
        self.assets_to_download.append(self._asset_search("Toy train-02", "model"))

    def test01Search(self):
        self.assets_to_download.append(self._asset_search("Wooden toy car", "model"))

    def test02Search(self):
        self.assets_to_download.append(
            self._asset_search("flowers1 wallpaper", "material")
        )

    def test03Search(self):
        self.assets_to_download.append(self._asset_search("hexa wallpaper", "material"))

    def test04Search(self):
        self.assets_to_download.append(
            self._asset_search("Desk for product visualization", "scene")
        )

    def test05Search(self):
        self.assets_to_download.append(
            self._asset_search("Butterfly Mural Room", "scene")
        )

    def test06Search(self):
        self.assets_to_download.append(self._asset_search("Garden Nook", "hdr"))

    def test07Search(self):
        self.assets_to_download.append(self._asset_search("Dark Autumn Forest", "hdr"))

    def test08Search(self):
        self.assets_to_download.append(self._asset_search("bricks", "brush"))

    def test09Search(self):
        self.assets_to_download.append(self._asset_search("Human eye iris", "brush"))

    def test10Download(self):
        self._asset_download(self.assets_to_download[0])

    def test12Download(self):
        self._asset_download(self.assets_to_download[2])

    def test14Download(self):
        self._asset_download(self.assets_to_download[4])

    def test16Download(self):
        self._asset_download(self.assets_to_download[6])

    def test18Download(self):
        self._asset_download(self.assets_to_download[8])


### CLIENT IS NOT RUNNING ###


class Test99ClientStopped(unittest.TestCase):
    def test_shutdown_client(self):
        daemon_lib.shutdown_client()
        for _ in range(5):
            alive, _ = client_is_responding()
            if alive == False:
                break
            time.sleep(1)
        self.assertFalse(alive)
