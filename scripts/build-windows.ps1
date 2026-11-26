[CmdletBinding()]
param(
    [string] $Python = 'python',
    [switch] $BrowserOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root 'build/windows'
$frontend = Join-Path $root 'frontend'
$name = 'GB28181-Analyzer'
$variant = if ($BrowserOnly) { 'browser' } else { 'desktop' }

Push-Location $root
try {
    $platform = & $Python -c "import sysconfig; print(sysconfig.get_platform())"
    if ($LASTEXITCODE -ne 0 -or $platform -ne 'win-amd64') {
        throw 'Build requires 64-bit x86 Windows Python.'
    }
    $version = & $Python -c "import sys; sys.path.insert(0, 'backend'); from app import __version__; print(__version__)"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read application version.' }

    npm.cmd --prefix $frontend ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed.' }
    npm.cmd --prefix $frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }

    $packArgs = @(
        '--noconfirm', '--clean', '--noupx', '--onedir', '--console',
        '--name', 'AnalyzerEngine', '--paths', "$root/backend",
        '--hidden-import', 'uvicorn.loops.asyncio',
        '--hidden-import', 'uvicorn.protocols.http.h11_impl',
        '--hidden-import', 'uvicorn.lifespan.on',
        '--add-data', "$frontend/dist:frontend",
        '--distpath', "$output/app", '--workpath', "$output/work",
        '--specpath', $output, "$root/backend/windows_launcher.py"
    )
    if (!$BrowserOnly) {
        $cargo = (Get-Command cargo -ErrorAction SilentlyContinue).Source
        if (!$cargo) { $cargo = "$env:USERPROFILE/.cargo/bin/cargo.exe" }
        if (!(Test-Path -LiteralPath $cargo)) { throw "Native Shell desktop build needs Rust and Cargo." }
        & $cargo build --locked --release --manifest-path desktop/Cargo.toml
        if ($LASTEXITCODE -ne 0) { throw 'Rust build failed.' }
        $packArgs += @('--add-binary', "$root/desktop/target/release/gb28181_scan.dll;.")
    }
    & $Python -m PyInstaller @packArgs
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    $stage = Join-Path $output ([guid]::NewGuid().ToString())
    $bundle = Join-Path $stage $name
    $engine = Join-Path $bundle 'engine'
    New-Item -ItemType Directory -Force -Path $engine | Out-Null
    Copy-Item -Path "$output/app/AnalyzerEngine/*" -Destination $engine -Recurse -Force
    if ($BrowserOnly) {
        $launcher = '@echo off' + "`r`n" + '"%~dp0engine\AnalyzerEngine.exe" %*' + "`r`n"
        Set-Content -LiteralPath (Join-Path $bundle 'Start-Analyzer.cmd') -Value $launcher -Encoding ascii -NoNewline
    } else {
        $sdk = Join-Path $output 'nsh-0.7.1'
        $nsh = Join-Path $sdk 'nsh/bin/nsh.exe'
        if (!(Test-Path -LiteralPath $nsh)) {
            $sdkZip = Join-Path $output 'nsh-sdk.zip'
            Invoke-WebRequest 'https://github.com/longbridge/nsh/releases/download/v0.7.1/nsh-windows-x86_64.zip' -OutFile $sdkZip
            if ((Get-FileHash $sdkZip).Hash -ne 'F09AAF5155B0C57213FBDA29CE1E82CD973694D33C745F74B94A1A966A673433') { throw 'Native Shell SDK checksum mismatch.' }
            Expand-Archive -LiteralPath $sdkZip -DestinationPath $sdk -Force
        }
        $oldRuntime = $env:NSH_RUNTIME
        try {
            $env:NSH_RUNTIME = "$sdk/nsh/runtime"
            & $nsh package desktop-nsh --target windows --name AnalyzerShell -o "$output/nsh-pinned"
            if ($LASTEXITCODE -ne 0) { throw 'Native Shell packaging failed.' }
        } finally { $env:NSH_RUNTIME = $oldRuntime }
        Copy-Item -LiteralPath "$output/nsh-pinned/AnalyzerShell" -Destination "$bundle/shell" -Recurse
        Copy-Item "$sdk/nsh/LICENSE-APACHE" "$bundle/shell/LICENSE-APACHE"
        Copy-Item desktop/target/release/gb28181-desktop.exe "$bundle/$name.exe" -Force
    }
    $reported = & "$engine/AnalyzerEngine.exe" --version
    if ($LASTEXITCODE -ne 0 -or $reported -ne $version) { throw 'Portable version check failed.' }
    Copy-Item -LiteralPath 'LICENSE' -Destination $bundle
    Copy-Item -LiteralPath 'docs/WINDOWS.md' -Destination "$bundle/README-Windows.md"
    $suffix = if ($BrowserOnly) { "-browser" } else { "" }
    $archive = Join-Path $output "gb28181-analyzer-windows-x64-v$version$suffix.zip"
    Compress-Archive -LiteralPath $bundle -DestinationPath $archive -Force
    $digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksum = "$digest  $(Split-Path -Leaf $archive)"
    Set-Content -LiteralPath "$archive.sha256" -Value $checksum -Encoding ascii
    Write-Output $checksum
    Write-Output $archive
} finally {
    Pop-Location
}
