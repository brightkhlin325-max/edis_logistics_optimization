@echo off
setlocal EnableExtensions

:: Run relative to this repository, including when launched by double-click.
cd /d "%~dp0"

set "ENV_NAME=Fastapp"
set "APP_URL=http://localhost:8000/static/index.html"

echo ==========================================
echo EDIS Setup and Run Script
echo ==========================================
echo [INFO] Project: %CD%

:: 1. Locate Conda.
set "CONDA_CMD="
where conda.exe >nul 2>nul
if not errorlevel 1 set "CONDA_CMD=conda.exe"
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

:: 2. Create or synchronize the environment.
echo [INFO] Checking Conda environment "%ENV_NAME%"...
call "%CONDA_CMD%" run -n "%ENV_NAME%" python --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] Creating environment from environment.yml...
    call "%CONDA_CMD%" env create -f environment.yml
    if errorlevel 1 goto environment_error
) else (
    echo [INFO] Updating environment from environment.yml...
    call "%CONDA_CMD%" env update -n "%ENV_NAME%" -f environment.yml --prune
    if errorlevel 1 goto environment_error
)

:: 3. Validate every runtime dependency used by the current application.
echo [INFO] Verifying Python dependencies...
call "%CONDA_CMD%" run -n "%ENV_NAME%" python -c "import bcrypt, fastapi, multipart, numpy, pandas, pulp, sklearn, uvicorn, xgboost; import app; print('[OK] Application imports are ready.')"
if errorlevel 1 (
    echo [ERROR] Dependency validation failed.
    echo Try: conda env update -n %ENV_NAME% -f environment.yml --prune
    pause
    exit /b 1
)

:: 4. Tracked predictions and model files are sufficient for normal startup.
:: The raw Kaggle dataset is needed only if those artifacts are missing.
if exist "data\processed\predictions.csv" if exist "models\xgboost_model.json" goto model_outputs_ready

echo [INFO] Model outputs are missing. Preparing the training dataset...
if not exist "data\raw\DataCoSupplyChainDataset.csv" if exist "data\raw\archive.zip" (
    powershell -NoProfile -Command "Expand-Archive -Path 'data\raw\archive.zip' -DestinationPath 'data\raw' -Force"
    if errorlevel 1 (
        echo [ERROR] Dataset extraction failed.
        pause
        exit /b 1
    )
)

if not exist "data\raw\DataCoSupplyChainDataset.csv" (
    echo [ERROR] Model outputs and the raw dataset are both missing.
    echo Put DataCoSupplyChainDataset.csv in data\raw\ and run this script again.
    pause
    exit /b 1
)

set "PYTHONIOENCODING=utf-8"
echo [INFO] Running data pipeline...
call "%CONDA_CMD%" run --no-capture-output -n "%ENV_NAME%" python core\data_pipeline.py
if errorlevel 1 (
    echo [ERROR] Data pipeline failed.
    pause
    exit /b 1
)

echo [INFO] Training model and generating predictions...
call "%CONDA_CMD%" run --no-capture-output -n "%ENV_NAME%" python core\model_pipeline.py
if errorlevel 1 (
    echo [ERROR] Model training failed.
    pause
    exit /b 1
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

:: 5. Initialize local authentication and start the API.
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
    echo Run: netstat -ano ^| findstr :8000
    pause
    exit /b 1
)

exit /b 0

:environment_error
echo [ERROR] Failed to create or update the Conda environment.
echo Check your network connection and environment.yml, then try again.
pause
exit /b 1
