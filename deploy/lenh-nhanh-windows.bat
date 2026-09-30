@echo off
REM Lenh nhanh cho chu so huu: bam dup, go so/chu roi Enter.
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0\.."
title automaton51 - lenh nhanh
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
if not defined PY if exist "%ProgramFiles%\Python313\python.exe" set "PY="%ProgramFiles%\Python313\python.exe""
if not defined PY echo Chua cai Python. Bam dup deploy\cai-dat-windows.bat truoc. & pause & exit /b 1
set "A51=%PY% -m automaton51 --state state"
:menu
echo.
echo ========================= automaton51 =========================
echo  1. Xem tinh trang (vi, quy 51%%, quy 49%%)
echo  2. Xem don hang dang mo
echo  3. Ghi so: DA HOAN TIEN cho mot don
echo  T. Xac nhan: khach da chuyen tien nhung quen ghi ma don
echo  4. Ghi so: DA CHUYEN quy 51%% sang tai khoan ca nhan
echo  5. Ghi so: DA NAP them tien API Claude
echo  6. Doi thong tin (tai khoan nhan tien, khoa API, Gmail...)
echo  7. Nhap danh ba (tep CSV xuat tu contacts.google.com)
echo  8. Kiem tra ket noi
echo  9. TAM DUNG AI
echo  C. Cho AI chay tiep (tat tam dung) va mo cua so chay
echo  B. Mo bang dieu khien tren trinh duyet
echo  0. Thoat
set "CHON="
set /p CHON=Chon roi Enter: 
if not defined CHON goto menu
set "CHON=%CHON:"=%"
if "%CHON%"=="1" %A51% status
if "%CHON%"=="2" %A51% orders
if "%CHON%"=="3" goto refund
if /i "%CHON%"=="T" goto paid
if "%CHON%"=="4" goto payout
if "%CHON%"=="5" goto fund
if "%CHON%"=="6" %A51% setup
if "%CHON%"=="7" goto contacts
if "%CHON%"=="8" %A51% doctor
if "%CHON%"=="9" %A51% stop
if /i "%CHON%"=="C" goto resume
if /i "%CHON%"=="B" start "" http://localhost:8451
if "%CHON%"=="0" exit /b 0
goto menu

:refund
set "MA="
set /p MA=Nhap ma don da hoan tien (vi du HTABC234): 
if not defined MA goto menu
set "MA=%MA:"=%"
%A51% refund "%MA%"
goto menu

:paid
set "MA="
set /p MA=Nhap ma don trong email [CAN BAN] (vi du HTABC234): 
if not defined MA goto menu
set "MA=%MA:"=%"
%A51% paid "%MA%"
goto menu

:payout
set "USD="
set /p USD=So USD da chuyen (bo trong roi Enter = toan bo quy 51%%): 
if not defined USD goto payout_all
set "USD=%USD:"=%"
%A51% payout "%USD%"
goto menu
:payout_all
%A51% payout
goto menu

:fund
set "USD="
set /p USD=So USD vua nap vao API Claude (vi du 20): 
if not defined USD goto menu
set "USD=%USD:"=%"
%A51% fund "%USD%" --memo "Nap them tien API Claude"
goto menu

:contacts
set "CSV="
echo Keo tha tep CSV vao cua so nay roi Enter.
set /p CSV=(bo trong = dung tep contacts.csv trong thu muc Downloads): 
if not defined CSV set "CSV=%USERPROFILE%\Downloads\contacts.csv"
set "CSV=%CSV:"=%"
%A51% outreach import "%CSV%"
goto menu

:resume
%A51% resume
start "automaton51" /min "%~dp0chay-tren-windows.bat"
goto menu
