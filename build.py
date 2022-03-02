import subprocess
import shutil
import sys

PYTHON_VERSION = 3.9

packages = [
  "multidict==6.0.2",
  "aiohttp==3.8.1",
  "aiosignal==1.2.0",
  "async-timeout==4.0.2",
  "attrs==21.4.0",
  "charset-normalizer==2.0.10",
  "frozenlist==1.3.0",
  "idna==3.3",
  "yarl==1.7.2",
]

MACOS = {
  'name': 'Darwin',
  'platforms': {
    #'macosx_10_9_x86_64': packages,
    'macosx_10_9_universal2': packages,
  }
}

LINUX = {
  'name': 'Linux',
  'platforms' : {
    'manylinux_2_17_x86_64': packages[0:1],
    'manylinux1_x86_64': packages[1:],
  }
}

WINDOWS = {
  'name': 'Windows',
  'platforms': {
    'win_amd64': packages,
  }
}

shutil.rmtree("vendor", True)

print("***** VENDORING DEPENDENCIES *****")
for OS in [MACOS, WINDOWS, LINUX]:
  print(f'\n===== {OS["name"]} =====')
  for platform in OS['platforms']:
    for module in OS['platforms'][platform]:
      cmd = [
        'pip3',
        'install',
        '--only-binary=:all:',
        f'--platform={platform}',
        f'--python-version={PYTHON_VERSION}',
        f'--target=vendor/{OS["name"]}',
        '--no-deps',
        module,
      ]
      exit_code = subprocess.call(cmd)
      if exit_code != 0:
        sys.exit(1)
