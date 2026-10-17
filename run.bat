@echo off
chcp 65001 >nul
rem Запуск File-sorter одной командой: при первом запуске uv сам создаёт окружение
rem и ставит зависимости. Аргументы передаются программе: run.bat clean --dry-run

where uv >nul 2>nul
if errorlevel 1 (
    echo Не найден uv: менеджер Python-проектов, на котором работает программа.
    echo Установите его командой в PowerShell и запустите этот файл снова:
    echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    pause
    exit /b 1
)

uv run --project "%~dp0." file-sorter %*
set "code=%errorlevel%"

rem при запуске двойным щелчком окно закрылось бы сразу
if "%~1"=="" pause
exit /b %code%
