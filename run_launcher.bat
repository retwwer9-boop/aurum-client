@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul && (
    start "" pythonw -m launcher
    exit /b 0
)
where pyw >nul 2>nul && (
    start "" pyw -3 -m launcher
    exit /b 0
)
where python >nul 2>nul && (
    start "" python -m launcher
    exit /b 0
)
echo Python не найден. Установите Python 3.11+ и включите "Add to PATH".
pause
