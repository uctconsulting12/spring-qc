# Run ONCE on the edge box, in an elevated (Run as Administrator) PowerShell,
# so the admin PC and operator HMI panels on the shop-floor LAN can reach the
# app. Safe to re-run.

New-NetFirewallRule -DisplayName "Spring QC app (8001)" `
    -Direction Inbound -Protocol TCP -LocalPort 8001 `
    -Action Allow -Profile Private, Domain `
    -ErrorAction SilentlyContinue | Out-Null

Write-Host "Firewall rule for port 8001 (Private/Domain profiles) is in place."
Write-Host "Postgres (5432) is intentionally NOT opened here - leave it that way. Windows"
Write-Host "Firewall default-denies inbound connections with no matching allow rule, so"
Write-Host "5432 stays unreachable from the rest of the LAN even though the container"
Write-Host "publishes it on all interfaces."
Write-Host ""
Write-Host "Current IPv4 addresses on this box (pick the shop-floor LAN one for EDGE_HOST):"
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } |
    Select-Object InterfaceAlias, IPAddress | Format-Table -AutoSize
