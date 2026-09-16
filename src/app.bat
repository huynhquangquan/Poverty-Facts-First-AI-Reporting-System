@echo off
setlocal

title Chatbot Ho Ngheo - app.py
cd /d "%~dp0"

echo ============================================
echo   Chatbot Ho Ngheo - app.py
echo ============================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

REM Kiem tra Ollama co dang chay khong. Neu may chua cai Ollama thi bo qua va app van chay duoc che do khong LLM.
curl -s http://localhost:11434 >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Ollama chua chay. Thu khoi dong Ollama...
    start "" ollama serve
    timeout /t 3 /nobreak >nul
)

REM Kiem tra database
if not exist "db\poverty.db" (
    echo [!] Chua co database. Dang build tu file Excel...
    "%PYTHON_EXE%" build_db.py
    echo.
)

echo [OK] Dang khoi dong ung dung...
echo [OK] Trinh duyet se tu dong mo tai: http://localhost:8501
echo.
echo [De thoat: dong cua so nay hoac nhan Ctrl+C]
echo.

"%PYTHON_EXE%" -m streamlit run app.py --server.port 8501 --server.headless false

pause
endlocal
