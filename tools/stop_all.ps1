# 一键关闭所有直播相关进程（自动申请管理员权限）
#
# 用法一：双击桌面「关闭直播」快捷方式
# 用法二：powershell -NoProfile -ExecutionPolicy Bypass -File D:\dafeiyu-ai-vtuber\tools\stop_all.ps1
# 参数：
#   -KeepCompanion  保留「直播伴侣」不关（默认一起关掉）
#   -NoElevate      不自动提权（当前窗口本身是管理员时可加，避免弹二次确认）

param(
  [switch]$KeepCompanion,
  [switch]$NoElevate
)

# ---------- 0) 自动提权 ----------
if (-not $NoElevate) {
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $isAdmin) {
    Write-Host "需要管理员权限（直播伴侣/弹幕程序是管理员进程），正在申请……"
    $argLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -NoElevate'
    if ($KeepCompanion) { $argLine += ' -KeepCompanion' }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argLine
    exit 0
  }
}

$ErrorActionPreference = 'Continue'
$Root = 'D:\dafeiyu-ai-vtuber'
$Log  = Join-Path $Root 'out\stop_all.log'

function W($m) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
  Write-Host $line
  try { Add-Content -Path $Log -Value $line -Encoding UTF8 } catch {}
}

W "=== 开始关闭直播进程 ==="

# ---------- 1) OBS：先停虚拟摄像头，再关窗口 ----------
$obs = Get-Process obs64 -ErrorAction SilentlyContinue
if ($obs) {
  $stopper = Join-Path $Root 'out\_obs_stopcam.py'
  if (Test-Path $stopper) {
    try { & (Join-Path $Root '.venv\Scripts\python.exe') -u $stopper 2>&1 | ForEach-Object { W "  [obs] $_" } }
    catch { W "  [obs] 停虚拟摄像头失败：$_" }
  }
  $obs | ForEach-Object { [void]$_.CloseMainWindow() }
  Start-Sleep -Seconds 3
  $left = Get-Process obs64 -ErrorAction SilentlyContinue
  if ($left) {
    $left | Stop-Process -Force -ErrorAction SilentlyContinue
    W "OBS 已强制结束"
  } else { W "OBS 已正常退出" }
} else { W "OBS 未在运行" }

# ---------- 2) 值守脚本 ----------
$sitters = Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*sitter.ps1*' -and $_.ProcessId -ne $PID }
foreach ($s in $sitters) { Stop-Process -Id $s.ProcessId -Force -ErrorAction SilentlyContinue; W "停止值守 pid=$($s.ProcessId)" }
if (-not $sitters) { W "值守脚本未在运行" }

# ---------- 3) python 服务 ----------
$pats = @('main.py', 'paint_service.py', 'caption', 'llm_fallback', 'proxy', 'live2d_server')
$killed = 0
foreach ($p in (Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue)) {
  if ($p.ProcessId -eq $PID) { continue }
  $cmd = [string]$p.CommandLine
  foreach ($pat in $pats) {
    if ($cmd -like "*$pat*") {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      W "停止 python pid=$($p.ProcessId)  [$pat]"
      $killed++
      break
    }
  }
}
if ($killed -eq 0) { W "没有匹配到 python 直播服务" }

# ---------- 4) 弹幕监听 ----------
$bar = Get-Process WssBarrageServer -ErrorAction SilentlyContinue
if ($bar) {
  $bar | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue; W "停止弹幕监听 pid=$($_.Id)" }
  Start-Sleep -Seconds 1
  $bar2 = Get-Process WssBarrageServer -ErrorAction SilentlyContinue
  if ($bar2) { W "弹幕监听仍未退出（可能权限不足）：pid=$($bar2.Id -join ',')" }
} else { W "弹幕监听未在运行" }

# ---------- 5) 直播伴侣 ----------
if ($KeepCompanion) {
  W "按要求保留直播伴侣"
} else {
  $lc = Get-Process '直播伴侣' -ErrorAction SilentlyContinue
  if ($lc) {
    W "关闭直播伴侣（$($lc.Count) 个进程）。若它正在直播，退出会让直播立刻中断"
    $lc | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $still = @(Get-Process '直播伴侣' -ErrorAction SilentlyContinue).Count
    if ($still -eq 0) { W "直播伴侣已退出" } else { W "直播伴侣还剩 $still 个进程" }
  } else { W "直播伴侣未在运行" }
}

# ---------- 6) 端口核对 ----------
Start-Sleep -Seconds 1
$alive = @()
foreach ($port in 8082, 12345, 5500, 8787, 8888, 8899, 4455) {
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($c) { $alive += "$port(pid $($c[0].OwningProcess))" }
}
if ($alive.Count -eq 0) { W "全部端口已释放：8082/12345/5500/8787/8888/8899/4455" }
else { W "仍在监听：$($alive -join ', ')" }
W "=== 完成 ==="
