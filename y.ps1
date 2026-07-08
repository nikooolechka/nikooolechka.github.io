# ЯМ: печатает все ценовые ключи вида "...Price":{"amount":{"intPart":N}}
$ErrorActionPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$u='https://market.yandex.ru/card/detskiye-vlazhnyye-salfetki-s-ksilitom-as-farm-20-sht-dlya-zubov-i-polosti-rta/102196144368'
$ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'
$H=@{ 'User-Agent'=$ua; 'Accept'='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'; 'Accept-Language'='ru-RU,ru;q=0.9'; 'Cookie'='yandex_gid=213' }

$r=Invoke-WebRequest -Uri $u -Headers $H -UseBasicParsing -TimeoutSec 40
$c=[string]$r.Content
Write-Host ("len={0}" -f $c.Length)

Write-Host "--- kluchi ...Price -> intPart ---"
$seen=@{}
$mm=[regex]::Matches($c,'"([A-Za-z]+)":\{"amount":\{"intPart":(\d+)')
foreach($x in $mm){
  $k="{0}={1}" -f $x.Groups[1].Value,$x.Groups[2].Value
  if(-not $seen.ContainsKey($k)){ $seen[$k]=1; Write-Host $k }
}
Write-Host ("vsego unikalnyh: {0}" -f $seen.Count)

Write-Host "--- lyubye intPart (60 znakov do) ---"
$s2=@{}
$m2=[regex]::Matches($c,'.{55}"intPart":(\d{2,7})')
$n=0
foreach($x in $m2){
  if($n -ge 14){break}
  $frag=($x.Value -replace '\s+',' ')
  if(-not $s2.ContainsKey($frag)){ $s2[$frag]=1; Write-Host $frag; $n++ }
}
Write-Host "--- GOTOVO ---"
