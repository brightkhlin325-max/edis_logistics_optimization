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

:: 3. Verify the packages required by the API, model, and MILP optimizer.
echo [INFO] Verifying Python dependencies...
call "%CONDA_CMD%" run -n "%ENV_NAME%" python -c "import fastapi, uvicorn, pandas, numpy, sklearn, xgboost, pulp, multipart; print('[OK] Python dependencies are ready.')"
if errorlevel 1 (
    echo [ERROR] A required Python package is unavailable.
    echo Try: conda env update -n %ENV_NAME% -f environment.yml
    pause
    exit /b 1
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

if not exist "data\raw\DataCoSupplyChainDataset.csv" (
    echo [ERROR] Model outputs are missing and the training dataset was not found.
    echo Put DataCoSupplyChainDataset.csv in data\raw\ and run this script again.
    pause
    exit /b 1
)

echo [INFO] Running data pipeline...
set "PYTHONIOENCODING=utf-8"
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
