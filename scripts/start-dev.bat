@echo off
REM Amplifier Distro - Development Environment Startup Script
REM
REM This script builds and starts the Docker development environment.
REM Run this from Windows (cmd.exe or PowerShell) or by double-clicking.

echo ========================================
echo Amplifier Distro - Starting Dev Environment
echo ========================================
echo.

REM Navigate to project root (script is in scripts/ subdirectory)
cd /d "%~dp0.."

echo [1/4] Stopping any existing containers...
docker compose down >nul 2>&1

echo.
echo [2/4] Building Docker images...
docker compose --profile all build
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker build failed
    pause
    exit /b 1
)

echo.
echo [3/4] Starting all containers (CLI, TUI, GUI, Voice)...
docker compose --profile all up -d
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to start containers
    pause
    exit /b 1
)

echo.
echo [4/5] Waiting for installation to complete...
timeout /t 10 /nobreak >nul

echo.
echo [5/5] Launching TUI...
echo.
echo ========================================
echo Starting Amplifier TUI interface...
echo ========================================
echo.

REM Launch the TUI (this will take over the terminal)
docker compose exec tui amplifier-tui

REM After TUI exits, show info
echo.
echo ========================================
echo TUI closed. Services are still running.
echo.
echo To restart TUI:
echo   docker compose exec tui amplifier-tui
echo.
echo To enter CLI:
echo   docker compose exec cli bash
echo.
echo To stop all services:
echo   docker compose down -v
echo ========================================
echo.
pause
