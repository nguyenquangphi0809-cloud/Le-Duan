@echo off
REM ================================================================
REM  CAI DAT automaton51 TREN WINDOWS - bam dup de chay
REM  Tu cai Python (neu chua co), thu vien, hoi thong tin, kiem tra,
REM  cho AI tu chay moi khi bat may. Chay lai tep nay de doi thong tin.
REM ================================================================
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0\.."
title Cai dat automaton51
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if not defined PY if exist "%ProgramFiles%\Python313\python.exe" set "PY="%ProgramFiles%\Python313\python.exe""
if defined PY goto have_python
echo Chua co Python. Dang cai Python 3.13 bang winget (mat 1-3 phut, co the hien hop thoai xin phep - bam Yes)...
winget install --id Python.Python.3.13 --exact --silent --accept-package-agreements --accept-source-agreements
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if not defined PY if exist "%ProgramFiles%\Python313\python.exe" set "PY="%ProgramFiles%\Python313\python.exe""
if defined PY goto have_python
echo.
echo Khong tu cai duoc Python. Hay cai thu cong tai https://www.python.org/downloads/windows/
echo (khi cai nho tich o "Add python.exe to PATH"), roi bam dup lai tep nay.
pause
exit /b 1
:have_python
echo Dung Python: %PY%
%PY% -m automaton51 --state state install
echo.
pause
