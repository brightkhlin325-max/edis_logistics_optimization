@echo off
setlocal

echo ==========================================
echo EDIS Setup and Run Script
echo ==========================================

:: 1. Check if raw dataset exists
if not exist "data\raw\DataCoSupplyChainDataset.csv" (
    if exist "data\raw\archive.zip" (
        echo [INFO] archive.zip detected. Extracting...
        powershell -Command "Expand-Archive -Path 'data\raw\archive.zip' -DestinationPath 'data\raw' -Force"
    ) else (
        echo [ERROR] Dataset DataCoSupplyChainDataset.csv not found in data\raw\
        echo Please download it from Kaggle first.
        echo.
        pause
        exit /b 1
    )
)

:: 2. Resolve target environment python path first
set "ENV_PYTHON="
if exist "%USERPROFILE%\anaconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=%USERPROFILE%\anaconda3\envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "D:\anaconda_envs\Fastapp\python.exe" set "ENV_PYTHON=D:\anaconda_envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\anaconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=C:\ProgramData\anaconda3\envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "%USERPROFILE%\miniconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=%USERPROFILE%\miniconda3\envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\miniconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=C:\ProgramData\miniconda3\envs\Fastapp\python.exe"

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

    if not defined CONDA_EXE (
        echo [ERROR] Conda not found! Please install Anaconda or Miniconda to build the environment.
        pause
        exit /b 1
    )
)

:: 4. Check and create Conda environment
echo [INFO] Checking Conda environment...
if defined ENV_PYTHON goto env_exists

echo [INFO] Environment 'Fastapp' not detected. Creating it now (this may take a few minutes)...
"%CONDA_EXE%" env create -f environment.yml
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create environment!
    pause
    exit /b 1
)

:: Re-resolve ENV_PYTHON after creation
if exist "%USERPROFILE%\anaconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=%USERPROFILE%\anaconda3\envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "D:\anaconda_envs\Fastapp\python.exe" set "ENV_PYTHON=D:\anaconda_envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\anaconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=C:\ProgramData\anaconda3\envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "%USERPROFILE%\miniconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=%USERPROFILE%\miniconda3\envs\Fastapp\python.exe"
if not defined ENV_PYTHON if exist "C:\ProgramData\miniconda3\envs\Fastapp\python.exe" set "ENV_PYTHON=C:\ProgramData\miniconda3\envs\Fastapp\python.exe"

if not defined ENV_PYTHON (
    echo [ERROR] Failed to locate Python in the created environment!
    pause
    exit /b 1
)

:env_exists
echo [INFO] Conda environment 'Fastapp' is ready.

:: 5. Check pipeline outputs and run model training if needed
if not exist "data\processed\predictions.csv" (
    echo [INFO] predictions.csv not found. Running pipeline and training model...
    set PYTHONIOENCODING=utf-8
    
    "%ENV_PYTHON%" core/data_pipeline.py
    if %errorlevel% neq 0 (
        echo [ERROR] Data pipeline failed!
        pause
        exit /b 1
    )
    "%ENV_PYTHON%" core/model_pipeline.py
    if %errorlevel% neq 0 (
        echo [ERROR] Model training failed!
        pause
        exit /b 1
    )
) else (
    echo [INFO] predictions.csv exists. Skipping training.
)

if /I "%~1"=="tune-threshold" (
    echo [INFO] Running threshold tuning report...
    "%ENV_PYTHON%" scripts/tune_threshold.py
    if %errorlevel% neq 0 (
        echo [ERROR] Threshold tuning failed!
        pause
        exit /b 1
    )
    echo [INFO] Threshold tuning completed.
    echo [INFO] Outputs:
    echo   data\processed\threshold_tuning.csv
    echo   data\processed\threshold_tuning_summary.json
    pause
    exit /b 0
)

:: 6. Install additional packages
echo [INFO] Installing required packages...
"%ENV_PYTHON%" -m pip install passlib bcrypt python-multipart --quiet
if %errorlevel% neq 0 (
    echo [WARNING] Some packages may have failed to install, continuing...
)

:: 7. Initialize auth database
echo [INFO] Initializing authentication database...
"%ENV_PYTHON%" core/auth.py
if %errorlevel% neq 0 (
    echo [WARNING] Auth database initialization failed, continuing...
)

:: 8. Run Web Server
echo [INFO] Starting API Server...
echo Open http://localhost:8000/static/index.html in your browser (opening automatically)...
echo Press Ctrl + C to stop the server.
echo.

:: Automatically open the browser
start http://localhost:8000/static/index.html

"%ENV_PYTHON%" app.py

pause
