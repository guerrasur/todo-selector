@echo off
cd /d "%~dp0"

if exist ".git" (
    echo Buscando actualizaciones...
    git pull --ff-only
    if errorlevel 1 (
        echo No se pudo autoactualizar ^(sin conexion o cambios locales^). Sigo con la version que ya tengo.
    )
) else (
    echo Esta carpeta no es un clon de git: no hay autoactualizacion.
    echo Bajala con "git clone" en vez de descargar el zip para tener updates automaticos.
)

echo Instalando dependencias...
py -m pip install -r requirements.txt -q
py -m playwright install chromium
echo.
echo Levantando StockSwitch en http://127.0.0.1:8001/
py run.py
pause
