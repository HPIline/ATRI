<#
.SYNOPSIS
    无人值守地跑一遍 A.T.R.I. 的 Webots 联调。

.DESCRIPTION
    Webots 的 --batch 跑完之后不会自己退出：控制器按 --exit-on-done 退出了，
    但仿真还在继续，Webots 进程一直挂着，控制台输出也一直不 flush。
    所以这个脚本负责：后台启动 Webots → 等控制器写出联调报告 JSON →
    结束 Webots → 打印结论。退出码 0 表示五项任务全过，2 表示没过。

.EXAMPLE
    pwsh -File webots/tools/run_webots_batch.ps1

.EXAMPLE
    pwsh -File webots/tools/run_webots_batch.ps1 -Mapping joint_mapping_nao.json
#>
[CmdletBinding()]
param(
    [string]$World,
    [string]$Report,
    [string]$Log,
    [string]$Webots,
    [string]$Mapping,
    [int]$TimeoutSec = 300
)

$ErrorActionPreference = 'Stop'

# $PSScriptRoot = <repo>/webots/tools
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $World)  { $World  = Join-Path $repoRoot 'webots\worlds\atri_22dof.wbt' }
if (-not $Report) { $Report = Join-Path $repoRoot 'atri_report.json' }
if (-not $Log)    { $Log    = Join-Path $repoRoot 'atri_console.log' }

if (-not $Webots) {
    $cmd = Get-Command webots -ErrorAction SilentlyContinue
    if ($cmd) {
        $Webots = $cmd.Source
    } else {
        $Webots = @(
            'C:\Program Files\Webots\msys64\mingw64\bin\webots.exe',
            'C:\Program Files (x86)\Webots\msys64\mingw64\bin\webots.exe'
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
}
if (-not $Webots -or -not (Test-Path $Webots)) {
    Write-Host "找不到 webots.exe，请用 -Webots 指定路径。" -ForegroundColor Red
    exit 3
}
if (-not (Test-Path $World)) {
    Write-Host "找不到世界文件: $World" -ForegroundColor Red
    exit 3
}

Remove-Item $Report, $Log -Force -ErrorAction SilentlyContinue

# Webots 没有向控制器透传命令行参数的机制，只能靠环境变量
$env:ATRI_WEBOTS_EXIT_ON_DONE = '1'
$env:ATRI_WEBOTS_REPORT = $Report
$env:ATRI_WEBOTS_LOG = $Log
if ($Mapping) { $env:ATRI_WEBOTS_MAPPING = $Mapping }

Write-Host "Webots  : $Webots"
Write-Host "世界    : $World"
Write-Host "报告    : $Report"
Write-Host "日志    : $Log"
Write-Host ("-" * 60)

Get-Process webots -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

$proc = Start-Process -FilePath $Webots `
    -ArgumentList '--batch', '--mode=fast', '--no-rendering', '--minimize', '--stdout', '--stderr', $World `
    -PassThru

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $Report) { break }
    if ($proc.HasExited) { break }
    Start-Sleep -Milliseconds 500
}

$appeared = Test-Path $Report
# 给控制器一点时间把日志 flush 完
Start-Sleep -Seconds 2
if (-not $proc.HasExited) {
    try { $proc.Kill() } catch { }
}
Get-Process webots -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if (-not $appeared) {
    Write-Host "超时 ${TimeoutSec}s，控制器没有写出报告——仿真没跑起来或控制器没启动。" -ForegroundColor Red
    if (Test-Path $Log) {
        Write-Host "控制台日志尾部:" -ForegroundColor Yellow
        Get-Content $Log -Tail 40
    }
    exit 2
}

$result = Get-Content $Report -Raw -Encoding UTF8 | ConvertFrom-Json

Write-Host ""
Write-Host ("=" * 60)
Write-Host ("Webots 闭环: {0}/{1} 项任务通过" -f $result.passed, $result.total)
Write-Host ("  关节绑定  : {0}/{1}（映射应绑定 {2}，未绑定 {3} 个）" -f $result.bound_joints, $result.expected_joints, $result.mapped_joints, $result.unbound_joints.Count)
Write-Host ("  有行程关节: {0}/{1}" -f $result.moved_joints, $result.expected_joints)
Write-Host ("  仿真时间  : {0} s（{1} 步，墙钟 {2} s）" -f $result.sim_seconds, $result.sim_steps, $result.wall_seconds)
Write-Host ("  报告      : {0}" -f $Report)
Write-Host ("=" * 60)

$zero = $result.joint_travel_deg.PSObject.Properties | Where-Object { $_.Value -le 1.0 }
if ($zero) {
    Write-Host "这轮没有任何行程的关节（当前任务卡用不到的自由度）:" -ForegroundColor Yellow
    foreach ($z in $zero) { Write-Host ("  {0}" -f $z.Name) }
}

# 绑定判据：实际绑定数 == 映射中非空条目数，且 > 0。
# 映射留空 = 该机型没有这个自由度（Nao 的 4 个），不算失败；
# 非空条目没绑上（电机改名、世界损坏）= 世界与映射不匹配，任务跑得再顺也不算通过。
$bindingOk = ($result.bound_joints -gt 0) -and ($result.bound_joints -eq $result.mapped_joints)
if (-not $bindingOk) {
    Write-Host ("绑定不完整：映射应绑定 {0} 个关节，实际绑定 {1} 个，联调结果不可信。" -f $result.mapped_joints, $result.bound_joints) -ForegroundColor Red
}

if ($result.passed -eq $result.total -and $result.total -gt 0 -and $result.simulation_alive -and $bindingOk) {
    Write-Host "联调通过。" -ForegroundColor Green
    exit 0
}

Write-Host "联调未通过。" -ForegroundColor Red
exit 2
