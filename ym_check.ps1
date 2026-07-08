# ЯМ ПРОВЕРКА (только на экран, в таблицу НИЧЕГО не пишет).
# Берёт список карточек, снимает цены, печатает до СПП / с СПП / СПП. Запись — отдельно, после подтверждения.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$cfg = Get-Content "$env:USERPROFILE\asfarm\ym.cfg" -Raw | ConvertFrom-Json
$proxy=$cfg.proxy; $key=$cfg.key
$ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'
$H=@{ 'User-Agent'=$ua; 'Accept'='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'; 'Accept-Language'='ru-RU,ru;q=0.9'; 'Cookie'='yandex_gid=213' }

$targets = (Invoke-RestMethod -Uri "$proxy/ym/targets?k=$key" -TimeoutSec 60).targets
Write-Host ("=== PROVERKA (bez zapisi). Kartochek: {0} ===" -f $targets.Count)
foreach($t in $targets){
  $o=$null;$a=$null;$note=''
  try{
    $c=[string](Invoke-WebRequest -Uri $t.url -Headers $H -UseBasicParsing -TimeoutSec 60).Content
    if($c -match 'showcaptcha|SmartCaptcha|Вы не робот|используете VPN'){ $note='KAPCHA' }
    else{
      $mo=[regex]::Match($c,'"oldPrice":\{"amount":\{"intPart":(\d+)');    if($mo.Success){$o=[int]$mo.Groups[1].Value}
      $ma=[regex]::Match($c,'"actualPrice":\{"amount":\{"intPart":(\d+)'); if($ma.Success){$a=[int]$ma.Groups[1].Value}
    }
  }catch{ $note=("oshibka: "+$_.Exception.Message) }
  $do = if($o){$o}else{$a}
  $spp='0%'
  if($do -and $a -and $do -gt $a){ $spp = ("{0:N2}%" -f ((1-$a/$do)*100)) }
  Write-Host ("  {0,-24} do SPP={1,-6} s SPP={2,-6} SPP={3,-7} {4}" -f $t.article,$do,$a,$spp,$note)
  Start-Sleep -Seconds 3
}
Write-Host "=== GOTOVO (v tablicu nichego ne zapisano) ==="
