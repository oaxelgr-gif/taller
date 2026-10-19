# =====================================================================
#  SGT Taller - Instalador / actualizador para Windows 10 y 11 (64 bits)
#  Lo ejecuta INSTALAR_O_ACTUALIZAR.bat con permisos de administrador.
#  Es seguro ejecutarlo varias veces: instala lo que falta y actualiza
#  el sistema conservando la base de datos, las fotos y la configuración.
# =====================================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ---------------------------------------------------------------------
#  Configuración
# ---------------------------------------------------------------------
$Raiz        = 'C:\SGT-Taller'
$PuertoWeb   = 5000
$PgPuerto    = 5433                 # distinto de 5432 para no chocar con otro PostgreSQL
$PgServicio  = 'SGT-PostgreSQL'
$PyVersion   = '3.12.10'
$PyUrls      = @("https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip")
$GetPipUrls  = @('https://bootstrap.pypa.io/get-pip.py')
$PgUrls      = @(
    'https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64.exe',
    'https://sbp.enterprisedb.com/getfile.jsp?fileid=1260621'
)
$PgPaginaDescarga = 'https://www.enterprisedb.com/downloads/postgres-postgresql-downloads'

$Paquete      = Split-Path -Parent $PSScriptRoot
$Fuente       = Join-Path $Paquete 'sistema'
$Instaladores = Join-Path $Paquete 'instaladores'
$Python       = Join-Path $Raiz 'python\python.exe'
$PythonW      = Join-Path $Raiz 'python\pythonw.exe'
$App          = Join-Path $Raiz 'app'
$Datos        = Join-Path $Raiz 'datos'
$Config       = Join-Path $Raiz 'config'
$ClaveSuper   = Join-Path $Config 'pg_super.txt'
$Icono        = Join-Path $Raiz 'sgt.ico'
$Temporal     = Join-Path $env:TEMP 'sgt-instalador'
$TotalPasos   = 11

# ---------------------------------------------------------------------
#  Utilidades
# ---------------------------------------------------------------------
function Paso([int]$n, [string]$texto) {
    Write-Host ''
    Write-Host ("[{0}/{1}] {2}" -f $n, $TotalPasos, $texto) -ForegroundColor Cyan
}
function Ok([string]$texto)    { Write-Host "     OK  $texto" -ForegroundColor Green }
function Info([string]$texto)  { Write-Host "     $texto" }
function Aviso([string]$texto) { Write-Host "     AVISO: $texto" -ForegroundColor Yellow }
function Falla([string]$texto) { throw $texto }

function Clave-Aleatoria([int]$n = 24) {
    $abc = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] $n
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $abc[$_ % $abc.Length] })
}

function Puerto-Abierto([int]$puerto) {
    $cliente = New-Object Net.Sockets.TcpClient
    try {
        $intento = $cliente.BeginConnect('127.0.0.1', $puerto, $null, $null)
        if ($intento.AsyncWaitHandle.WaitOne(800) -and $cliente.Connected) { return $true }
        return $false
    } catch { return $false } finally { $cliente.Close() }
}

function Esperar-Puerto([int]$puerto, [int]$segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        if (Puerto-Abierto $puerto) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return (Puerto-Abierto $puerto)
}

function Descargar([string[]]$urls, [string]$destino, [long]$minimoBytes) {
    foreach ($url in $urls) {
        Info "Descargando: $url"
        Remove-Item $destino -Force -ErrorAction SilentlyContinue
        try {
            if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
                & curl.exe -L --fail --retry 3 --retry-delay 3 --connect-timeout 30 -# -o $destino $url
                if ($LASTEXITCODE -ne 0) { throw "curl terminó con código $LASTEXITCODE" }
            } else {
                Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing -ErrorAction Stop
            }
            if ((Test-Path $destino) -and ((Get-Item $destino).Length -ge $minimoBytes)) { return $true }
            Aviso 'El archivo descargado está incompleto.'
        } catch {
            Aviso "No se pudo descargar ($_)."
        }
    }
    Remove-Item $destino -Force -ErrorAction SilentlyContinue
    return $false
}

# Busca primero en la carpeta "instaladores" del paquete (uso sin internet).
function Obtener([string]$patronLocal, [string[]]$urls, [string]$nombre, [long]$minimoBytes) {
    if (Test-Path $Instaladores) {
        $local = Get-ChildItem -Path $Instaladores -Filter $patronLocal -File -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending | Select-Object -First 1
        if ($local) { Info "Usando $($local.Name) de la carpeta instaladores."; return $local.FullName }
    }
    New-Item -ItemType Directory -Force -Path $Temporal | Out-Null
    $destino = Join-Path $Temporal $nombre
    if (Descargar $urls $destino $minimoBytes) { return $destino }
    return $null
}

function Python-Ejecutar {
    & $Python @args
    if ($LASTEXITCODE -ne 0) { Falla "Python terminó con error ($LASTEXITCODE): $($args -join ' ')" }
}

function Crear-Acceso([string]$ruta, [string]$destino, [string]$argumentos, [string]$icono, [string]$descripcion) {
    $shell = New-Object -ComObject WScript.Shell
    $acceso = $shell.CreateShortcut($ruta)
    $acceso.TargetPath = $destino
    $acceso.Arguments = $argumentos
    $acceso.WorkingDirectory = $App
    $acceso.IconLocation = $icono
    $acceso.Description = $descripcion
    $acceso.Save()
}

# ---------------------------------------------------------------------
#  Programa principal
# ---------------------------------------------------------------------
Clear-Host
Write-Host '=================================================================' -ForegroundColor DarkCyan
Write-Host '   SGT Taller  -  Instalación / actualización para Windows'       -ForegroundColor White
Write-Host '=================================================================' -ForegroundColor DarkCyan
Write-Host "   Carpeta de instalación: $Raiz"
Write-Host '   No cierres esta ventana hasta que termine.'

New-Item -ItemType Directory -Force -Path (Join-Path $Datos 'logs') | Out-Null
$registro = Join-Path $Datos ("logs\instalacion_{0}.txt" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
try { Start-Transcript -Path $registro -Force | Out-Null } catch {}

$codigo = 0
try {
    # -----------------------------------------------------------------
    Paso 1 'Revisando el equipo'
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Falla 'Se necesitan permisos de administrador. Ejecuta INSTALAR_O_ACTUALIZAR.bat.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        Falla 'Windows de 32 bits no es compatible (PostgreSQL sólo existe para 64 bits).'
    }
    if ([Environment]::OSVersion.Version.Major -lt 10) { Falla 'Se requiere Windows 10 u 11.' }
    if (-not (Test-Path (Join-Path $Fuente 'run.py'))) { Falla "No se encontró la carpeta 'sistema' junto al instalador. Extrae el ZIP completo." }
    $libre = (Get-PSDrive -Name ($Raiz.Substring(0, 1))).Free
    if ($libre -lt 1.5GB) { Falla ("Se necesitan al menos 1.5 GB libres en el disco (hay {0:N1} GB)." -f ($libre / 1GB)) }
    Get-ChildItem -Path $Paquete -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
    $esActualizacion = Test-Path (Join-Path $App '.env')
    if ($esActualizacion) { Ok 'Instalación existente detectada: se actualizará conservando los datos.' }
    else { Ok 'Instalación nueva.' }
    foreach ($carpeta in @($Raiz, $Datos, $Config, (Join-Path $Datos 'uploads'), (Join-Path $Datos 'respaldos'))) {
        New-Item -ItemType Directory -Force -Path $carpeta | Out-Null
    }
    # El servidor corre con el usuario normal: necesita escribir registros, fotos y respaldos.
    foreach ($sub in @('logs', 'uploads', 'respaldos')) {
        & icacls.exe (Join-Path $Datos $sub) /grant '*S-1-5-32-545:(OI)(CI)M' /T /C /Q | Out-Null
    }

    # -----------------------------------------------------------------
    Paso 2 'Deteniendo el sistema si está encendido'
    $detener = Join-Path $App 'windows\detener.pyw'
    if ((Test-Path $Python) -and (Test-Path $detener)) {
        & $Python $detener --silencioso
    }
    Get-Process -Name python, pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($Raiz, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Ok 'Listo.'

    # -----------------------------------------------------------------
    Paso 3 "Python $PyVersion (versión portátil, sólo para este sistema)"
    $carpetaPy = Join-Path $Raiz 'python'
    if (-not (Test-Path $Python)) {
        $zip = Obtener 'python-*-embed-amd64.zip' $PyUrls 'python-embed.zip' 5MB
        if (-not $zip) { Falla 'No se pudo descargar Python. Revisa la conexión a internet.' }
        Expand-Archive -Path $zip -DestinationPath $carpetaPy -Force
        Ok 'Python instalado.'
    } else { Ok 'Python ya estaba instalado.' }
    # El archivo ._pth define las rutas de Python embebido: se habilita pip y la carpeta app.
    $pth = Get-ChildItem -Path $carpetaPy -Filter 'python*._pth' | Select-Object -First 1
    if (-not $pth) { Falla 'La instalación de Python está incompleta. Borra C:\SGT-Taller\python y reintenta.' }
    $zipStdlib = $pth.Name -replace '\._pth$', '.zip'
    Set-Content -Path $pth.FullName -Encoding ASCII -Value @($zipStdlib, '.', '..\app', 'Lib\site-packages', 'import site')
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    & $Python -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        $getpip = Obtener 'get-pip.py' $GetPipUrls 'get-pip.py' 500KB
        if (-not $getpip) { Falla 'No se pudo descargar el instalador de pip.' }
        Python-Ejecutar $getpip --no-warn-script-location --quiet
        Ok 'pip instalado.'
    } else { Ok 'pip disponible.' }

    # -----------------------------------------------------------------
    Paso 4 'Copiando el sistema'
    $envActual = Join-Path $App '.env'
    $envRespaldo = Join-Path $Config 'env.respaldo'
    if (Test-Path $envActual) { Copy-Item $envActual $envRespaldo -Force }
    & robocopy.exe $Fuente $App /MIR /XD __pycache__ /XF .env *.pyc /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Falla "No se pudieron copiar los archivos (robocopy $LASTEXITCODE)." }
    if ((Test-Path $envRespaldo) -and -not (Test-Path $envActual)) { Copy-Item $envRespaldo $envActual -Force }
    Copy-Item (Join-Path $App 'windows\sgt.ico') $Icono -Force
    Ok "Sistema copiado en $App"

    # -----------------------------------------------------------------
    Paso 5 'Librerías de Python (puede tardar unos minutos la primera vez)'
    $requisitos = Join-Path $App 'requirements.txt'
    $ruedas = Join-Path $Instaladores 'wheels'
    if (Test-Path $ruedas) {
        Python-Ejecutar -m pip install --no-index --find-links $ruedas --no-warn-script-location -r $requisitos
    } else {
        Python-Ejecutar -m pip install --upgrade --no-warn-script-location --prefer-binary -r $requisitos
    }
    & $Python -m compileall -q -x 'tests' $App | Out-Null   # arranque más rápido
    Ok 'Librerías instaladas.'

    # -----------------------------------------------------------------
    Paso 6 'Base de datos PostgreSQL 16'
    $servicio = Get-Service -Name $PgServicio -ErrorAction SilentlyContinue
    if (-not $servicio) {
        if (Test-Path (Join-Path $Datos 'pgdata\PG_VERSION')) {
            Falla "Existe la carpeta de datos $Datos\pgdata pero no el servicio $PgServicio. Recupérala o muévela antes de reinstalar."
        }
        # Carpeta de contraseñas: sólo Administradores y SYSTEM (se protege antes de escribir).
        & icacls.exe $Config /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' | Out-Null
        $super = Clave-Aleatoria 24
        Set-Content -Path $ClaveSuper -Value $super -Encoding ASCII -NoNewline
        $instaladorPg = Obtener 'postgresql-*-windows-x64.exe' $PgUrls 'postgresql-16-windows-x64.exe' 100MB
        if (-not $instaladorPg) {
            Start-Process $PgPaginaDescarga
            Falla ("No se pudo descargar PostgreSQL. Descarga la versión 16 para Windows x86-64 desde la página que se abrió, " +
                   "guárdala en la carpeta 'instaladores' del paquete y vuelve a ejecutar el instalador.")
        }
        Info 'Instalando PostgreSQL (aparece una barra de progreso; tarda de 2 a 6 minutos)...'
        $argumentos = @(
            '--mode', 'unattended', '--unattendedmodeui', 'minimal',
            '--superpassword', $super,
            '--serverport', "$PgPuerto",
            '--servicename', $PgServicio,
            '--prefix', "`"$Raiz\pgsql`"",
            '--datadir', "`"$Datos\pgdata`"",
            '--enable-components', 'server,commandlinetools',
            '--disable-components', 'pgAdmin,stackbuilder',
            '--create_shortcuts', '0'
        )
        $proceso = Start-Process -FilePath $instaladorPg -ArgumentList $argumentos -Wait -PassThru
        $servicio = Get-Service -Name $PgServicio -ErrorAction SilentlyContinue
        if (-not $servicio) {
            Falla ("La instalación de PostgreSQL no terminó (código $($proceso.ExitCode)). " +
                   "Revisa el registro en $env:TEMP\install-postgresql.log")
        }
        Ok 'PostgreSQL instalado como servicio de Windows.'
    } else {
        if (-not (Test-Path $ClaveSuper)) { Falla "Falta $ClaveSuper (contraseña de PostgreSQL). No se puede actualizar la base de datos." }
        Ok 'PostgreSQL ya estaba instalado.'
    }
    Set-Service -Name $PgServicio -StartupType Automatic
    if ((Get-Service -Name $PgServicio).Status -ne 'Running') { Start-Service -Name $PgServicio }
    if (-not (Esperar-Puerto $PgPuerto 60)) { Falla "PostgreSQL no responde en el puerto $PgPuerto." }
    Ok "PostgreSQL activo en el puerto $PgPuerto (sólo accesible desde este equipo)."

    # -----------------------------------------------------------------
    Paso 7 'Configurando el sistema y la base de datos'
    Push-Location $App
    try {
        Python-Ejecutar (Join-Path $App 'windows\configurar.py') --raiz $Raiz --pg-puerto $PgPuerto `
            --pg-servicio $PgServicio --pg-super-archivo $ClaveSuper --puerto-web $PuertoWeb
    } finally { Pop-Location }
    Info 'Reiniciando PostgreSQL para aplicar los ajustes de memoria...'
    Restart-Service -Name $PgServicio -Force
    if (-not (Esperar-Puerto $PgPuerto 60)) { Falla 'PostgreSQL no volvió a iniciar.' }
    Ok 'Base de datos lista.'

    # -----------------------------------------------------------------
    Paso 8 "Permitiendo el acceso desde celulares (firewall, puerto $PuertoWeb)"
    try {
        Get-NetFirewallRule -Group 'SGT Taller' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName "SGT Taller - puerto $PuertoWeb" -Group 'SGT Taller' -Direction Inbound `
            -Action Allow -Protocol TCP -LocalPort $PuertoWeb -RemoteAddress LocalSubnet -Profile Any | Out-Null
        foreach ($ejecutable in @($Python, $PythonW)) {
            New-NetFirewallRule -DisplayName ("SGT Taller - " + (Split-Path $ejecutable -Leaf)) -Group 'SGT Taller' `
                -Direction Inbound -Action Allow -Program $ejecutable -Protocol TCP -LocalPort $PuertoWeb `
                -RemoteAddress LocalSubnet -Profile Any | Out-Null
        }
        Ok 'Sólo equipos de la red local pueden entrar.'
    } catch {
        Aviso "No se pudo configurar el firewall ($_). Si usas otro antivirus, permite el puerto $PuertoWeb."
    }

    # -----------------------------------------------------------------
    Paso 9 'Energía: evitar que el equipo se suspenda conectado a la corriente'
    & powercfg.exe /change standby-timeout-ac 0 | Out-Null
    & powercfg.exe /change hibernate-timeout-ac 0 | Out-Null
    Ok 'El equipo no se dormirá mientras esté conectado (la pantalla sí puede apagarse).'

    # -----------------------------------------------------------------
    Paso 10 'Accesos directos'
    $lanzador = "`"$App\windows\lanzador.pyw`""
    $escritorio = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $menu = Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'SGT Taller'
    $inicioWindows = [Environment]::GetFolderPath('CommonStartup')
    New-Item -ItemType Directory -Force -Path $menu | Out-Null
    $accesoEscritorio = Join-Path $escritorio 'SGT Taller.lnk'
    Crear-Acceso $accesoEscritorio $PythonW $lanzador "$Icono,0" 'Abrir el sistema del taller'
    Crear-Acceso (Join-Path $menu 'SGT Taller.lnk') $PythonW $lanzador "$Icono,0" 'Abrir el sistema del taller'
    Crear-Acceso (Join-Path $menu 'Conectar celulares (QR).lnk') $PythonW "$lanzador --ruta /conectar" "$Icono,0" 'Muestra el código QR para entrar desde el celular'
    Crear-Acceso (Join-Path $menu 'Detener servidor.lnk') $PythonW "`"$App\windows\detener.pyw`"" "$env:SystemRoot\System32\shell32.dll,27" 'Apaga el servidor del sistema'
    Crear-Acceso (Join-Path $menu 'Respaldos.lnk') "$env:SystemRoot\explorer.exe" "`"$Datos\respaldos`"" "$env:SystemRoot\System32\shell32.dll,4" 'Carpeta de respaldos diarios'
    Crear-Acceso (Join-Path $inicioWindows 'SGT Taller (servidor).lnk') $PythonW "$lanzador --sin-navegador" "$Icono,0" 'Enciende el servidor al iniciar Windows'
    Ok 'Escritorio: "SGT Taller"   |   Menú Inicio: carpeta "SGT Taller"   |   Arranque automático al iniciar Windows.'

    # -----------------------------------------------------------------
    Paso 11 'Encendiendo el sistema'
    # Se abre a través del Explorador para que corra con el usuario normal (sin permisos de administrador).
    Start-Process -FilePath "$env:SystemRoot\explorer.exe" -ArgumentList "`"$accesoEscritorio`""
    if (Esperar-Puerto $PuertoWeb 90) {
        Ok 'Sistema encendido.'
    } else {
        Aviso "El sistema tardó en encender. Usa el ícono del escritorio; si falla revisa $Datos\logs\servidor.log"
    }
    $ip = ''
    Push-Location $App
    try { $ip = (& $Python -c "from app.red import ips_lan; i = ips_lan(); print(i[0] if i else '')" 2>$null) } catch {}
    Pop-Location

    Write-Host ''
    Write-Host '=================================================================' -ForegroundColor Green
    Write-Host '   INSTALACIÓN TERMINADA' -ForegroundColor Green
    Write-Host '=================================================================' -ForegroundColor Green
    Write-Host "   En esta computadora:  http://localhost:$PuertoWeb"
    if ($ip) { Write-Host "   Desde celulares:      http://${ip}:$PuertoWeb   (misma red WiFi)" -ForegroundColor White }
    Write-Host '   Código QR:            menú del sistema > "Conectar dispositivos"'
    Write-Host "   Respaldos diarios:    $Datos\respaldos"
    Write-Host "   Registro:             $registro"
} catch {
    $codigo = 1
    Write-Host ''
    Write-Host '=================================================================' -ForegroundColor Red
    Write-Host '   NO SE PUDO COMPLETAR LA INSTALACIÓN' -ForegroundColor Red
    Write-Host "   $_" -ForegroundColor Red
    Write-Host '=================================================================' -ForegroundColor Red
    Write-Host "   Puedes volver a ejecutar el instalador: continúa donde se quedó."
    Write-Host "   Registro completo: $registro"
} finally {
    try { Stop-Transcript | Out-Null } catch {}
    Remove-Item -Recurse -Force $Temporal -ErrorAction SilentlyContinue
}
exit $codigo
