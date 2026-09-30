@echo off
REM Chay automaton51 lien tuc. Tu khoi dong lai sau 30 giay neu bi dung.
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0\.."
title automaton51 - AI dang lam viec (dong cua so nay = dung AI)
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if not defined PY if exist "%ProgramFiles%\Python313\python.exe" set "PY="%ProgramFiles%\Python313\python.exe""
if not defined PY echo Chua cai Python. Bam dup deploy\cai-dat-windows.bat truoc. & pause & exit /b 1
:loop
%PY% -m automaton51 --state state run --serve
if "%errorlevel%"=="75" goto already
echo automaton51 dung lai, se tu khoi dong lai sau 30 giay... (dong cua so nay neu muon dung han)
timeout /t 30 /nobreak >nul
goto loop
:already
echo AI da dang chay trong mot cua so khac. Cua so nay tu dong sau 10 giay.
timeout /t 10 >nul
exit /b 0
