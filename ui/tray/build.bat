@echo off
chcp 65001 > nul
echo ======================================================
echo    Сборка DNS-Switcher Windows (.exe)
echo ======================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден в системе. Установите Python 3.10+ и добавьте его в PATH.
    pause
    exit /b 1
)

echo [1/2] Проверка и установка зависимостей...
pip install -r ..\..\requirements.txt
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)

echo.
echo [2/2] Компиляция приложения через PyInstaller...
python build_exe.py
if errorlevel 1 (
    echo [ОШИБКА] Сборка завершилась с ошибкой.
    pause
    exit /b 1
)

echo.
echo Готово! Собранный файл находится в папке: dist\DNS-Switcher.exe
echo.
pause
