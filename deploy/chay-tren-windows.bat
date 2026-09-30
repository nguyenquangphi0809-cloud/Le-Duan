@echo off
REM Chay automaton51 lien tuc tren Windows. Tu khoi dong lai neu bi dung.
REM Dat vao Task Scheduler (Trigger: At log on) de tu chay khi bat may.
REM Nho tat che do Sleep cua may (Settings > System > Power) de AI khong bi ngat.
chcp 65001 >nul
cd /d "%~dp0\.."
:loop
python -m automaton51 --state state run --serve
echo automaton51 dung lai, khoi dong lai sau 30 giay...
timeout /t 30 /nobreak >nul
goto loop
