@echo off
cd /d "%~dp0"
echo Instalando dependencias...
py -m pip install -r requirements.txt -q
py -m playwright install chromium
echo.
echo Levantando StockSwitch en http://127.0.0.1:8001/
py run.py
pause
