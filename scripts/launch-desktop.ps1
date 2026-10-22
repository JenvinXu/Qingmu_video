param([switch]$Accept)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskRelease=Join-Path $taskRoot 'release\win-unpacked'
$taskExecutable=Get-ChildItem -LiteralPath $taskRelease -Filter '*Lime Studio.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if($taskExecutable) {
    $taskArgs=@()
    if($Accept){$taskArgs=@('--accept')}
    if($taskArgs.Count){Start-Process -FilePath $taskExecutable.FullName -ArgumentList $taskArgs -WorkingDirectory $taskRelease -WindowStyle Hidden}
    else {Start-Process -FilePath $taskExecutable.FullName -WorkingDirectory $taskRelease -WindowStyle Hidden}
} else {
    $taskExecutable=Join-Path $taskRoot 'node_modules\electron\dist\electron.exe'
    $taskArgs=@('.')
    if($Accept){$taskArgs+=@('--accept')}
    Start-Process -FilePath $taskExecutable -ArgumentList $taskArgs -WorkingDirectory $taskRoot -WindowStyle Hidden
}
