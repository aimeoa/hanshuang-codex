# Hanshuang-Codex Release Build Script (PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File .\build-release.ps1
# 产物: dist\寒霜破甲工具\寒霜破甲工具.exe

Write-Host "=== Hanshuang-Codex Release Build ===" -ForegroundColor Cyan

# 1. 安装依赖
Write-Host "[1/3] Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt pyinstaller -q
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed" -ForegroundColor Red; exit 1 }

# 2. 构建 PyInstaller release bundle
Write-Host "[2/3] Building PyInstaller release bundle..." -ForegroundColor Yellow
pyinstaller fj_tool.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Host "pyinstaller build failed" -ForegroundColor Red; exit 1 }

# 3. 列出产物
Write-Host "[3/3] Build artifacts:" -ForegroundColor Yellow
$bundleDir = "dist\寒霜破甲工具"
if (Test-Path $bundleDir) {
    Get-ChildItem -Path $bundleDir -Recurse -File | ForEach-Object {
        Write-Host "  $($_.FullName)" -ForegroundColor Green
    }
} else {
    Write-Host "  Bundle directory not found: $bundleDir" -ForegroundColor Red
}

Write-Host "=== Build complete ===" -ForegroundColor Cyan
