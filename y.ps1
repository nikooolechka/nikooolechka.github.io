# ЯМ: тянет карточку прямым запросом (РФ-IP этого компа) и выгружает HTML для разбора
$ErrorActionPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$u='https://market.yandex.ru/card/detskiye-vlazhnyye-salfetki-s-ksilitom-as-farm-20-sht-dlya-zubov-i-polosti-rta/102196144368'
$ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'
$H=@{ 'User-Agent'=$ua; 'Accept'='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'; 'Accept-Language'='ru-RU,ru;q=0.9'; 'Cookie'='yandex_gid=213' }

try{
  $r=Invoke-WebRequest -Uri $u -Headers $H -UseBasicParsing -TimeoutSec 40
  $c=[string]$r.Content
  Write-Host ("len={0}" -f $c.Length)
  $p=$env:TEMP+'\ym.html'
  [IO.File]::WriteAllText($p,$c,[Text.Encoding]::UTF8)
  # выгрузка на 0x0.st (встроенный curl.exe в Windows 10)
  $url = (& curl.exe -s -F ("file=@"+$p) https://0x0.st) 2>$null
  Write-Host "======================================"
  Write-Host ("SSYLKA: {0}" -f $url)
  Write-Host "======================================"
}catch{ Write-Host ("ERR: {0}" -f $_.Exception.Message) }
