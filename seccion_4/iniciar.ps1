<#
.SYNOPSIS
    Prepara y abre la aplicación en un solo paso (Windows).

.DESCRIPTION
    La primera vez: crea el entorno virtual, instala las dependencias, crea la base de datos (SQLite) y
    genera los datos de demostración dentro del código, con un usuario por rol. Las contraseñas se muestran
    una sola vez en la consola (o se usa la de la variable DEMO_PASSWORD, si está definida).
    Las siguientes veces: solo verifica dependencias y migraciones y abre el servidor. Nunca borra datos.

.PARAMETER Red
    Permite abrir la aplicación desde otros computadores de la misma red (escucha en todas las interfaces
    y autoriza las IP de este equipo). Solo para demostraciones en una red de confianza.

.PARAMETER Puerto
    Puerto del servidor (por defecto 8000).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File iniciar.ps1
    powershell -ExecutionPolicy Bypass -File iniciar.ps1 -Red
#>
param(
    [switch]$Red,
    [int]$Puerto = 8000
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Paso([string]$texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

function Buscar-Python {
    # Devuelve un Python 3.11+ instalado: el comando y sus argumentos (python, o el lanzador "py -3")
    foreach ($opcion in @(@{ Cmd = "python"; Args = @() }, @{ Cmd = "py"; Args = @("-3") })) {
        if (-not (Get-Command $opcion.Cmd -ErrorAction SilentlyContinue)) { continue }
        $a = $opcion.Args
        $version = & $opcion.Cmd @a -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($version -and ([version]$version -ge [version]"3.11")) { return $opcion }
    }
    throw "Se necesita Python 3.11 o superior. Descárguelo de https://www.python.org/downloads/ y vuelva a ejecutar."
}

# 1. Entorno virtual y dependencias --------------------------------------------------------------
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Paso "Creando el entorno virtual (.venv)"
    $py = Buscar-Python
    $a = $py.Args
    & $py.Cmd @a -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual." }
}
Paso "Instalando dependencias (requirements.txt)"
& $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }

# 2. Base de datos y datos de demostración --------------------------------------------------------
$primeraVez = -not (Test-Path (Join-Path $PSScriptRoot "db.sqlite3"))
Paso "Preparando la base de datos"
& $venvPython manage.py migrate --noinput -v 0
if ($LASTEXITCODE -ne 0) { throw "Falló la migración de la base de datos." }
if ($primeraVez) {
    Paso "Generando los datos de demostración y un usuario por rol"
    & $venvPython manage.py cargar_datos_demo --usuarios-demo
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron cargar los datos de demostración." }
    Write-Host "   Guarde las contraseñas de arriba: no se vuelven a mostrar." -ForegroundColor Yellow
}

# 3. Servidor ---------------------------------------------------------------------------------------
$direccion = "127.0.0.1"
$urls = @("http://127.0.0.1:$Puerto/")
if ($Red) {
    $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -ExpandProperty IPAddress)
    $env:DJANGO_ALLOWED_HOSTS = (@("localhost", "127.0.0.1", $env:COMPUTERNAME) + $ips) -join ","
    $direccion = "0.0.0.0"
    $urls += $ips | ForEach-Object { "http://${_}:$Puerto/" }
    Write-Host "   Windows puede pedir permiso en el firewall para Python: acéptelo solo en redes privadas." -ForegroundColor Yellow
}
Paso "Abriendo la aplicación (Ctrl+C para detenerla)"
$urls | ForEach-Object { Write-Host "   $_" -ForegroundColor Green }
& $venvPython manage.py runserver "${direccion}:$Puerto"
