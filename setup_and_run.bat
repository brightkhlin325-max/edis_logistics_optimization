@echo off
setlocal EnableExtensions

:: Always run relative to this repository, even when launched by double-click.
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

:: XGBoost and LightGBM each ship their own OpenMP runtime; loading both in one
:: process aborts on Windows ("OMP: Error #15"). The ROI endpoints score with
:: LightGBM while delay endpoints use XGBoost, so allow the duplicate runtime.
set "KMP_DUPLICATE_LIB_OK=TRUE"

:: LLM backend configuration template.
:: Manager UI settings are preferred and persist encrypted in data\processed\llm_runtime_config.json.
:: These environment defaults are used only when Manager UI settings do not exist.
if not defined SLIDE_LLM_PROVIDER set "SLIDE_LLM_PROVIDER=openai"
if not defined SLIDE_LLM_MODEL set "SLIDE_LLM_MODEL=gpt-4o-mini"
if not defined SLIDE_LLM_API_KEY set "SLIDE_LLM_API_KEY="
:: To use a free local LLM instead, install Ollama, run `ollama pull llama3.1`,
:: then uncomment the Ollama lines below.
:: set "SLIDE_LLM_PROVIDER=ollama"
:: set "SLIDE_LLM_MODEL=llama3.1"
:: set "SLIDE_LLM_API_URL=http://localhost:11434/api/chat"
:: For cloud providers, change provider/model and paste your own key below.
:: Example: set "SLIDE_LLM_PROVIDER=openai"
:: Example: set "SLIDE_LLM_MODEL=gpt-4o-mini"
:: Example: set "SLIDE_LLM_API_KEY=你的_key"

set "ENV_NAME=Fastapp"
set "APP_URL=http://localhost:8000/static/index.html"

echo ==========================================
echo EDIS Setup and Run Script
echo ==========================================
echo [INFO] Project: %CD%

:: 1. Check for local Python virtual environment (.venv) first, then fallback to Conda.
set "USE_VENV=0"
if exist ".venv\Scripts\python.exe" (
    set "USE_VENV=1"
    set "RUN_CMD=.venv\Scripts\python.exe"
    echo [INFO] Local Python virtual environment venv detected.
) else (
    set "CONDA_CMD="
    rem 先找標準安裝位置的 conda.bat(雙擊時 conda 不在 PATH 也能抓到；不依賴區塊內 errorlevel）
    if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "CONDA_CMD=%USERPROFILE%\anaconda3\condabin\conda.bat"
    if not defined CONDA_CMD if exist "%USERPROFILE%\miniconda3\condabin\conda.bat" set "CONDA_CMD=%USERPROFILE%\miniconda3\condabin\conda.bat"
    if not defined CONDA_CMD if exist "C:\ProgramData\anaconda3\condabin\conda.bat" set "CONDA_CMD=C:\ProgramData\anaconda3\condabin\conda.bat"
    if not defined CONDA_CMD if exist "C:\ProgramData\miniconda3\condabin\conda.bat" set "CONDA_CMD=C:\ProgramData\miniconda3\condabin\conda.bat"
    rem 非標準安裝：用 PATH 搜尋 conda.bat / conda.exe，取「完整路徑」當備援(不會回歸到壞的 bare conda.exe）
    if not defined CONDA_CMD for %%I in (conda.bat) do if not defined CONDA_CMD if not "%%~$PATH:I"=="" set "CONDA_CMD=%%~$PATH:I"
    if not defined CONDA_CMD for %%I in (conda.exe) do if not defined CONDA_CMD if not "%%~$PATH:I"=="" set "CONDA_CMD=%%~$PATH:I"
)

if %USE_VENV% equ 0 (
    if not defined CONDA_CMD (
        echo [ERROR] Conda was not found.
        echo Install Miniconda or Anaconda, then reopen this script.
        pause
        exit /b 1
    )
)

:: 2. Create the environment only when missing; avoid slow updates on every run.
if %USE_VENV% equ 1 goto use_venv_env

echo [INFO] Checking Conda environment "%ENV_NAME%"...
call "%CONDA_CMD%" run -n "%ENV_NAME%" python --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] Environment "%ENV_NAME%" not detected.
    echo [INFO] Creating environment from environment.yml. This may take a few minutes...
    call "%CONDA_CMD%" env create -f environment.yml
    if errorlevel 1 goto environment_error
) else (
    echo [INFO] Conda environment "%ENV_NAME%" is ready. (Skipping update to save time)
    
    :: Verify if pydantic and pydantic_core are correctly working (preventing windows import crash)
    call "%CONDA_CMD%" run -n "%ENV_NAME%" python -c "import pydantic" >nul 2>nul
    if errorlevel 1 (
        echo [WARNING] Pydantic or pydantic-core dependency is corrupted. Repairing...
        call "%CONDA_CMD%" run -n "%ENV_NAME%" python -m pip install --force-reinstall pydantic pydantic-core
        if errorlevel 1 (
            echo [ERROR] Failed to auto-repair Pydantic.
            pause
            exit /b 1
        )
        echo [INFO] Repair completed.
    )
)
set "RUN_CMD="%CONDA_CMD%" run -n "%ENV_NAME%" python"
set "RUN_CMD_INTERACTIVE="%CONDA_CMD%" run --no-capture-output -n "%ENV_NAME%" python"
goto env_done

:use_venv_env
echo [INFO] Using virtual environment venv.
set "RUN_CMD=.venv\Scripts\python.exe"
set "RUN_CMD_INTERACTIVE=.venv\Scripts\python.exe"

:env_done

:: 3. Existing predictions and model files are enough to run the application.
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

:model_outputs_ready
echo [INFO] Model and prediction files are ready.

:: 3b. Build the unified decision dataset for the ROI Simulator (only when missing).
:: Non-fatal: if inputs are absent the app still launches; ROI pages return 404 until built.
if exist "data\processed\decision_dataset.csv" goto decision_ready
echo [INFO] Building decision dataset for ROI Simulator...
call %RUN_CMD_INTERACTIVE% scripts\build_decision_dataset.py
if errorlevel 1 (
    echo [WARNING] Decision dataset build failed. The ROI Simulator pages will be
    echo           unavailable until "python scripts\build_decision_dataset.py" succeeds.
)
:decision_ready

if /I "%~1"=="tune-threshold" (
    echo [INFO] Running threshold tuning report...
    call %RUN_CMD_INTERACTIVE% scripts\tune_threshold.py
    if errorlevel 1 (
        echo [ERROR] Threshold tuning failed.
        pause
        exit /b 1
    )
    echo [INFO] Threshold tuning completed.
    pause
    exit /b 0
)

:: 4. Create the local authentication database and launch the app.
echo [INFO] Initializing authentication database...
call %RUN_CMD_INTERACTIVE% core\auth.py
if errorlevel 1 (
    echo [ERROR] Authentication database initialization failed.
    pause
    exit /b 1
)

echo [INFO] Starting EDIS API server...
echo [INFO] Browser: %APP_URL%
echo [INFO] Press Ctrl+C to stop the server.
start "" "%APP_URL%"

call %RUN_CMD_INTERACTIVE% -m uvicorn app:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
    echo.
    echo [ERROR] Server failed to start. Port 8000 may already be in use.
    echo Close the old server or run: netstat -ano ^| findstr :8000
    pause
    exit /b 1
)

exit /b 0

:environment_error
echo [ERROR] Failed to create the Conda environment.
echo Check your network connection and environment.yml, then try again.
pause
exit /b 1
