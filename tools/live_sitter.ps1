# 夜间值守：崩了就拉起来，异常就记下来
# 每 45 秒检查一次，写 out\sitter.log
$ErrorActionPreference = 'Continue'
$root = 'D:\dafeiyu-ai-vtuber'
Set-Location $root
$log = Join-Path $root 'out\sitter.log'
$stateFile = Join-Path $root 'out\sitter_state.json'

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
}

function PortUp($p) {
    return (@(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue).Count -gt 0)
}

function Start-Main {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $env:DEEPSEEK_API_KEY = (Get-Item 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment').GetValue('DEEPSEEK_API_KEY', '', 'DoNotExpandEnvironmentNames')
    $env:DASHSCOPE_KEY = (Get-Item 'HKCU:\Environment').GetValue('DASHSCOPE_KEY', '', 'DoNotExpandEnvironmentNames')
    $env:Path = $env:Path + ';' + (Join-Path $root 'tools\ffmpeg\bin')
    $py = Join-Path $root '.venv\Scripts\python.exe'
    $out = Join-Path $root 'out\main.stdout.txt'
    $err = Join-Path $root 'out\main.stderr.txt'
    Start-Process -FilePath $py -ArgumentList '-u', 'main.py' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err | Out-Null
    Write-Log "main.py 已重启"
}

Write-Log "sitter started"

$restarts = 0
while ($true) {
    try {
        $alive = @{
            main = PortUp 8082
            live2d = PortUp 12345
            caption = PortUp 5500
            proxy = PortUp 8787
            danmaku = PortUp 8888
            obs = PortUp 4455
        }
        $alive | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8

        if (-not $alive.main -or -not $alive.live2d) {
            if ($restarts -lt 12) {
                Write-Log "主程序挂了（8082=$($alive.main) 12345=$($alive.live2d)），尝试重启第 $($restarts + 1) 次"
                Start-Main
                $restarts++
                Start-Sleep -Seconds 25
            } else {
                Write-Log "主程序已重启 12 次，暂停重启，等人工处理"
            }
        }
        if (-not $alive.proxy) { Write-Log "警告：8787 大模型代理没在跑，点歌/聊天会失败" }
        if (-not $alive.caption) { Write-Log "警告：5500 字幕服务没在跑" }
        if (-not $alive.danmaku) { Write-Log "警告：8888 弹幕监听没在跑" }
        if (-not $alive.obs) { Write-Log "警告：OBS 4455 没在跑，画面会黑" }

        # 每小时记一次概况，方便早上回看
        $minute = (Get-Date).Minute
        if ($minute -eq 0) {
            $stats = 'n/a'
            try { $stats = (Invoke-WebRequest 'http://127.0.0.1:8787/stats' -UseBasicParsing -TimeoutSec 5).Content } catch {}
            Write-Log "整点概况 端口=$($alive | ConvertTo-Json -Compress) token=$stats"
        }
    } catch {
        Write-Log "sitter 自身异常：$($_.Exception.Message)"
    }
    Start-Sleep -Seconds 45
}
