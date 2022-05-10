import argparse
import os
import shutil
import subprocess
import sys


PYTHON_VERSION = "3.10"
PACKAGES = [
  "multidict==6.0.2",
  "aiohttp==3.8.1",
  "aiosignal==1.2.0",
  "async-timeout==4.0.2",
  "attrs==21.4.0",
  "certifi==2021.10.08",
  "charset-normalizer==2.0.10",
  "frozenlist==1.3.0",
  "idna==3.3",
  "yarl==1.7.2",
]


def do_build(install_at=None):
  """Build addon by copying relevant addon directories and files to ./out/blenderkit directory. Create zip in ./out/blenderkit.zip."""

  shutil.rmtree('out', True)

  target_dir = "out/blenderkit"
  ignore_files = [
    '.gitignore',
    'build.py',
    'README.md',
    'requirements.txt',
    'setup.cfg'
  ]

  shutil.copytree('bl_ui_widgets', f'{target_dir}/bl_ui_widgets', ignore=shutil.ignore_patterns('__pycache__'))
  shutil.copytree('blendfiles', f'{target_dir}/blendfiles')
  shutil.copytree('daemon', f'{target_dir}/daemon', ignore=shutil.ignore_patterns('__pycache__'))
  shutil.copytree('data', f'{target_dir}/data')
  shutil.copytree('dependencies', f'{target_dir}/dependencies')
  shutil.copytree('thumbnails', f'{target_dir}/thumbnails')

  for item in os.listdir():
    if os.path.isdir(item):
      continue # we copied directories above
    if item in ignore_files:
      continue
    shutil.copy(item, f'{target_dir}/{item}')

  #CREATE ZIP
  shutil.make_archive('out/blenderkit', 'zip', 'out', 'blenderkit')

  if install_at != None:
    shutil.rmtree(f'{install_at}/blenderkit', ignore_errors=True)
    shutil.copytree('out/blenderkit', f'{install_at}/blenderkit')


def bundle_dependencies():
  """Bundle dependencies specified in PACKAGES variable into ./dependencies directory."""

  MACOS = {
    'name': 'Darwin',
    'platforms': {
      #'macosx_10_9_x86_64': packages,
      'macosx_10_9_universal2': PACKAGES,
    }
  }

  LINUX = {
    'name': 'Linux',
    'platforms' : {
      'manylinux_2_17_x86_64': PACKAGES[0:1],
      'manylinux1_x86_64': PACKAGES[1:],
    }
  }

  WINDOWS = {
    'name': 'Windows',
    'platforms': {
      'win_amd64': PACKAGES,
    }
  }

  shutil.rmtree("dependencies", True)
  print("***** VENDORING DEPENDENCIES *****")
  for OS in [MACOS, WINDOWS, LINUX]:
    print(f'\n===== {OS["name"]} =====')
    for platform in OS['platforms']:
      for module in OS['platforms'][platform]:
        cmd = [
          'pip',
          'install',
          '--only-binary=:all:',
          f'--platform={platform}',
          f'--python-version={PYTHON_VERSION}',
          f'--target=dependencies/{OS["name"]}',
          '--no-deps',
          module,
        ]
        exit_code = subprocess.call(cmd)
        if exit_code != 0:
          sys.exit(1)


### COMMAND LINE INTERFACE

parser = argparse.ArgumentParser()
parser.add_argument("command", default='build', choices=['build', 'bundle'], help="""BUILD = copy relevant files into ./out/blenderkit. BUNDLE = bundle dependencies into ./dependencies""")
parser.add_argument('--install-at', type=str, default=None, help='If path is specified, then builded addon will be copied to that location.')
args = parser.parse_args()

if args.command == "build":
  do_build(args.install_at)
elif args.command == "bundle":
  bundle_dependencies()
else:
  parser.print_help()
