# pdf-translate 一键安装脚本
# 自动安装：uv（Python 运行时）+ Python 3.12 + MinerU + pandoc
# 用法：右键「使用 PowerShell 运行」，或在终端执行 setup.bat

param(
    [switch]$PreloadModels
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$SkillDir = $PSScriptRoot
$InstallDir = Join-Path $HOME '.pdf-translate'
$VenvDir = Join-Path $InstallDir '.venv'
$ToolsDir = Join-Path $InstallDir 'tools'
$PandocVer = '3.12.1'
$UvUrl = 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'
$PandocUrl = "https://github.com/jgm/pandoc/releases/download/$PandocVer/pandoc-$PandocVer-windows-x86_64.zip"

Write-Host ''
Write-Host '=== pdf-translate 安装程序 ===' -ForegroundColor Cyan
Write-Host "安装位置: $InstallDir"
Write-Host ''

New-Item -ItemType Directory -Force -Path $InstallDir, $ToolsDir | Out-Null

# --- 1. uv ---
$UvExe = Join-Path $ToolsDir 'uv\uv.exe'
if (-not (Test-Path $UvExe)) {
    Write-Host '[1/4] 下载 uv ...'
    $zip = Join-Path $env:TEMP 'uv-windows.zip'
    Invoke-WebRequest -Uri $UvUrl -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $ToolsDir 'uv') -Force
    Remove-Item $zip -Force
}
Write-Host '      uv 就绪' -ForegroundColor DarkGray

# --- 2. Python 环境 ---
$Py = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $Py)) {
    Write-Host '[2/4] 创建 Python 环境（自动下载 CPython 3.12）...'
    & $UvExe venv $VenvDir --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python 环境创建失败' }
}
Write-Host '      Python 就绪' -ForegroundColor DarkGray

# --- 3. MinerU ---
$MineruKit = Join-Path $VenvDir 'Scripts\mineru-kit.exe'
if (-not (Test-Path $MineruKit)) {
    Write-Host '[3/4] 安装 MinerU（约 600 MB，需要几分钟）...'
    $Wheel = Join-Path $SkillDir 'vendor\mineru-4.0.12-py3-none-any.whl'
    if (Test-Path $Wheel) {
        Write-Host '      使用仓库内置版本 4.0.12'
        & $UvExe pip install --python $Py $Wheel
    } else {
        & $UvExe pip install --python $Py 'mineru>=4.0,<5'
    }
    if ($LASTEXITCODE -ne 0) { throw 'MinerU 安装失败' }
}
Write-Host '      MinerU 就绪' -ForegroundColor DarkGray

# --- 4. pandoc ---
$PandocDir = Join-Path $ToolsDir 'pandoc'
$PandocExe = Join-Path $PandocDir "pandoc-$PandocVer\pandoc.exe"
if (-not (Test-Path $PandocExe)) {
    Write-Host '[4/4] 下载 pandoc ...'
    $zip = Join-Path $env:TEMP 'pandoc-windows.zip'
    Invoke-WebRequest -Uri $PandocUrl -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $PandocDir -Force
    Remove-Item $zip -Force
}
Write-Host '      pandoc 就绪' -ForegroundColor DarkGray

# --- 写配置 ---
$Edge = $null
$browsers = @(
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Google\Chrome\Application\chrome.exe'
)
foreach ($b in $browsers) {
    if (Test-Path $b) { $Edge = $b; break }
}

$config = [ordered]@{
    mineru_kit = $MineruKit
    pandoc     = $PandocExe
    edge       = $Edge
}
$config | ConvertTo-Json | Set-Content -Path (Join-Path $SkillDir 'config.json') -Encoding UTF8

if ($PreloadModels) {
    Write-Host ''
    Write-Host '预下载模型（约 2 GB，请耐心等待）...'
    & $MineruKit models download --tier basic --small-backend onnx --vlm-engine llama-cpp --source huggingface
}

Write-Host ''
Write-Host '安装完成' -ForegroundColor Green
Write-Host ''
Write-Host '下一步：'
Write-Host '  1. 把整个仓库目录放到技能目录下，例如：'
Write-Host "     $HOME\.agents\skills\pdf-translate\"
Write-Host '  2. 对 AI agent 说「把这篇文章翻译成中文」并附上 PDF 路径'
Write-Host ''
Write-Host '手动运行：'
Write-Host "  `"$Py`" `"$SkillDir\scripts\prepare.py`" 论文.pdf"
Write-Host "  `"$Py`" `"$SkillDir\scripts\check.py`"   论文_translate"
Write-Host "  `"$Py`" `"$SkillDir\scripts\build.py`"   论文_translate"
Write-Host ''
if (-not $Edge) {
    Write-Host '注意：没有找到 Edge 或 Chrome，生成 PDF 需要其中之一。' -ForegroundColor Yellow
}
Write-Host '首次解析会自动下载 MinerU 模型（约 2 GB）。' -ForegroundColor DarkGray
