# 一键部署到 Hugging Face Spaces（Gradio SDK 免费版，实际运行 FastAPI）
# 用法: .\deploy-hf.ps1 -HfUser <HF用户名> -HfToken <hf_令牌> [-SpaceName ai-stock-research]
param(
    [Parameter(Mandatory=$true)][string]$HfUser,
    [Parameter(Mandatory=$true)][string]$HfToken,
    [string]$SpaceName = 'ai-stock-research'
)
$ErrorActionPreference = 'Stop'

$src = $PSScriptRoot
$tmp = Join-Path $env:TEMP ('hf-space-' + $SpaceName)

Write-Host '==> 克隆 Space ...'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
$repoUrl = 'https://' + $HfUser + ':' + $HfToken + '@huggingface.co/spaces/' + $HfUser + '/' + $SpaceName
git clone $repoUrl $tmp 2>&1 | Out-Null
if (-not (Test-Path (Join-Path $tmp '.git'))) { throw '克隆失败：检查用户名/令牌/Space(Gradio类型) 是否正确' }

Write-Host '==> 同步项目文件 ...'
$exclude = @('.git', 'vendor', '.cache', '.env', 'deploy-hf.ps1', 'render.yaml')
Get-ChildItem $src -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $tmp $_.Name) -Recurse -Force
}

# README 前加 HF Space frontmatter（Gradio SDK + 端口 7860）
$readmePath = Join-Path $tmp 'README.md'
$readme = Get-Content $readmePath -Raw -ErrorAction SilentlyContinue
$nl = [char]10
$front = '---' + $nl + 'title: AI Stock Research' + $nl + 'emoji: chart_increasing' + $nl + 'colorFrom: blue' + $nl + 'colorTo: indigo' + $nl + 'sdk: gradio' + $nl + 'app_port: 7860' + $nl + 'pinned: false' + $nl + '---' + $nl + $nl
if ($readme -notmatch '^---') {
    Set-Content $readmePath -Value ($front + $readme) -Encoding UTF8 -NoNewline
}

Write-Host '==> 提交并推送（HF 自动开始构建） ...'
git -C $tmp add -A
git -C $tmp -c user.name='deploy' -c user.email='deploy@local' commit -m 'deploy: AI stock research web app' 2>&1 | Out-Null
git -C $tmp push origin main 2>&1 | Out-Null
Remove-Item $tmp -Recurse -Force   # 清理令牌痕迹

Write-Host ''
Write-Host '推送完成！HF 正在安装依赖并启动（首次约 3-6 分钟）' -ForegroundColor Green
Write-Host ('  Space: https://huggingface.co/spaces/' + $HfUser + '/' + $SpaceName)
Write-Host ('  应用:   https://' + $HfUser + '-' + $SpaceName + '.hf.space')
Write-Host ''
Write-Host '设置 Secrets（必须，否则妙想/研报不可用）:' -ForegroundColor Yellow
Write-Host '  网页: Space -> Settings -> Variables and secrets:'
Write-Host '    EM_API_KEY  = <妙想KEY>'
Write-Host '    LLM_API_KEY = <DeepSeek KEY>'
