[CmdletBinding()]
param(
    [string] $Python = 'python'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root 'build/windows'
$frontend = Join-Path $root 'frontend'
$name = 'GB28181-Analyzer'

Push-Location $root
try {
    $platform = & $Python -c "import sysconfig; print(sysconfig.get_platform())"
    if ($LASTEXITCODE -ne 0 -or $platform -ne 'win-amd64') {
        throw 'Build requires 64-bit x86 Windows Python.'
    }
    $version = & $Python -c "import sys; sys.path.insert(0, 'backend'); from app import __version__; print(__version__)"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read application version.' }

    npm --prefix $frontend ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed.' }
    npm --prefix $frontend run build
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
    & $Python -m PyInstaller @packArgs
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    $bundle = Join-Path "$output/desktop" $name
    $engine = Join-Path $bundle 'engine'
    New-Item -ItemType Directory -Force -Path $engine | Out-Null
    Copy-Item -Path "$output/app/AnalyzerEngine/*" -Destination $engine -Recurse -Force
    cargo build --release --manifest-path desktop/Cargo.toml
    if ($LASTEXITCODE -ne 0) { throw 'Tauri desktop build failed.' }
    Copy-Item desktop/target/release/gb28181-desktop.exe "$bundle/$name.exe" -Force
    $reported = & "$engine/AnalyzerEngine.exe" --version
    if ($LASTEXITCODE -ne 0 -or $reported -ne $version) { throw 'Portable version check failed.' }
    Copy-Item -LiteralPath 'LICENSE' -Destination $bundle
    Copy-Item -LiteralPath 'docs/WINDOWS.md' -Destination "$bundle/README-Windows.md"
    $archive = Join-Path $output "gb28181-analyzer-windows-x64-v$version.zip"
    Compress-Archive -LiteralPath $bundle -DestinationPath $archive -Force
    $digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "$digest  $(Split-Path -Leaf $archive)"
    Write-Output $archive
} finally {
    Pop-Location
}
