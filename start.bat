@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Erstelle virtuelle Umgebung...
    py -3 -m venv .venv || (echo Python nicht gefunden. Bitte Python 3.12+ installieren. & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (pause & exit /b 1)

REM cmd /k haelt das Serverfenster bei Fehlern offen
start "SubTranslate Server" cmd /k ""%~dp0.venv\Scripts\python.exe" -m flask --app app run --port 5000"

set /a tries=0
:wait
curl -s -o nul http://127.0.0.1:5000 && goto ready
set /a tries+=1
if %tries% geq 30 (echo Server startet nicht. Siehe Serverfenster. & pause & exit /b 1)
timeout /t 1 /nobreak >nul
goto wait

:ready
start chrome --app=http://127.0.0.1:5000
