# =============================================================================
#  旧仓库启动提示（tcms-ai-platform 已并入 monorepo：tcms-agent）
#
#  为什么把原来的 start.bat 换成这个"只提示、不启动"的壳：
#  这台机器上同时有多份能启动的副本（monorepo 本体 / 旧仓库 / 发布包），
#  它们的界面长得像、默认端口还都是 8000。于是会出现一种很难自查的误会——
#  双击了旧副本，看到的是 2026-09-12 的界面，却以为"新改动没生效"。
#  与其让人去猜，不如让旧入口自己把话说清楚。
#
#  编码：本文件必须为 UTF-8 with BOM（PowerShell 5.1 读无 BOM 的 .ps1 会按 ANSI
#  解析，中文会变乱码）。这是本项目的既有纪律，见 tcms-agent 的分发卫生测试。
# =============================================================================

$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
$New = Join-Path (Split-Path $Root -Parent) 'tcms-agent\start.bat'

Write-Host ''
Write-Host '  ============================================================' -ForegroundColor Yellow
Write-Host '   这个目录是【旧仓库】tcms-ai-platform，已经停止维护。' -ForegroundColor Yellow
Write-Host '  ============================================================' -ForegroundColor Yellow
Write-Host ''
Write-Host '  它启动的界面停留在 2026-09-12，缺少后续的改进：'
Write-Host '    · 运行期间的白盒步骤流（自由目标路径也实时展示真实步骤）'
Write-Host '    · 模型选择器与「测试连接」自检'
Write-Host '    · 全站界面重构（两栏工作台 / 层级治理 / 错误兜底）'
Write-Host ''
Write-Host '  新仓库在这里：'
Write-Host "    $New" -ForegroundColor Green
Write-Host ''
Write-Host '  提示：新版界面侧栏底部会显示「界面 <构建时间> · <产物哈希>」，'
Write-Host '        用它就能确认自己打开的是哪一版，不用再猜。'
Write-Host ''

if (Test-Path $New) {
    $ans = Read-Host '  现在就用新仓库启动吗？(Y/N)'
    if ($ans -match '^[Yy]') {
        Start-Process -FilePath $New
        Write-Host '  已在另一个窗口启动新仓库。' -ForegroundColor Green
        Start-Sleep -Seconds 2
    } else {
        Write-Host '  已取消。旧版启动器保留在 start.old.bat（不推荐）。'
    }
} else {
    Write-Host '  [!] 没找到新仓库的启动脚本，请手动打开：' -ForegroundColor Red
    Write-Host '      E:\DSHworkplace\objects\tcms-agent\start.bat' -ForegroundColor Red
}

Write-Host ''
Read-Host '  按回车键退出'
