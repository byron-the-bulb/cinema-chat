# WSL2 Port Forwarding Script for Cinema Chat Backend
# Run this in PowerShell as Administrator on Windows

# Get WSL2 IP address
$wslIp = (wsl hostname -I).Trim()
Write-Host "WSL2 IP: $wslIp"

# Remove any existing port proxy for 8765
netsh interface portproxy delete v4tov4 listenport=8765 listenaddress=0.0.0.0

# Add port forwarding from Windows to WSL2
netsh interface portproxy add v4tov4 listenport=8765 listenaddress=0.0.0.0 connectport=8765 connectaddress=$wslIp

# Show the port proxy configuration
Write-Host "`nPort forwarding configured:"
netsh interface portproxy show all

# Add Windows Firewall rule if it doesn't exist
$ruleName = "Cinema Chat Backend Port 8765"
$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue

if ($null -eq $existingRule) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -LocalPort 8765 -Protocol TCP -Action Allow
    Write-Host "`nFirewall rule created"
} else {
    Write-Host "`nFirewall rule already exists"
}

Write-Host "`nSetup complete! Pi should now be able to connect to 192.168.1.143:8765"
