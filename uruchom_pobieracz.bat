@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\groco\AppData\Local\Programs\Python\Python312\python.exe"
set "FFMPEG_BIN=C:\Users\groco\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-essentials_build\bin"

if not exist "%PYTHON_EXE%" (
    echo Nie znaleziono interpretera Python:
    echo %PYTHON_EXE%
    echo.
    echo Zainstaluj Python albo popraw sciezke w pliku uruchom_pobieracz.bat.
    pause
    exit /b 1
)

if exist "%FFMPEG_BIN%\ffmpeg.exe" (
    set "PATH=%FFMPEG_BIN%;%PATH%"
)

"%PYTHON_EXE%" "%~dp0run_app.py"

if errorlevel 1 (
    echo.
    echo Aplikacja zakonczyla sie bledem.
    pause
)
