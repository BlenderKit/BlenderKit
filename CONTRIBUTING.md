# Contributing

## Development

### Codestyle

We use `isort` for imports sorting.
We use `black` for codestyle.
We will use `ruff` for linting.

To install them all run: `pip3 install --user isort, black, ruff`.

Before committing your changes, please run:
```
isort .
black .
ruff .
```

or just run `python3 dev.py format` to run all of them automatically.

Right now `isort` and `black` are required.
Pull requests will fail in CI/CD if they are not formatted properly and isort or black throws an error.

We are migrating towards `ruff` as well, but it is not required yet.
Please run `ruff` on files you have edited and try to fix all the errors.
Slowly we will add the ruff as a required check in CI/CD.

### Building the add-on

Use `dev.py` script to build the add-on.
This script will copy relevant files to `out/blenderkit` directory (ignoring all files which are not needed in the add-on).
From this source the script will then create a zip file at `out/blenderkit.zip`.
This zip then can be used as a release of BlenderKit.

To build run:
```
python dev.py build
```

#### Development build: build and copy to Blender for quick testing

Script `dev.py` provides handy option `--install-at` to copy the `out/blenderkit` directly to Blender so you can quickly test the build just by starting the Blender without any further steps.
Just specify path to addons directory in `--install-at` flag.
Script will then remove old `blenderkit` directory in addons location and replace it with current build.

To build and copy to Blender 3.2.x addons directory run:

```
python dev.py build --install-at /path/to/blender/3.2/scripts/addons
```

### Compiling daemon

Compiled daemon binary is meant as fallback option for situations where the daemon is blocked by antivirus or firewall.
Daemon is compiled by `pyinstaller`.

1. install `pipenv`: `pip install --user pipenv`
2. compile for current platform and architecture: `python dev.py compile`


### Updating dependencies

1. create a virtual environment: `python3 -m venv .venv`
2. activate the environment: `source .venv/bin/activate`
3. change symbols in requirements.txt from `==` to `>=`
4. install the dependencies: `pip3 install -r requirements.txt`
5. save the installed latest versions into requirements.txt: `pip3 freeze > requirements.txt` 
6. copy the versions into: constant `PACKAGES` in `dev.py` 
7. bundle the dependencies: `python3 dev.py bundle`

## Releasing

Before release update the add-on version in `__init__.py` and `daemon/daemon.py`, make sure it is merged in `main` branch.

1. go to Github Actions, choose `Release` workflow
2. insert the version in format `X.Y.Z.YYMMDD` (e.g. `3.8.0.2306220`), this has to be same as in `__init__.py` and `daemon/daemon.py`
3. set Release Stage to `alpha`, `beta`, `rc` or `gold` for final release
4. once finished, the release draft is available in Github Releases

## Testing

BlenderKit add-on uses tests implemented through `unittest` module.
As the add-on and its submodules require `bpy` module and interaction with Blender, the tests needs to be executed in the Python inside of the Blender.
This makes the tests to be on the edge between unit tests and integration tests.

The tests are defined in files `test_<name-of-tested-file>.py` and their starting point is in file `test.py` which is executed from `dev.py` script.

### Local testing

To test the add-on locally, make sure you have a Blender on your PATH.
Then run:

```
python dev.py test --install-at /path/to/blender/3.2/scripts/addons
```

NOTE: please make sure that version in the `--install-at` path must match the version of the Blender version you have on your PATH.
Otherwise the add-on with test files will be copied to Blender version 3.x, but tests will run on different Blender version 3.a with outdated BlenderKit build.

### Automated testing: CI/CD

We run automated tests on: Pull Requests.
The tests and checks which must pass for PR to be accepted are:
- unit/integration tests on several versions of Blender 3.x.,
- `isort` check,
- automated build of the add-on.

Those CI/CD jobs are realized through Github workflows and are defined in `.github/workflows` directory.
For Pull Requests jobs it is in file: `.github/workflows/PR.yml`.
