@echo off
chcp 65001 >nul
echo     Сортировка файлов
echo.
echo Выбор режима:
echo [1] Тестовый режим (показ без перемещения)
echo [2] Реальное перемещение файлов
echo [3] Выход
echo.
set /p choice="Ваш выбор (1/2/3): "

if "%choice%"=="1" (
    echo.
    echo Запуск в тестовом режиме...
    python one_time_cleanup.py --dry-run
    goto end
)

if "%choice%"=="2" (
    echo.
    echo Все файлы будут будет перемещены!
    set /p confirm="Продолжить? (y/n): "
    if /i "%confirm%"=="y" (
        echo.
        echo Запуск перемещения файлов...
        python one_time_cleanup.py
    ) else (
        echo Операция отменена.
    )
    goto end
)

if "%choice%"=="3" (
    echo Выход...
    exit /b
)

echo Неверный выбор!

:end
echo.
echo Нажмите любую клавишу для выхода...
pause >nul
