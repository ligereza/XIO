param(
    [string]$Device = "8299e66f",
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$adbCandidates = @(
    "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    "C:\IA\flujo\xio\actual\platform-tools\adb.exe"
)
$adb = $adbCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $adb) { throw "No se encontró adb." }

$javaCandidates = @(
    "$env:JAVA_HOME\bin\java.exe",
    "C:\Program Files\Android\Android Studio\jbr\bin\java.exe"
)
$java = $javaCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $java) { throw "No se encontró Java. Instala Android Studio y vuelve a ejecutar este script." }
$env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $java)

$gradlew = Join-Path $project "gradlew.bat"
if (-not (Test-Path -LiteralPath $gradlew)) {
    throw "Falta gradlew.bat. Abre el proyecto en Android Studio una vez para generar el wrapper o añade el wrapper de Gradle."
}

$model = Join-Path $project "app\src\main\assets\efficientnet_lite0.tflite"
if (-not (Test-Path -LiteralPath $model)) { throw "Falta el modelo en assets." }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $model).Hash
if ($hash -ne "6C7AB0A6E5DCBF38A8C33B960996A55A3B4300B36A018C4545801DE3A3C8BDE0") {
    throw "El SHA-256 del modelo no coincide: $hash"
}

& $adb devices | Out-Host
& $gradlew -p $project assembleDebug
$apk = Join-Path $project "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path -LiteralPath $apk)) { throw "No se generó el APK." }

if (-not $Install) {
    Write-Output "APK listo: $apk"
    Write-Output "No se modificó ningún dispositivo. Usa -Install sólo después de confirmar la instalación en el Xiaomi."
    exit 0
}

& $adb -s $Device install -r $apk
& $adb -s $Device shell am start -n com.xio.vision/.MainActivity
Write-Output "Demo instalada y abierta en $Device"
