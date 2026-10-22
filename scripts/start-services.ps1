param([int]$BackendPort=4318,[int]$AgentPort=4319,[switch]$Reload)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskData=Join-Path $taskRoot 'data'
New-Item -ItemType Directory -Path $taskData -Force | Out-Null
$env:PYTHONUTF8='1'
$env:LIME_DATA_DIR=$taskData
$env:LIME_BACKEND_URL='http://127.0.0.1:'+$BackendPort
$env:LIME_AGENT_URL='http://127.0.0.1:'+$AgentPort
$env:LIME_AGENT_PORT=[string]$AgentPort
$taskArguments = @('backend\launch.py','--port',[string]$BackendPort)
if($Reload){$taskArguments=@('-m','uvicorn','studio.api.app:app','--app-dir','backend','--reload','--reload-dir','backend','--host','127.0.0.1','--port',[string]$BackendPort,'--no-access-log')}
$taskBackend=Start-Process -FilePath (Join-Path $taskRoot '.venv\Scripts\python.exe') -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskData ('backend-'+$BackendPort+'-out.log')) -RedirectStandardError (Join-Path $taskData ('backend-'+$BackendPort+'-error.log'))
for($taskTry=0;$taskTry -lt 100;$taskTry++) {
  try { $taskHealth=Invoke-RestMethod -Uri ($env:LIME_BACKEND_URL+'/health') -TimeoutSec 2; if($taskHealth.service -eq 'lime-studio'){break} } catch {}
  Start-Sleep -Milliseconds 300
}
$taskAgent=Start-Process -FilePath 'node.exe' -ArgumentList @('dist\agent\server.mjs') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskData ('agent-'+$AgentPort+'-out.log')) -RedirectStandardError (Join-Path $taskData ('agent-'+$AgentPort+'-error.log'))
@{backend_pid=$taskBackend.Id;agent_pid=$taskAgent.Id;backend_port=$BackendPort;agent_port=$AgentPort} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskData 'dev-services.json') -Encoding utf8
Write-Output 'Local services started.'
