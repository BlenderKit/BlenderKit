@echo off
setlocal EnableDelayedExpansion

set THIS_FOLDER=%~dp0
set REPO_FOLDER=%~dp0..

:: print for debug
echo "Script directory: %~dp0"
echo "Repository directory: %REPO_FOLDER%"

:: check if PDM is accessible in paths
:: if not ERROR and exit out
where pdm >nul 2>nul
if errorlevel 1 (
    :: check if pdm already exists but is not in PATH
    set "PDM_SCRIPTS1=%APPDATA%\Python\Scripts"
    set "PDM_SCRIPTS2=%USERPROFILE%\AppData\Roaming\Python\Scripts"

    if exist "!PDM_SCRIPTS1!\pdm.exe" (
        echo "'pdm' command found but not in PATH. Adding to PATH..."
        set Path=!PDM_SCRIPTS1!;!Path!

        :: check again
        where pdm >nul 2>nul
        if errorlevel 1 (
            echo "'pdm' command still not found in PATH after installation. Please ensure it is accessible in your system PATH."
            exit /b 1
        )

        goto CONTINUE_SETUP
    ) else if exist "!PDM_SCRIPTS2!\pdm.exe" (
        echo "'pdm' command found but not in PATH. Adding to PATH..."
        set Path=!PDM_SCRIPTS2!;!Path!

        where pdm >nul 2>nul
        if errorlevel 1 (
            echo "'pdm' command still not found in PATH after installation. Please ensure it is accessible in your system PATH."
            exit /b 1
        )

        goto CONTINUE_SETUP
    )

    :: try to install PDM and set paths automatically
    echo "'pdm' command not found in PATH. Attempting to install 'pdm'..."

    :: must run powershell with official PDM installer
    rem Invoke PowerShell to install pdm using official installer
    powershell.exe -ExecutionPolicy ByPass -c "irm https://pdm-project.org/install-pdm.py | python -"

    if errorlevel 1 (
        echo "Failed to install 'pdm'. Please install it manually (https://pdm-project.org/en/latest/)."
        exit /b 1
    )
    :: set paths - add any known install locations for immediate availability
    if exist "!PDM_SCRIPTS1!\pdm.exe" set Path=!PDM_SCRIPTS1!;!Path!
    if exist "!PDM_SCRIPTS2!\pdm.exe" set Path=!PDM_SCRIPTS2!;!Path!

    :: check again
    where pdm >nul 2>nul
    if errorlevel 1 (
        echo "'pdm' command still not found in PATH after installation."
        echo PATH: !Path!
        echo "Checked locations:"
        echo "  !PDM_SCRIPTS1!"
        echo "  !PDM_SCRIPTS2!"
        exit /b 1
    )
)

:: continue with setup
:CONTINUE_SETUP

:: update pdm itself
pdm self update

cd /d %REPO_FOLDER%

echo ----------------------------------------
echo "Processing project: blenderkit_addon"
echo ----------------------------------------

set "PROJECT_NAME=blenderkit_addon"
set "PROJECT_DIR=%REPO_FOLDER%"
:: make PROJECT_DIR absolute
for %%A in ("!PROJECT_DIR!") do set "PROJECT_DIR=%%~fA"

set "REQUIREMENTS_FILE=!PROJECT_DIR!\pyproject.toml"

:: Print paths for debugging
echo Project directory: !PROJECT_DIR!

:: cd to project_dir
cd /d "!PROJECT_DIR!"

:: Ensure virtual environment exists and is properly configured
echo "Ensuring virtual environment exists..."
pdm info --env

if errorlevel 1 (
    echo "Creating new virtual environment..."
    pdm venv create --with-pip
)

:: Check Python version to determine approach
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo "Detected Python version: !PYTHON_VERSION!"

:: Sync environment (install dependencies including dev group)
if exist "!REQUIREMENTS_FILE!" (
    echo "Syncing environment with dependencies..."

    :: First, try to update the lockfile to include dev dependencies
    echo "Updating lockfile to include dev dependencies..."
    pdm install

    if errorlevel 1 (
        echo "Warning: Failed to update lockfile with all groups. Using fallback approach..."
    )
) else (
    echo "No pyproject.toml found in !PROJECT_NAME!, skipping dependency sync."
)

echo "Virtual environment setup for !PROJECT_NAME! completed successfully!"

echo ----------------------------------------
echo "Virtual environment set up successfully!"
echo ----------------------------------------
echo "Virtual environment info:"
pdm info --env
echo ----------------------------------------
endlocal
pause
