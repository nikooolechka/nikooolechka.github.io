# ЯМ диагностика — печатает, каким способом видна цена на этом компьютере
$ErrorActionPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$u='https://market.yandex.ru/card/detskiye-vlazhnyye-salfetki-s-ksilitom-as-farm-20-sht-dlya-zubov-i-polosti-rta/102196144368'
$ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'
$H=@{ 'User-Agent'=$ua; 'Accept'='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'; 'Accept-Language'='ru-RU,ru;q=0.9'; 'Cookie'='yandex_gid=213' }

Write-Host "===== A) pryamoy zapros (bez brauzera) ====="
try{
  $r=Invoke-WebRequest -Uri $u -Headers $H -UseBasicParsing -TimeoutSec 30
  $c=[string]$r.Content
  $cap = $c -match 'showcaptcha|SmartCaptcha|checkbox-captcha|Вы не робот|используете VPN'
  Write-Host ("len={0}  captcha={1}" -f $c.Length,$cap)
  if($c -match '<title>(.*?)</title>'){Write-Host ("title: {0}" -f $matches[1])}
  $pr=([regex]::Matches($c,'"price"\s*:\s*"?(\d{2,7})')|%{$_.Groups[1].Value}|select -Unique) -join ', '
  Write-Host ("ld+json price: [{0}]" -f $pr)
  $any=([regex]::Matches($c,'(\d[\d\s]{1,7})\s*(?:&#8381;|₽|руб)')|%{($_.Groups[1].Value -replace '\s','')}|select -Unique -First 8) -join ', '
  Write-Host ("chisla pered rub: [{0}]" -f $any)
}catch{ Write-Host ("ERR A: {0}" -f $_.Exception.Message) }

Write-Host ""
Write-Host "===== B) Edge headless, dolshe zhdat ====="
try{
  $e=@("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe","${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe")|?{Test-Path $_}|select -First 1
  $h=(& $e --headless=new --disable-gpu --no-first-run --user-data-dir=$env:TEMP\ymt2 --virtual-time-budget=25000 --run-all-compositor-stages-before-draw --lang=ru-RU --dump-dom $u 2>$null | Out-String)
  $cap = $h -match 'showcaptcha|SmartCaptcha|Вы не робот|используете VPN'
  Write-Host ("len={0}  captcha={1}" -f $h.Length,$cap)
  $pr=([regex]::Matches($h,'"price"\s*:\s*"?(\d{2,7})')|%{$_.Groups[1].Value}|select -Unique) -join ', '
  Write-Host ("ld+json price: [{0}]" -f $pr)
}catch{ Write-Host ("ERR B: {0}" -f $_.Exception.Message) }
Write-Host ""
Write-Host "===== GOTOVO ====="
