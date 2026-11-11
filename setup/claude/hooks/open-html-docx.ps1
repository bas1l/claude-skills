$ErrorActionPreference = 'SilentlyContinue'
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $path = $payload.tool_input.file_path
    if ($payload.tool_name -eq 'Write' -and $path -and $path -match '\.(html|docx)$' -and (Test-Path -LiteralPath $path)) {
        Start-Process -FilePath $path
    }
} catch { }
exit 0
