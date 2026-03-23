# E2E: Create trust request, login, call suggest-reply, output response and status.
$base = "http://localhost:8000/api"
$ErrorActionPreference = "Stop"

Write-Host "1. Creating trust request..."
$createBody = '{"requester_email":"e2e@test.com","message":"We need encrypted data at rest and compliance documentation. Can you help?","workspace_id":1}'
$create = Invoke-RestMethod -Uri "$base/trust-requests/" -Method Post -ContentType "application/json" -Body $createBody
$rid = $create.id
Write-Host "   Created request id=$rid"

Write-Host "2. Logging in (demo@trust.local)..."
$loginBody = '{"email":"demo@trust.local","password":"j"}'
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginResp = Invoke-WebRequest -Uri "$base/auth/login" -Method Post -ContentType "application/json" -Body $loginBody -WebSession $session -UseBasicParsing
if ($loginResp.StatusCode -ne 200) { Write-Host "   Login failed: $($loginResp.StatusCode)"; exit 1 }
Write-Host "   Login OK"

Write-Host "3. Calling suggest-reply for request $rid..."
try {
    $suggestResp = Invoke-WebRequest -Uri "$base/trust-requests/$rid/suggest-reply" -Method Post -WebSession $session -UseBasicParsing
    Write-Host "   Status: $($suggestResp.StatusCode)"
    Write-Host "   Raw content length: $($suggestResp.Content.Length)"
    Write-Host "   Raw (first 500 chars): $($suggestResp.Content.Substring(0, [Math]::Min(500, $suggestResp.Content.Length)))"
    $json = $suggestResp.Content | ConvertFrom-Json
    $draft = $json.draft
    $reply = $json.reply
    if ($draft) { Write-Host "   draft length: $($draft.Length)"; Write-Host "   draft preview: $($draft.Substring(0, [Math]::Min(120, $draft.Length)))..." }
    elseif ($reply) { Write-Host "   reply length: $($reply.Length)" }
    else { Write-Host "   No draft/reply in response. Keys: $($json.PSObject.Properties.Name -join ',')" }
} catch {
    Write-Host "   Error: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.BaseStream.Position = 0
        Write-Host "   Body: $($reader.ReadToEnd())"
    }
    exit 1
}
Write-Host "Done."
