"""Requires proxy server running on 8899 port."""

from urllib.parse import urlparse

from blenderkit import daemon_lib, global_vars

from test_daemon_lib import SearchAndDownloadAssetTestCase, DaemonRunningTestCase, DaemonStoppedTestCase


class Test01DaemonRunningBehindHTTPOpenProxy(DaemonRunningTestCase):
    def test01_start_daemon_server(self):
        global_vars.PREFS['proxy_which'] = 'CUSTOM'
        global_vars.PREFS['proxy_address'] = 'http://127.0.0.1:8899'
        self._start_daemon_server()
        

class Test02SearchAndDownloadAsset(SearchAndDownloadAssetTestCase):
    assets_to_download = []
    def test00Search(self):
        self.assets_to_download.append(self._search_asset('Toy train-02', 'model'))
    def test10Download(self):
        self._download_asset(self.assets_to_download[0])

class Test99DaemonStopped(DaemonStoppedTestCase):
    def test_kill_daemon_server(self):
        print("KILLING")
        self._kill_daemon_server()
