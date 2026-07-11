# Run backend (:8000) + frontend (:3000) in this terminal, logs interleaved.
# Usage: .\dev.ps1   (Ctrl+C stops both)

$root = $PSScriptRoot

$backend = Start-Job -Name api -ScriptBlock {
    Set-Location "$using:root\backend"
    & "$using:root\venv\Scripts\python.exe" app.py 2>&1
}
$frontend = Start-Job -Name web -ScriptBlock {
    Set-Location "$using:root\frontend"
    npm run dev 2>&1
}

Write-Host "backend :8000 + frontend :3000 starting... Ctrl+C to stop both" -ForegroundColor Cyan

try {
    while ($true) {
        Receive-Job $backend | ForEach-Object { Write-Host "[api] $_" -ForegroundColor DarkCyan }
        Receive-Job $frontend | ForEach-Object { Write-Host "[web] $_" -ForegroundColor DarkGreen }
        if ($backend.State -eq 'Failed' -or $frontend.State -eq 'Failed') { break }
        Start-Sleep -Milliseconds 300
    }
}
finally {
    Stop-Job $backend, $frontend -ErrorAction SilentlyContinue
    Remove-Job $backend, $frontend -Force -ErrorAction SilentlyContinue
    # ponytail: jobs don't always kill child procs; sweep the ports directly
    foreach ($port in 8000, 3000) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "stopped." -ForegroundColor Cyan
}
