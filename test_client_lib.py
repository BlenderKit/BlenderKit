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


# Dynamically set the package context for the BlenderKit add-on
for addon in bpy.context.preferences.addons:
    if "blenderkit" in addon.module:
        __package__ = addon.module
        break

# Handle imports for both package and standalone execution
try:
    from . import client_lib, datas, download, paths, utils
except ImportError:
    # Fallback for when running as standalone script
    import sys
    import os

    sys.path.insert(0, os.path.dirname(__file__))
    import client_lib, datas, download, paths, utils


def client_is_responding() -> tuple[bool, str]:
    """Check whether blenderkit-client is responding."""
    address = client_lib.get_address()
    try:
        with requests.Session() as session:
            with session.get(
                address, timeout=client_lib.TIMEOUT, proxies=client_lib.NO_PROXIES
            ) as resp:
                if resp.status_code != 200:
                    return False, f"Server response not 200: {resp.status_code}"
                return True, f"Server alive, PID: {resp.text}"
    except requests.exceptions.ConnectionError as err:
        return False, f'EXCEPTION OCCURED:", {err}, {type(err)}'


### CLIENT IS NOT RUNNING ###


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test01ClientNotRunning(unittest.TestCase):
    def test01_client_not_running(self):
        """Tests run in background (bpy.app.background == True), so blednerkit-client is not started during registration.
        Also the client_communication_timer() and all other timers are not registered.
        So we expect blenderkit-client to be not running.
        """
        alive, pid = client_is_responding()
        self.assertFalse(alive)
        self.assertIsInstance(alive, bool)
        self.assertIsInstance(pid, str)

    def test02_get_reports_not_running(self):
        app_id = os.getpid()
        try:
            client_lib.get_reports(app_id)
            self.fail("got report but blenderkit-client should be offline")
        except requests.exceptions.ConnectionError as err:
            type(err)
            return
        except Exception as err:
            self.fail(f"expected requests.exceptions.ConnectionError, got {err}")


### CLIENT IS RUNNING ###


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test02ClientRunning(unittest.TestCase):
    def test01_start_client_server(self):
        client_lib.start_blenderkit_client()
        for i in range(10):
            time.sleep(i * 0.5)
            alive, _ = client_is_responding()
            if alive == True:
                break
        self.assertTrue(alive)


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test03ClientUtilFunctions(unittest.TestCase):
    def test_get_port(self):
        ports = ["62485", "65425", "55428", "49452", "35452", "25152", "5152", "1234"]
        self.assertIn(client_lib.get_port(), ports)

    def test_get_address(self):
        address = client_lib.get_address()
        parsed = urlparse(address)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, int(client_lib.get_port()))

    def test_client_directory_path(self):
        dir_path = client_lib.get_client_directory()
        self.assertTrue(os.path.exists(dir_path))


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test04GetReportsClientRunning(unittest.TestCase):
    def test_get_reports_running(self):
        """Get reports for current Blender PID (app_id)."""
        app_id = os.getpid()
        reports = client_lib.get_reports(app_id)
        self.assertEqual(1, len(reports))
        self.assertEqual(reports[0]["app_id"], app_id)
        self.assertEqual(reports[0]["task_type"], "client_status")

    def test_get_reports_another_app_id(self):
        """Get reports for non-existing Blender PID (app_id)."""
        app_id = os.getpid() + 10
        reports = client_lib.get_reports(app_id)
        self.assertEqual(1, len(reports))
        self.assertEqual(reports[0]["app_id"], app_id)
        self.assertEqual(reports[0]["task_type"], "client_status")


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test05SearchAndDownloadAsset(unittest.TestCase):
    assets_to_download = []

    def _asset_search(self, search_word, asset_type):
        addon_version = utils.get_addon_version()
        blender_version = utils.get_blender_version()
        urlquery = f"https://www.blenderkit.com/api/v1/search/?query={search_word}+asset_type:{asset_type}+order:_score&dict_parameters=1&page_size=15&addon_version={addon_version}&blender_version={blender_version}"
        tempdir = paths.get_temp_dir(f"{asset_type}_search")
        data = datas.SearchData(
            PREFS=utils.get_preferences(),
            tempdir=tempdir,
            urlquery=urlquery,
            asset_type=asset_type,
            blender_version=blender_version,
            page_size=15,
            get_next=False,
            scene_uuid="",
        )
        try:
            response = client_lib.asset_search(data)
            search_task_id = response["task_id"]

            to_download = None
            for i in range(10):
                reports = client_lib.get_reports(os.getpid())
                for task in reports:
                    if search_task_id != task["task_id"]:
                        continue
                    if task["status"] == "error":
                        error_msg = task.get("message", "Unknown error")
                        self.fail(f"Search task failed: {error_msg}, query: {urlquery}")
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
            self.fail(
                f"Error waiting for search task to be reported as finished, query: {urlquery}"
            )
        except Exception as e:
            self.fail(f"Search request failed: {str(e)}, query: {urlquery}")

    def _asset_download(self, asset_data):
        if asset_data == None:
            self.fail("Asset data from search are None")

        download.start_download(
            asset_data,
            resolution="resolution_0_5K",
            model_location=(0.0, 0.0, 0.0),
            model_rotation=(0.0, 0.0, 0.0),
        )

        for _ in range(100):
            reports = client_lib.get_reports(os.getpid())
            for task in reports:
                if task["task_type"] != "asset_download":
                    continue
                if task["status"] != "finished":
                    continue
                return
            time.sleep(1)

    # small assets are chosen here
    def test00Search(self):
        self.assets_to_download.append(self._asset_search("Toy+train-02", "model"))

    def test01Search(self):
        self.assets_to_download.append(self._asset_search("Wooden+toy+car", "model"))

    def test02Search(self):
        self.assets_to_download.append(
            self._asset_search("flowers1+wallpaper", "material")
        )

    def test03Search(self):
        self.assets_to_download.append(self._asset_search("hexa+wallpaper", "material"))

    def test04Search(self):
        self.assets_to_download.append(
            self._asset_search("Desk+for+product+visualization", "scene")
        )

    def test05Search(self):
        self.assets_to_download.append(
            self._asset_search("Butterfly+Mural+Room", "scene")
        )

    def test06Search(self):
        self.assets_to_download.append(self._asset_search("Garden+Nook", "hdr"))

    def test07Search(self):
        self.assets_to_download.append(self._asset_search("Dark+Autumn+Forest", "hdr"))

    def test08Search(self):
        self.assets_to_download.append(self._asset_search("bricks", "brush"))

    def test09Search(self):
        self.assets_to_download.append(self._asset_search("Human+eye+iris", "brush"))

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


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test99ClientStopped(unittest.TestCase):
    def test_shutdown_client(self):
        client_lib.shutdown_client()
        for _ in range(5):
            alive, _ = client_is_responding()
            if alive == False:
                break
            time.sleep(1)
        self.assertFalse(alive)
