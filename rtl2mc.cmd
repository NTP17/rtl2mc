@echo off
python "%~dp0rtl2mc.py" %*
exit /b %errorlevel%
