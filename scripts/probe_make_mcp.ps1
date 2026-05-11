param(
    [string]$ServerUrl = $env:MAKE_MCP_SERVER_URL,
    [string]$BearerToken = $env:MAKE_MCP_BEARER_TOKEN
)

if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
    throw "MAKE_MCP_SERVER_URL is required."
}
if ([string]::IsNullOrWhiteSpace($BearerToken)) {
    throw "MAKE_MCP_BEARER_TOKEN is required."
}

function Invoke-MakeMcp {
    param([hashtable]$Payload)

    $body = $Payload | ConvertTo-Json -Depth 20 -Compress
    $response = Invoke-WebRequest `
        -Uri $ServerUrl `
        -Method Post `
        -Headers @{
            Authorization = "Bearer $BearerToken"
            Accept = "application/json, text/event-stream"
            "Content-Type" = "application/json"
        } `
        -Body $body `
        -UseBasicParsing `
        -TimeoutSec 30

    $dataLines = @()
    foreach ($line in ($response.Content -split "`n")) {
        if ($line.StartsWith("data: ")) {
            $data = $line.Substring(6).Trim()
            if ($data -and $data -ne "[DONE]") {
                $dataLines += $data
            }
        }
    }
    if ($dataLines.Count -eq 0) {
        return $response.Content | ConvertFrom-Json
    }
    return ($dataLines -join "") | ConvertFrom-Json
}

$initialize = Invoke-MakeMcp @{
    jsonrpc = "2.0"
    id = 1
    method = "initialize"
    params = @{
        protocolVersion = "2025-03-26"
        capabilities = @{}
        clientInfo = @{
            name = "careagent-backend"
            version = "0.1.0"
        }
    }
}

$tools = Invoke-MakeMcp @{
    jsonrpc = "2.0"
    id = 2
    method = "tools/list"
    params = @{}
}

[pscustomobject]@{
    serverName = $initialize.result.serverInfo.name
    serverTitle = $initialize.result.serverInfo.title
    protocolVersion = $initialize.result.protocolVersion
    toolCount = @($tools.result.tools).Count
    tools = @($tools.result.tools | ForEach-Object { $_.name })
} | ConvertTo-Json -Depth 5
