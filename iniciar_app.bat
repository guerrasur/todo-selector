@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Todo-Selector

REM Arranque de Todo-Selector en cualquier PC con Windows, sin git y sin
REM preparacion previa: se autoactualiza, instala Python si falta, instala las
REM dependencias y levanta la app.
REM
REM   iniciar_app.bat              arranque normal
REM   iniciar_app.bat simulado     modo simulado (no toca las plataformas)
REM   iniciar_app.bat reinstalar   fuerza reinstalar dependencias y Chromium

set "PAQUETE_PYTHON=Python.Python.3.12"
set "DATOS=%LOCALAPPDATA%\TodoSelector"

if /i "%~1"=="simulado" set "STOCKSWITCH_SIMULADO=1"
if /i "%~1"=="reinstalar" del /q "%DATOS%\deps-*.ok" >nul 2>&1

REM Sobra de un swap anterior del lanzador.
if exist "_aplicar_update.cmd" del /q "_aplicar_update.cmd" >nul 2>&1


REM ---------- 1. Autoactualizacion (no necesita git) ----------

if exist "iniciar_app.bat.nuevo" goto :aplicar_update

if exist "actualizar.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0actualizar.ps1"
) else (
    echo No encuentro actualizar.ps1: salteo la autoactualizacion.
)

if exist "iniciar_app.bat.nuevo" goto :aplicar_update


REM ---------- 2. Python ----------

set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :python_ok

REM python.exe puede ser el alias trucho de la Microsoft Store: se descarta.
for /f "delims=" %%p in ('where python 2^>nul ^| findstr /i /v "WindowsApps"') do if not defined PY set PY="%%p"
if defined PY goto :python_ok

call :instalar_python

py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :python_ok

echo.
echo No pude dejar Python andando solo. Instalalo a mano desde
echo    https://www.python.org/downloads/windows/
echo tildando "Add python.exe to PATH", y volve a correr este archivo.
echo.
pause
exit /b 1

:python_ok


REM ---------- 3. Dependencias (solo si cambio requirements.txt) ----------

if not exist "%DATOS%" mkdir "%DATOS%" >nul 2>&1

set "REQHASH="
for /f "usebackq delims=" %%h in (`powershell -NoProfile -Command "(Get-FileHash '%~dp0requirements.txt' -Algorithm MD5).Hash"`) do set "REQHASH=%%h"
if not defined REQHASH goto :instalar_deps
if exist "%DATOS%\deps-%REQHASH%.ok" goto :deps_ok

:instalar_deps
echo Instalando dependencias (la primera vez tarda unos minutos)...
%PY% -m pip install --upgrade pip -q
%PY% -m pip install -r requirements.txt -q
if errorlevel 1 goto :error_deps
%PY% -m playwright install chromium
if errorlevel 1 goto :error_deps
if defined REQHASH echo ok> "%DATOS%\deps-%REQHASH%.ok"

:deps_ok


REM ---------- 4. Arrancar ----------

echo.
if defined STOCKSWITCH_SIMULADO echo MODO SIMULADO: no se toca ninguna plataforma.
echo Levantando Todo-Selector en http://127.0.0.1:8001/
echo.
%PY% run.py
pause
exit /b


REM ---------- subrutinas ----------

:instalar_python
echo.
echo No encontre Python en esta PC. Lo instalo yo, no tenes que hacer nada.
where winget >nul 2>&1
if errorlevel 1 (
    echo Esta PC no tiene winget, asi que no puedo instalarlo solo.
    echo Te abro la pagina: instalalo tildando "Add python.exe to PATH".
    start "" https://www.python.org/downloads/windows/
    goto :eof
)
winget install --id %PAQUETE_PYTHON% -e --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 winget install --id %PAQUETE_PYTHON% -e --source winget --silent --accept-package-agreements --accept-source-agreements
REM El PATH de esta ventana quedo viejo: lo releemos del registro.
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%p"
goto :eof

:error_deps
echo.
echo Fallo la instalacion de dependencias. Fijate si tenes internet y volve a probar.
echo.
pause
exit /b 1

:aplicar_update
REM Un .bat no se puede pisar mientras corre: lo reemplaza un ayudante que
REM arranca aparte, espera a que esta ventana cierre y vuelve a abrir la app.
echo Aplicando actualizacion del lanzador...
> "_aplicar_update.cmd" echo @echo off
>>"_aplicar_update.cmd" echo timeout /t 2 /nobreak ^>nul
>>"_aplicar_update.cmd" echo move /y "%~dp0iniciar_app.bat.nuevo" "%~f0" ^>nul
>>"_aplicar_update.cmd" echo if exist "%~dp0iniciar_app.bat.nuevo" del /q "%~dp0iniciar_app.bat.nuevo"
>>"_aplicar_update.cmd" echo start "" "%~f0"
start "" /min "%~dp0_aplicar_update.cmd"
exit /b
