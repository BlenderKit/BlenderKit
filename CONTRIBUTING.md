# Contributing

BlenderKit add-on is an open-source project and we welcome contributions from the community.

## Add-on Architecture
BlenderKit add-on is made of two main parts:
- Blender add-on written in Python, which is responsible for the user interface and interaction with Blender
- Client written in Go, which serves as background HTTP server - a bridge between BlenderKit add-on and BlenderKit server

### How it is packaged
BlenderKit add-on is packaged as a zip file (standard way for Blender add-ons), which contains all the necessary files for the add-on to work.
This includes not only the Python files, icons and other files, but also the Client binaries for 3 platforms on 2 architectures (windows x86_64, windows arm64, macos x86_64, macos arm64, linux x86_64, linux arm64).
When add-on is registered, it chooses the correct Client binary for the platform and architecture and copies it to the user's BlenderKit data directory, from this location the Client is later started.

### How it works
Communication between Add-on and Client happens in one way direction: add-on schedules Tasks via request and periodically gets updates about the progress and results of the tasks in reponses to the requests:
`Add-on -> Client -> Server`

1. add-on checks whether the Client is running. If it is not, it starts the Client binary located at `<global-directory>/client/bin/vX.Y.Z/blenderkit-client-<platform>-<architecture>`,
2. add-on periodically asks for results with GET request and Client responds to the request,

3. if needed add-on sends requests (identifying itself with app_id which is PID of running Blender instance) for search, download asset, get notifications, download thumbnails etc. to the Client
4. Client receives the request for work, saves it into `var Tasks map[int]map[string]*Task` and ASAP responds by OK to not block the add-on,
5. Client starts the work in goroutine, or makes request to BlenderKit server, or combination of both,
6. When work is done, or response comes from BlenderKit server, Client updates the results into `var Tasks map[int]map[string]*Task`.
7. next time when add-on periodically asks for results of the Tasks, Client sends the results as response.

Communication between Client and Server currently happens in one way also Client -> Server (Client makes requests to Server).

## Development

### Codestyle

We use `isort` for imports sorting.
We use `black` for codestyle.
We use `go fmt` for formatting Go code in `./client`
We will use `ruff` for linting.

We define versions in `devs/requirements.txt` so the local development environment is consistent with CI/CD (Github Actions).
To install them in correct versions run: `pip3 install -U --user --r devs/requirements.py`.

Before committing your changes, please run:
```
isort .
black .
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

#### Development build: build for quick testing

Script `dev.py` provides handy option `--install-at` to copy the `out/blenderkit` directly to Blender so you can quickly test the build just by starting the Blender without any further steps.
Just specify path to addons directory in `--install-at` flag.
Script will then remove old `blenderkit` directory in addons location and replace it with current build.

To build and copy to Blender 4.0.x addons directory and also clean blenderkit_data, run:

```
python dev.py build --install-at /path/to/blender/4.0/scripts/addons --clean-dir /Users/username/blenderkit_data
```

NOTE: --clean-dir is required if you change anything in the blenderkit-client, otherwise add-on will not copy the new binaries over the old ones.
We recommend using this command to clean all client binaries, while enabling you to continuously tail -f default.log file:

```
python dev.py build --install-at /path/to/blender/4.0/scripts/addons --clean-dir /Users/username/blenderkit_data/client/bin
```

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

### Pull Requests

To contribute to the project, please create a Pull Request.
PR should contain a description of the changes and the reason for the changes.
Ideally PR should be linked to an issue in the issue tracker.

PR will be reviewed by the team and if it passes the automated tests and checks, it will be merged.

#### Automated tests

We run automated tests on: Pull Requests.
The tests and checks which must pass for PR to be accepted are:
- unit/integration tests on several versions of Blender 3.x.,
- `isort` check for validity of import sorting,
- `black` check for codestyle,
- `go fmt` check for formatting Go code in `./client`,
- automated build of the add-on.

Those CI/CD jobs are realized through Github workflows and are defined in `.github/workflows` directory.
For Pull Requests jobs it is in file: `.github/workflows/PR.yml`.
