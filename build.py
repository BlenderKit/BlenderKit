import subprocess
import os
import shutil

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

MACOS = (
  'darwin',
  (
    ('macosx_10_9_x86_64', packages),
  )
)

LINUX = (
  'linux',
  (
    ('manylinux_2_17_x86_64', packages[0:1]),
    ('manylinux1_x86_64', packages[1:]),
  )
)

WINDOWS = (
  'windows',
  (
    ('win_amd64', packages),
  )
)


shutil.rmtree("bundle")


for platform in [MACOS, WINDOWS, LINUX]:
  for platform_target in platform[1]:
    print(platform_target[1])
    for module in platform_target[1]:
      cmd = [
        'pip3',
        'install',
        '--only-binary=:all:',
        f'--platform={platform_target[0]}',
        f'--python-version={PYTHON_VERSION}',
        f'--target=bundle/{platform[0]}',
        '--no-deps',
        module,
      ]
      print(f"=============: {cmd}")
      ok = subprocess.call(cmd)
      print(f'{ok}')

