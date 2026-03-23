# Free port 8000 by killing only the process that is listening on it.
# Run from repo root: .\scripts\kill-port-8000.ps1
# If kill fails, close the terminal that is running "npm run dev:all" and run this again.
$port = 8000
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $conn) {
  Write-Host "Port $port is not in use."
  exit 0
}
$procId = $conn.OwningProcess
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
$name = if ($proc) { $proc.ProcessName } else { "(process not visible - may be in another session)" }
Write-Host "Port $port is used by PID $procId $name"
try {
  Stop-Process -Id $procId -Force -ErrorAction Stop
  Write-Host "Stopped PID $procId"
} catch {
  Write-Host "Could not stop PID $procId : $_"
  Write-Host "Close the terminal running 'npm run dev:all' (or the process using port $port), then run this script again."
  exit 1
}
Start-Sleep -Seconds 2
$check = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($check) { Write-Host "WARNING: Port $port still in use. Try closing the other terminal and run again."; exit 1 }
Write-Host "Port $port is free."
exit 0
