param(
    [string]$Device = "8299e66f",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$adbCandidates = @(
    "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    "C:\IA\flujo\xio\actual\platform-tools\adb.exe"
)
$adb = $adbCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $adb) { throw "No se encontró adb." }

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Get-Location) "work\device_snapshots"
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$telephony = (& $adb -s $Device shell dumpsys telephony.registry) -join "`n"
$wifi = (& $adb -s $Device shell dumpsys wifi) -join "`n"
$props = (& $adb -s $Device shell getprop) -join "`n"
$storage = (& $adb -s $Device shell df -h /data /sdcard) -join "`n"

function First-Match([string]$Text, [string]$Pattern) {
    $match = [regex]::Match($Text, $Pattern)
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

$record = [ordered]@{
    capturedAt = (Get-Date).ToUniversalTime().ToString("o")
    device = $Device
    model = First-Match $props '\[ro\.product\.model\]: \[(.*?)\]'
    android = First-Match $props '\[ro\.build\.version\.release\]: \[(.*?)\]'
    operator = First-Match $telephony 'mOperatorAlphaLong=([^,]+)'
    dataTechnology = First-Match $telephony 'getRilDataRadioTechnology=([^,]+)'
    channel = First-Match $telephony 'mChannelNumber=([^,]+)'
    rsrp = First-Match $telephony 'rsrp=(-?\d+)'
    rsrq = First-Match $telephony 'rsrq=(-?\d+)'
    rssnr = First-Match $telephony 'rssnr=(-?\d+)'
    sinr = First-Match $telephony 'ssSinr = (-?\d+)'
    wifiFrequency = First-Match $wifi 'frequency=([0-9]+)'
    wifiRssi = First-Match $wifi 'RSSI[:= ]+(-?\d+)'
    telephonyRaw = "telephony-$stamp.txt"
    wifiRaw = "wifi-$stamp.txt"
    storageRaw = "storage-$stamp.txt"
}

$jsonPath = Join-Path $OutputDirectory "xiaomi-state-$stamp.json"
$record | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $jsonPath
$telephony | Set-Content -Encoding utf8 (Join-Path $OutputDirectory $record.telephonyRaw)
$wifi | Set-Content -Encoding utf8 (Join-Path $OutputDirectory $record.wifiRaw)
$storage | Set-Content -Encoding utf8 (Join-Path $OutputDirectory $record.storageRaw)

Write-Output ($record | ConvertTo-Json -Depth 4)
Write-Output "Guardado: $jsonPath"
