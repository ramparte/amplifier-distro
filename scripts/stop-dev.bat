@echo off
REM Amplifier Distro - Stop Development Environment
REM
REM Stops and removes containers, volumes (clean slate).

echo ========================================
echo Amplifier Distro - Stopping Dev Environment
echo ========================================
echo.

REM Navigate to project root
cd /d "%~dp0.."

echo Tearing down containers and volumes...
docker compose down -v
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to stop containers
    pause
    exit /b 1
)

echo.
echo ========================================
echo Environment stopped and cleaned.
echo ========================================
echo.
pause
