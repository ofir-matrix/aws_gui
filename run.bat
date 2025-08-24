@echo off

echo [INFO] Starting server...
start "" cmd /c "pipenv run python app.py"

echo [INFO] Waiting for the server to start...
:: Give it a few seconds to boot up
timeout /t 10 >nul

echo [INFO] Opening http://127.0.0.1:5000 in default browser...
start "" http://127.0.0.1:5000

echo [INFO] Server is running! Press Ctrl+C in the server window to stop it.
pause
