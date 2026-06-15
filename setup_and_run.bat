@echo off
setlocal EnableExtensions

:: Always run relative to this repository, even when launched by double-click.
cd /d "%~dp0"

set "ENV_NAME=Fastapp"
set "APP_URL=http://localhost:8000/static/index.html"

echo ==========================================
echo EDIS Setup and Run Script
echo ==========================================
echo [INFO] Project: %CD%

:: 1. Locate Conda. Using `conda run` also supports custom environment paths.
set "CONDA_CMD="
where conda.exe >nul 2>nul
if %errorlevel% equ 0 set "CONDA_CMD=conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "CONDA_CMD=%USERPROFILE%\anaconda3\condabin\conda.bat"
if not defined CONDA_CMD if exist "%USERPROFILE%\miniconda3\condabin\conda.bat" set "CONDA_CMD=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not defined CONDA_CMD if exist "C:\ProgramData\anaconda3\condabin\conda.bat" set "CONDA_CMD=C:\ProgramData\anaconda3\condabin\conda.bat"
if not defined CONDA_CMD if exist "C:\ProgramData\miniconda3\condabin\conda.bat" set "CONDA_CMD=C:\ProgramData\miniconda3\condabin\conda.bat"

if not defined CONDA_CMD (
    echo [ERROR] Conda was not found.
    echo Install Miniconda or Anaconda, then reopen this script.
    pause
    exit /b 1
)

:: 2. Create the environment when missing; otherwise synchronize dependencies.
echo [INFO] Checking Conda environment "%ENV_NAME%"...
call "%CONDA_CMD%" run -n "%ENV_NAME%" python --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] Creating environment from environment.yml. This may take a few minutes...
    call "%CONDA_CMD%" env create -f environment.yml
    if errorlevel 1 goto environment_error
) else (
    echo [INFO] Updating environment from environment.yml...
    call "%CONDA_CMD%" env update -n "%ENV_NAME%" -f environment.yml
    if errorlevel 1 goto environment_error
)

:: 2. Resolve target environment python path first
set "ENV_PYTHON="
if exist "D:\anaconda_envs\edis_env\python.exe" set "ENV_PYTHON=D:\anaconda_envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "%USERPROFILE%\anaconda3\envs\edis_env\python.exe" set "ENV_PYTHON=%USERPROFILE%\anaconda3\envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\anaconda3\envs\edis_env\python.exe" set "ENV_PYTHON=C:\ProgramData\anaconda3\envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "%USERPROFILE%\miniconda3\envs\edis_env\python.exe" set "ENV_PYTHON=%USERPROFILE%\miniconda3\envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\miniconda3\envs\edis_env\python.exe" set "ENV_PYTHON=C:\ProgramData\miniconda3\envs\edis_env\python.exe"

:: 3. Find Conda Path (Only needed if environment doesn't exist)
if not defined ENV_PYTHON (
    set "CONDA_EXE="
    if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\anaconda3\Scripts\conda.exe"
    if not defined CONDA_EXE if exist "C:\ProgramData\anaconda3\Scripts\conda.exe" set "CONDA_EXE=C:\ProgramData\anaconda3\Scripts\conda.exe"
    if not defined CONDA_EXE if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\miniconda3\Scripts\conda.exe"
    if not defined CONDA_EXE if exist "C:\ProgramData\miniconda3\Scripts\conda.exe" set "CONDA_EXE=C:\ProgramData\miniconda3\Scripts\conda.exe"
    if not defined CONDA_EXE (
        where conda.exe >nul 2>nul
        if %errorlevel% equ 0 set "CONDA_EXE=conda.exe"
    )
    
    if not defined CONDA_EXE (
        if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "CONDA_EXE=%USERPROFILE%\anaconda3\condabin\conda.bat"
        if not defined CONDA_EXE if exist "C:\ProgramData\anaconda3\condabin\conda.bat" set "CONDA_EXE=C:\ProgramData\anaconda3\condabin\conda.bat"
    )

:: 4. Existing predictions and model files are enough to run the application.
:: The raw Kaggle dataset is required only when these artifacts must be rebuilt.
if exist "data\processed\predictions.csv" if exist "models\xgboost_model.json" goto model_outputs_ready

echo [INFO] Model outputs are missing. The training pipeline must run once.
if not exist "data\raw\DataCoSupplyChainDataset.csv" (
    if exist "data\raw\archive.zip" (
        echo [INFO] Extracting data\raw\archive.zip...
        powershell -NoProfile -Command "Expand-Archive -Path 'data\raw\archive.zip' -DestinationPath 'data\raw' -Force"
        if errorlevel 1 (
            echo [ERROR] Dataset extraction failed.
            pause
            exit /b 1
        )
    )
)

:: 4. Check and create Conda environment
echo [INFO] Checking Conda environment...
if defined ENV_PYTHON goto env_exists

echo [INFO] Environment 'edis_env' not detected. Creating it now (this may take a few minutes)...
"%CONDA_EXE%" env create -f environment.yml
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create environment!
    pause
    exit /b 1
)

:: Re-resolve ENV_PYTHON after creation
if exist "D:\anaconda_envs\edis_env\python.exe" set "ENV_PYTHON=D:\anaconda_envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "%USERPROFILE%\anaconda3\envs\edis_env\python.exe" set "ENV_PYTHON=%USERPROFILE%\anaconda3\envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\anaconda3\envs\edis_env\python.exe" set "ENV_PYTHON=C:\ProgramData\anaconda3\envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "%USERPROFILE%\miniconda3\envs\edis_env\python.exe" set "ENV_PYTHON=%USERPROFILE%\miniconda3\envs\edis_env\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\miniconda3\envs\edis_env\python.exe" set "ENV_PYTHON=C:\ProgramData\miniconda3\envs\edis_env\python.exe"

if not defined ENV_PYTHON (
    echo [ERROR] Failed to locate Python in the created environment!
    pause
    exit /b 1
)

:env_exists
echo [INFO] Conda environment 'edis_env' is ready.

:: 5. Check pipeline outputs and run model training if needed
if not exist "data\processed\predictions.csv" (
    echo [INFO] predictions.csv not found. Running pipeline and training model...
    goto run_training_pipeline
)
if not exist "data\processed\val_ready.csv" (
    echo [INFO] val_ready.csv not found. Rebuilding train/validation/test outputs...
    goto run_training_pipeline
)

:model_outputs_ready
echo [INFO] Model and prediction files are ready.

if /I "%~1"=="tune-threshold" (
    echo [INFO] Running threshold tuning report...
    call "%CONDA_CMD%" run --no-capture-output -n "%ENV_NAME%" python scripts\tune_threshold.py
    if errorlevel 1 (
        echo [ERROR] Threshold tuning failed.
        pause
        exit /b 1
    )
    echo [INFO] Threshold tuning completed.
    pause
    exit /b 0
)

:: 5. Create the local authentication database and launch the app.
echo [INFO] Initializing authentication database...
call "%CONDA_CMD%" run --no-capture-output -n "%ENV_NAME%" python core\auth.py
if errorlevel 1 (
    echo [ERROR] Authentication database initialization failed.
    pause
    exit /b 1
)

echo [INFO] Starting EDIS API server...
echo [INFO] Browser: %APP_URL%
echo [INFO] Press Ctrl+C to stop the server.
start "" "%APP_URL%"

call "%CONDA_CMD%" run --no-capture-output -n "%ENV_NAME%" python -m uvicorn app:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
    echo.
    echo [ERROR] Server failed to start. Port 8000 may already be in use.
    echo Close the old server or run: netstat -ano ^| findstr :8000
    pause
    exit /b 1
)

exit /b 0

:environment_error
echo [ERROR] Failed to create or update the Conda environment.
echo Check your network connection and environment.yml, then try again.
pause
exit /b 1
