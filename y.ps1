# ЯМ: тянет карточку прямым запросом и печатает контекст вокруг цен (для точной привязки)
$ErrorActionPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$u='https://market.yandex.ru/card/detskiye-vlazhnyye-salfetki-s-ksilitom-as-farm-20-sht-dlya-zubov-i-polosti-rta/102196144368'
$ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'
$H=@{ 'User-Agent'=$ua; 'Accept'='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'; 'Accept-Language'='ru-RU,ru;q=0.9'; 'Cookie'='yandex_gid=213' }

$r=Invoke-WebRequest -Uri $u -Headers $H -UseBasicParsing -TimeoutSec 40
$c=[string]$r.Content
Write-Host ("len={0}" -f $c.Length)
Write-Host "--- kontekst vokrug cen ---"
foreach($n in '602','621','1800'){
  $i=0; $cnt=0
  while((($i=$c.IndexOf($n,$i)) -ge 0) -and ($cnt -lt 4)){
    $s=[math]::Max(0,$i-60); $len=[math]::Min(78,$c.Length-$s)
    $frag=($c.Substring($s,$len) -replace '\s+',' ')
    Write-Host ("["+$n+"] "+$frag)
    $i+=$n.Length; $cnt++
  }
}
Write-Host "--- ld+json ---"
$m=[regex]::Match($c,'application/ld\+json">(.*?)</script>',[Text.RegularExpressions.RegexOptions]::Singleline)
if($m.Success){ $j=$m.Groups[1].Value; if($j.Length -gt 450){$j=$j.Substring(0,450)}; Write-Host $j }
Write-Host "--- GOTOVO ---"
