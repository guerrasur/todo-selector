# Autoactualizacion de Todo-Selector. La llama iniciar_app.bat en cada arranque.
#
# Si la carpeta es un clon de git, usa "git pull". Si no lo es (o sea: bajaste
# el zip y listo), baja el zip del repo y copia los archivos que cambiaron.
# En cualquier caso, si no hay internet sigue de largo sin romper nada.
#
# El unico archivo que no se puede pisar es iniciar_app.bat, porque esta
# corriendo mientras esto se ejecuta: se deja como iniciar_app.bat.nuevo y el
# propio .bat lo aplica antes de salir.

param(
    [string]$Carpeta = $PSScriptRoot,
    [string]$Repo    = 'guerrasur/todo-selector',
    [string]$Rama    = 'main'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # Invoke-WebRequest es mucho mas rapido sin la barra

$LANZADOR = 'iniciar_app.bat'


function Iguales($a, $b) {
    if (-not (Test-Path -LiteralPath $b)) { return $false }
    return (Get-FileHash -LiteralPath $a).Hash -eq (Get-FileHash -LiteralPath $b).Hash
}


function Copiar-Sobre {
    # Copia solo lo que cambio. No borra nada que no venga en el zip, asi que
    # archivos locales (base de datos vieja, notas, .venv) quedan intactos.
    param($Origen, $Destino)

    $cambios = 0
    foreach ($f in Get-ChildItem -LiteralPath $Origen -Recurse -File) {
        $rel    = $f.FullName.Substring($Origen.Length).TrimStart('\')
        $actual = Join-Path $Destino $rel
        if (Iguales $f.FullName $actual) { continue }

        if ($rel -ieq $LANZADOR) {
            Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $Destino "$LANZADOR.nuevo") -Force
        } else {
            $dir = Split-Path -Parent $actual
            if (-not (Test-Path -LiteralPath $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
            }
            Copy-Item -LiteralPath $f.FullName -Destination $actual -Force
        }
        Write-Host "  actualizado: $rel"
        $cambios++
    }
    return $cambios
}


function Actualizar-ConGit {
    # git manda avisos por stderr que no son errores: no cortar por eso.
    $ErrorActionPreference = 'Continue'
    & git -C $Carpeta pull --ff-only 2>&1 | ForEach-Object { Write-Host "  $_" }
    return ($LASTEXITCODE -eq 0)
}


function Actualizar-ConZip {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $url  = "https://github.com/$Repo/archive/refs/heads/$Rama.zip"
    $tmp  = Join-Path $env:TEMP ('todoselector-' + [guid]::NewGuid().ToString('N'))
    $zip  = "$tmp.zip"

    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    try {
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 30
        Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force

        # GitHub empaqueta todo adentro de una carpeta tipo "todo-selector-main"
        $raiz = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
        if (-not $raiz) { throw 'el zip vino vacio' }

        return (Copiar-Sobre $raiz.FullName $Carpeta)
    } finally {
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}


function Crear-AccesoDirecto {
    # Deja "TODO-SELECTOR" en el escritorio, con el icono del repo.
    #
    # Se hace UNA sola vez y queda la marca en la carpeta de datos: si el
    # usuario lo borra a proposito, no se lo volvemos a poner en cada
    # arranque. La marca vive fuera del repo para que sobreviva a las
    # actualizaciones y a bajar el zip de nuevo.
    #
    # Nada de esto puede impedir que la app arranque: si algo falla, se
    # avisa y se sigue.

    $datos = Join-Path $env:LOCALAPPDATA 'TodoSelector'
    $marca = Join-Path $datos 'acceso-directo.ok'
    if (Test-Path -LiteralPath $marca) { return }

    $lanzador = Join-Path $Carpeta $LANZADOR
    if (-not (Test-Path -LiteralPath $lanzador)) { return }

    $escritorio = [Environment]::GetFolderPath('Desktop')
    if (-not $escritorio -or -not (Test-Path -LiteralPath $escritorio)) { return }

    $destino = Join-Path $escritorio 'TODO-SELECTOR.lnk'
    if (Test-Path -LiteralPath $destino) {
        # Ya estaba (lo hizo el usuario a mano, o una version anterior).
        if (-not (Test-Path -LiteralPath $datos)) {
            New-Item -ItemType Directory -Path $datos -Force | Out-Null
        }
        Set-Content -LiteralPath $marca -Value 'ya existia' -Encoding ASCII
        return
    }

    $shell  = New-Object -ComObject WScript.Shell
    $acceso = $shell.CreateShortcut($destino)
    $acceso.TargetPath       = $lanzador
    $acceso.WorkingDirectory = $Carpeta
    $acceso.Description      = 'Todo-Selector: apagar y prender productos'

    $icono = Join-Path $Carpeta 'todo2.ico'
    if (Test-Path -LiteralPath $icono) { $acceso.IconLocation = "$icono,0" }

    $acceso.Save()

    if (-not (Test-Path -LiteralPath $datos)) {
        New-Item -ItemType Directory -Path $datos -Force | Out-Null
    }
    Set-Content -LiteralPath $marca -Value (Get-Date -Format s) -Encoding ASCII

    Write-Host '  te deje un acceso directo "TODO-SELECTOR" en el escritorio.'
}


$esClon = Test-Path -LiteralPath (Join-Path $Carpeta '.git')
$hayGit = [bool](Get-Command git -ErrorAction SilentlyContinue)

try {
    if ($esClon -and $hayGit) {
        Write-Host 'Buscando actualizaciones (git)...'
        if (-not (Actualizar-ConGit)) {
            Write-Host '  no se pudo (sin conexion o cambios locales). Sigo con la version que tengo.'
        }
    }
    elseif ($esClon) {
        # Carpeta de desarrollo sin git instalado: pisar por zip borraria trabajo.
        Write-Host 'Esta carpeta es un clon de git pero git no esta instalado: no la toco.'
    }
    else {
        Write-Host 'Buscando actualizaciones...'
        $n = Actualizar-ConZip
        if ($n -eq 0) { Write-Host '  ya estabas al dia.' }
        else          { Write-Host "  listo: $n archivo(s) actualizados." }
    }
}
catch {
    Write-Host "No se pudo actualizar: $($_.Exception.Message)"
    Write-Host 'Sigo con la version que ya tengo.'
}

# Despues de actualizar, porque el icono puede haber llegado recien ahora.
try {
    Crear-AccesoDirecto
}
catch {
    Write-Host "No pude crear el acceso directo: $($_.Exception.Message)"
}

exit 0
