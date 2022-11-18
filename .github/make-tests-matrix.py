import re
from urllib import request


jobs = [
  {'version': '3.0.0', 'version_x_y': '3.0', 'download_url': 'https://download.blender.org/release/Blender3.0/blender-3.0.0-linux-x64.tar.xz'},
  {'version': '3.0.1', 'version_x_y': '3.0', 'download_url': 'https://download.blender.org/release/Blender3.0/blender-3.0.1-linux-x64.tar.xz'},
  {'version': '3.1.0', 'version_x_y': '3.1', 'download_url': 'https://download.blender.org/release/Blender3.1/blender-3.1.0-linux-x64.tar.xz'},
  {'version': '3.1.2', 'version_x_y': '3.1', 'download_url': 'https://download.blender.org/release/Blender3.1/blender-3.1.2-linux-x64.tar.xz'},
  {'version': '3.2.0', 'version_x_y': '3.2', 'download_url': 'https://download.blender.org/release/Blender3.2/blender-3.2.0-linux-x64.tar.xz'},
  {'version': '3.2.2', 'version_x_y': '3.2', 'download_url': 'https://download.blender.org/release/Blender3.2/blender-3.2.2-linux-x64.tar.xz'},
  {'version': '3.3.0', 'version_x_y': '3.3', 'download_url': 'https://download.blender.org/release/Blender3.3/blender-3.3.0-linux-x64.tar.xz'},
  {'version': '3.3.1-LTS', 'version_x_y': '3.3', 'download_url': 'https://download.blender.org/release/Blender3.3/blender-3.3.1-linux-x64.tar.xz'},
  #{'version': '', 'version_x_y': '', 'download_url': ''},
]


def get_daily_builds(jobs: list):
  resp = request.urlopen('https://builder.blender.org/download/daily/')
  page = resp.read().decode('utf-8')
  releases = re.findall(r'(https://builder.blender.org/download/daily/blender-((3\.\d)\.\d-\w+)\+\S{1,6}\.\S{12}-linux\.x86_64-release\.tar\.xz)', page)
  for release in releases:
    job = {
      'version': release[1],
      'version_x_y': release[2],
      'download_url': release[0],
    }
    if job not in jobs:
      jobs.append(job)


get_daily_builds(jobs)
matrix = {"include": jobs}
print(f'matrix={matrix}')
