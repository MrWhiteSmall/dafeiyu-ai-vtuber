$ErrorActionPreference = 'Continue'
$dir = 'D:\dafeiyu-ai-vtuber\out'
$log = Join-Path $dir 'beian_watch.log'
$alert = Join-Path $dir 'beian_alert.txt'
$url = 'https://vasset.douyin.com/v/copyright/list'

function Note($msg) {
  $line = "[{0}] {1}" -f (Get-Date).ToString('MM-dd HH:mm:ss'), $msg
  Add-Content -Path $log -Value $line -Encoding UTF8
}

Note "watcher started, interval 10 min, url=$url"

while ($true) {
  $seq = 'w' + (Get-Date).ToString('HHmmss')
  $payload = '{"seq":"' + $seq + '","url":"' + $url + '","wait":6000,"eval":"(document.body.innerText||\"\").slice(0,600)"}'
  Remove-Item (Join-Path $dir 'web_result.json') -ErrorAction SilentlyContinue
  [System.IO.File]::WriteAllText((Join-Path $dir 'web_cmd.json'), $payload, (New-Object System.Text.UTF8Encoding($false)))

  $got = $null
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 800
    if (Test-Path (Join-Path $dir 'web_result.json')) {
      try {
        $r = Get-Content (Join-Path $dir 'web_result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($r.seq -eq $seq) { $got = $r; break }
      } catch { }
    }
  }

  if ($null -eq $got) {
    Note "check timeout / no result"
  } else {
    $txt = ($got.texts -join ' | ')
    if ([string]::IsNullOrWhiteSpace($txt)) { $txt = '(empty)' }
    Note "status => $txt"
    if ($txt -match '通过|驳回|不通过|未通过|失败') {
      Set-Content -Path $alert -Value ("[{0}] {1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $txt) -Encoding UTF8
      Note "!!! 状态变化，已写 alert 文件"
    }
  }

  Start-Sleep -Seconds 600
}
