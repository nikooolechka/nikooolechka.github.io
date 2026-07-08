# ЯМ: снимает цены с market.yandex.ru (РФ-IP этого компа) и шлёт в облачный приёмник.
# Настройки (адрес приёмника + ключ) лежат локально в %USERPROFILE%\asfarm\ym.cfg
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$cfg = Get-Content "$env:USERPROFILE\asfarm\ym.cfg" -Raw | ConvertFrom-Json
$proxy=$cfg.proxy; $key=$cfg.key
$ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'
$H=@{ 'User-Agent'=$ua; 'Accept'='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'; 'Accept-Language'='ru-RU,ru;q=0.9'; 'Cookie'='yandex_gid=213' }

$targets = (Invoke-RestMethod -Uri "$proxy/ym/targets?k=$key" -TimeoutSec 60).targets
Write-Host ("kartochek YM: {0}" -f $targets.Count)
$results=@()
foreach($t in $targets){
  $o=$null;$a=$null;$ini=$null;$ok=$false;$note=''
  try{
    $c=[string](Invoke-WebRequest -Uri $t.url -Headers $H -UseBasicParsing -TimeoutSec 60).Content
    if($c -match 'showcaptcha|SmartCaptcha|Вы не робот|используете VPN'){ $note='captcha' }
    else{
      $mo=[regex]::Match($c,'"oldPrice":\{"amount":\{"intPart":(\d+)');    if($mo.Success){$o=[int]$mo.Groups[1].Value}
      $ma=[regex]::Match($c,'"actualPrice":\{"amount":\{"intPart":(\d+)'); if($ma.Success){$a=[int]$ma.Groups[1].Value}
      $mi=[regex]::Match($c,'"initialPrice":\{"amount":\{"intPart":(\d+)');if($mi.Success){$ini=[int]$mi.Groups[1].Value}
      if($a -or $o){ $ok=$true } else { $note='net ceny v HTML' }
    }
  }catch{ $note=("oshibka: "+$_.Exception.Message) }
  $do = if($o){$o}else{$a}
  Write-Host ("  {0}: doSPP={1} sSPP={2} ok={3} {4}" -f $t.article,$do,$a,$ok,$note)
  $results += @{article=$t.article; oldPrice=$o; actualPrice=$a; initialPrice=$ini; ok=$ok; note=$note}
  Start-Sleep -Seconds 3
}
# в массив JSON (устойчиво даже для 1 элемента)
$json = "[" + (($results | ForEach-Object { $_ | ConvertTo-Json -Depth 5 -Compress }) -join ",") + "]"
$resp = Invoke-RestMethod -Uri "$proxy/ym/prices?k=$key" -Method Post -Body $json -ContentType 'application/json' -TimeoutSec 120
Write-Host ("--- zapisano v tablicu: {0} ---" -f $resp.count)
if($resp.failed){ foreach($f in $resp.failed){ Write-Host ("  NE OK: {0} {1}" -f $f.article,$f.note) } }
Write-Host "GOTOVO"
