<#
.SYNOPSIS
    Creates Desktop + Start Menu shortcuts that open Spring QC pages in the
    default web browser - the "menu or shortcuts" for the simply-a-web-client
    architecture (no app to install on the client PC, just icons that point
    a normal browser at the server).

.DESCRIPTION
    Run this on any client PC (the admin PC, or a PC/kiosk box being used to
    view the Operator screen) once, pointed at the edge box's address. It
    writes .url files (the same format Windows uses for "Internet Shortcut"
    icons) - opening one just launches whatever the default browser is, no
    custom app involved.

.PARAMETER ServerAddress
    The Spring QC server's IP or hostname, e.g. 192.168.1.50. Do not include
    a port or scheme.

.PARAMETER Port
    The server's port. Defaults to 8001 (the app's default).

.PARAMETER Pages
    Which shortcuts to create. Defaults to all four. Pass a subset if this
    client PC only needs one, e.g. -Pages Operator for an operator panel.

.EXAMPLE
    .\Create-SpringQCShortcuts.ps1 -ServerAddress 192.168.1.50

.EXAMPLE
    .\Create-SpringQCShortcuts.ps1 -ServerAddress 192.168.1.50 -Pages Operator
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerAddress,

    [int]$Port = 8001,

    [ValidateSet('Admin', 'Operator', 'Monitor', 'Reports')]
    [string[]]$Pages = @('Admin', 'Operator', 'Monitor', 'Reports'),

    # Off by default - most client PCs only need the Desktop icon; flip this
    # on for a shared/kiosk PC where a Start Menu entry is also useful.
    [switch]$AlsoStartMenu
)

$ErrorActionPreference = 'Stop'

$pageMap = @{
    'Admin'    = @{ Path = '/admin';    Label = 'Spring QC - Admin' }
    'Operator' = @{ Path = '/operator'; Label = 'Spring QC - Operator' }
    'Monitor'  = @{ Path = '/monitor';  Label = 'Spring QC - Monitor' }
    'Reports'  = @{ Path = '/reports';  Label = 'Spring QC - Reports' }
}

$baseUrl = "http://${ServerAddress}:${Port}"

function New-UrlShortcut {
    param([string]$Directory, [string]$Label, [string]$Url)
    $dest = Join-Path $Directory "$Label.url"
    # Internet Shortcut format - Windows Explorer renders this with a globe
    # icon and opens it in the default browser on double-click. No COM
    # object, no admin rights, no dependency on anything but a text file.
    @"
[InternetShortcut]
URL=$Url
IconIndex=0
"@ | Set-Content -Path $dest -Encoding ASCII
    Write-Host "  Created: $dest -> $Url"
}

$desktop = [Environment]::GetFolderPath('Desktop')
Write-Host "Spring QC shortcuts -> $baseUrl"
Write-Host ""
Write-Host "Desktop:"
foreach ($p in $Pages) {
    $info = $pageMap[$p]
    New-UrlShortcut -Directory $desktop -Label $info.Label -Url "$baseUrl$($info.Path)"
}

if ($AlsoStartMenu) {
    $startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Spring QC'
    New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
    Write-Host ""
    Write-Host "Start Menu (Spring QC folder):"
    foreach ($p in $Pages) {
        $info = $pageMap[$p]
        New-UrlShortcut -Directory $startMenu -Label $info.Label -Url "$baseUrl$($info.Path)"
    }
}

Write-Host ""
Write-Host "Done. Double-click any shortcut to open that screen in your default browser."
