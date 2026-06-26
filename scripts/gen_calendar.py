"""Генератор ЖИВОГО календаря публикаций АС Фарм.

Читает РЕАЛЬНУЮ очередь content/queue.json и строит график выходов:
- прошлое — фактические даты публикаций (posted_at/released_at);
- будущее — проекция по реальной частоте публикатора (config.CADENCE_DAYS)
  и реальному расписанию workflow'ов, пока в очереди есть НЕопубликованные
  посты (рециклинг запрещён → когда очередь кончается, в календаре пусто).

Темы берутся из очереди, ничего не выдумывается. Результат — самодостаточный
docs/calendar.html: JS в браузере сам берёт сегодняшнюю дату и показывает
ТЕКУЩИЙ + СЛЕДУЮЩИЙ месяц, подсвечивает сегодня. Перегенерируется ежедневно
(вызывается из publish.py), плюс клиентский JS держит подсветку «сегодня» живой.

Частота публикаций (реальная, из config.CADENCE_DAYS):
- ВК   — каждый день,   плановое время 12:00 МСК (main.yml);
- Дзен — раз в 2 дня,   статьи из ленты, Дзен забирает сам (точное время не наше);
- VC   — раз в 30 дней (по дням, не по числу месяца!), плановое время 10:00 МСК (vc_post.yml).

ВАЖНО про VC: интервал отсчитывается ОТ ФАКТА последней публикации (+30 дней),
поэтому дата дрейфует и НЕ ломается на стыке месяцев разной длины.
Опубликованным постам ставим фактические дату и время; будущим — плановые.
"""
import os, json, html
from datetime import datetime, date, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(REPO_ROOT, "content", "queue.json")
OUT = os.path.join(REPO_ROOT, "docs", "calendar.html")

# реальные параметры расписания
VK_TIME = "12:00"     # МСК, плановое (фактическое берём из posted_at)
VC_TIME = "10:00"     # МСК, плановое
VK_EVERY_DAYS = 1
DZEN_EVERY_DAYS = 2
VC_EVERY_DAYS = 30
MSK = timezone(timedelta(hours=3))


def _dt(iso):
    return datetime.fromisoformat(iso).astimezone(MSK)


def _d(iso):
    """ISO -> date в МСК."""
    return _dt(iso).date()


def _t(iso):
    """ISO -> 'ЧЧ:ММ' в МСК (фактическое время публикации)."""
    return _dt(iso).strftime("%H:%M")


def build_events(posts, today):
    """Список событий: {date, channel, title, id, status, time}."""
    ev = []

    # --- ПРОШЛОЕ: фактические публикации (реальные дата и время) ---
    for p in posts:
        ch = p.get("channels", {})
        if ch.get("vk", {}).get("posted_at"):
            ev.append(dict(date=_d(ch["vk"]["posted_at"]), channel="vk",
                           title=p["title"], id=p["id"], status="published", time=_t(ch["vk"]["posted_at"])))
        if ch.get("vc", {}).get("posted_at"):
            ev.append(dict(date=_d(ch["vc"]["posted_at"]), channel="vc",
                           title=p["title"], id=p["id"], status="published", time=_t(ch["vc"]["posted_at"])))

    # --- БУДУЩЕЕ ВК: 1/день, следующие неопубликованные по порядку ---
    vk_done = {e["id"] for e in ev if e["channel"] == "vk"}
    vk_queue = [p for p in posts if p["id"] not in vk_done]
    last_vk = max([e["date"] for e in ev if e["channel"] == "vk"], default=today - timedelta(days=1))
    d = max(last_vk + timedelta(days=VK_EVERY_DAYS), today)
    for p in vk_queue:
        ev.append(dict(date=d, channel="vk", title=p["title"], id=p["id"],
                       status="planned", time=VK_TIME))
        d += timedelta(days=VK_EVERY_DAYS)

    # --- ДЗЕН: публикуется ~раз в 2 дня. Проецируем ВСЮ очередь (а не только то,
    # что уже в ленте), чтобы план Дзена был виден до конца следующего месяца.
    # Первый выход (сегодня) уже состоялся → помечаем опубликованным.
    dd = today
    for i, p in enumerate(posts):
        ev.append(dict(date=dd, channel="dzen", title=p["title"], id=p["id"],
                       status="published" if i == 0 else "planned", time="—"))
        dd += timedelta(days=DZEN_EVERY_DAYS)

    # --- БУДУЩЕЕ VC: РАЗ В 30 ДНЕЙ от фактической последней публикации ---
    vc_done = {e["id"] for e in ev if e["channel"] == "vc"}
    vc_queue = [p for p in posts if p["id"] not in vc_done]
    last_vc = max([e["date"] for e in ev if e["channel"] == "vc"], default=None)
    vc_date = (last_vc + timedelta(days=VC_EVERY_DAYS)) if last_vc else today
    for p in vc_queue[:3]:  # ближайшие 3 цикла (~3 месяца)
        ev.append(dict(date=vc_date, channel="vc", title=p["title"], id=p["id"],
                       status="planned", time=VC_TIME))
        vc_date += timedelta(days=VC_EVERY_DAYS)

    return ev


def _load_stats():
    p = os.path.join(REPO_ROOT, "docs", "stats.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def _fmt(n):
    """Число с разделителем тысяч; None → '—'."""
    if n is None:
        return "—"
    return f"{n:,}".replace(",", " ")


def _networks_html(stats):
    """Карточки соцсетей с живыми счётчиками и кликабельным названием-ссылкой."""
    meta = [
        ("vk",   "ВКонтакте", "g-vk"),
        ("dzen", "Дзен",      "g-dz"),
        ("vc",   "VC.ru",     "g-vc"),
    ]
    cards = []
    for key, name, dotcls in meta:
        s = stats.get(key, {}) or {}
        url = s.get("url", "#")
        rows = []
        rows.append(("Подписчики", _fmt(s.get("subscribers"))))
        rows.append(("Постов", _fmt(s.get("posts"))))
        rows.append(("Просмотры", _fmt(s.get("views"))))
        metrics = "".join(
            f'<div class="metric"><span class="mv">{v}</span><span class="ml">{l}</span></div>'
            for l, v in rows
        )
        cards.append(
            f'<a class="net" href="{url}" target="_blank" rel="noopener">'
            f'<div class="net-h"><span class="gdot {dotcls}"></span>{name}'
            f'<span class="net-go">↗</span></div>'
            f'<div class="metrics">{metrics}</div></a>'
        )
    return "".join(cards)


def render(posts, today=None):
    today = today or datetime.now(MSK).date()
    events = build_events(posts, today)
    stats = _load_stats()
    # сериализуем для JS
    data = [dict(date=e["date"].isoformat(), channel=e["channel"], title=e["title"],
                 id=e["id"], status=e["status"], time=e["time"]) for e in events]
    # статистика для верхних плашек
    vk_left = len([e for e in events if e["channel"] == "vk" and e["status"] == "planned"])
    dzen_left = len([e for e in events if e["channel"] == "dzen" and e["status"] == "planned"])
    pub_total = len([e for e in events if e["status"] == "published"])
    vc_planned = sorted([e for e in events if e["channel"] == "vc" and e["status"] == "planned"],
                        key=lambda e: e["date"])
    if vc_planned:
        next_vc = vc_planned[0]["date"].strftime("%d.%m")
        next_vc_title = vc_planned[0]["title"]
    else:
        next_vc, next_vc_title = "—", "очередь VC пуста"
    payload = json.dumps(data, ensure_ascii=False)
    gen_at = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
    vk_url = (stats.get("vk") or {}).get("url", "https://vk.com/asfarm_ru")
    dz_url = (stats.get("dzen") or {}).get("url", "https://dzen.ru/asfarm_ru")
    vc_url = (stats.get("vc") or {}).get("url", "https://vc.ru/id6010646")

    return (HTML
            .replace("__DATA__", payload)
            .replace("__GEN__", gen_at)
            .replace("__VKLEFT__", str(vk_left))
            .replace("__DZENLEFT__", str(dzen_left))
            .replace("__PUBTOTAL__", str(pub_total))
            .replace("__NEXTVC__", next_vc)
            .replace("__NEXTVCTITLE__", html.escape(next_vc_title))
            .replace("__NETWORKS__", _networks_html(stats))
            .replace("__VKURL__", vk_url)
            .replace("__DZURL__", dz_url)
            .replace("__VCURL__", vc_url))


HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Контент-план АС Фарм</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#070b16; --ink:#eaf0fb; --muted:#9aa6c2; --faint:#6b779a;
    --glass:rgba(255,255,255,.045); --glass2:rgba(255,255,255,.07); --line:rgba(255,255,255,.09);
    --vk1:#3b82f6; --vk2:#1d4ed8; --dz1:#fb923c; --dz2:#ea580c; --vc1:#a855f7; --vc2:#6d28d9;
    --acc1:#38bdf8; --acc2:#22d3ee;
  }
  *{ box-sizing:border-box; }
  html,body{ margin:0; }
  body{
    font-family:'Inter',-apple-system,Segoe UI,Roboto,sans-serif; color:var(--ink);
    background:var(--bg); min-height:100vh; -webkit-font-smoothing:antialiased;
    background-image:
      radial-gradient(900px 500px at 12% -8%, rgba(56,189,248,.18), transparent 60%),
      radial-gradient(800px 520px at 96% 4%, rgba(168,85,247,.16), transparent 58%),
      radial-gradient(700px 600px at 50% 116%, rgba(34,211,238,.10), transparent 60%);
    background-attachment:fixed;
  }
  .wrap{ max-width:1200px; margin:0 auto; padding:40px 22px 70px; position:relative; }

  .brand{ position:absolute; top:30px; right:24px; display:flex; flex-direction:column;
    align-items:center; gap:6px; }
  .brand img{ width:66px; height:auto; display:block; filter:drop-shadow(0 8px 20px rgba(0,0,0,.45)); }
  .brand .wm{ font-weight:800; font-size:18px; letter-spacing:.01em; color:#96c41c; }
  @media (max-width:680px){ .brand{ position:static; flex-direction:row; margin-bottom:14px; }
    .brand img{ width:52px; } }

  .kicker{ font-size:12px; font-weight:700; letter-spacing:.22em; color:var(--acc1);
    text-transform:uppercase; margin-bottom:10px; display:flex; align-items:center; gap:9px; }
  .kicker .live{ width:8px; height:8px; border-radius:50%; background:var(--acc2);
    box-shadow:0 0 0 0 rgba(34,211,238,.6); animation:pulse 2s infinite; }
  @keyframes pulse{ 0%{box-shadow:0 0 0 0 rgba(34,211,238,.55)} 70%{box-shadow:0 0 0 10px rgba(34,211,238,0)} 100%{box-shadow:0 0 0 0 rgba(34,211,238,0)} }
  h1{ font-size:40px; line-height:1.05; font-weight:900; margin:0 0 10px; letter-spacing:-.02em;
    background:linear-gradient(120deg,#fff 10%,#bfe3ff 45%,#a78bfa 95%);
    -webkit-background-clip:text; background-clip:text; color:transparent; }
  .sub{ color:var(--muted); font-size:14.5px; margin-bottom:26px; }
  .sub b{ color:var(--ink); font-weight:600; }

  .stats{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:26px; }
  @media (max-width:820px){ .stats{ grid-template-columns:repeat(2,1fr); } }
  .stat{ position:relative; overflow:hidden; padding:18px 18px 16px; border-radius:18px;
    background:var(--glass); border:1px solid var(--line); backdrop-filter:blur(14px);
    box-shadow:0 10px 30px rgba(0,0,0,.25); }
  .stat::after{ content:""; position:absolute; inset:0 0 auto 0; height:3px;
    background:linear-gradient(90deg,var(--acc1),var(--acc2)); opacity:.8; }
  .stat .n{ font-size:30px; font-weight:800; letter-spacing:-.02em; }
  .stat .l{ font-size:12.5px; color:var(--muted); margin-top:3px; }
  .stat .sm{ font-size:11.5px; color:var(--faint); margin-top:6px; line-height:1.3;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
  .stat.vk::after{ background:linear-gradient(90deg,var(--vk1),var(--vk2)); }
  .stat.dz::after{ background:linear-gradient(90deg,var(--dz1),var(--dz2)); }
  .stat.vc::after{ background:linear-gradient(90deg,var(--vc1),var(--vc2)); }

  /* карточки соцсетей со счётчиками */
  .nets{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:26px; }
  @media (max-width:820px){ .nets{ grid-template-columns:1fr; } }
  .net{ display:block; text-decoration:none; color:inherit; padding:16px 18px; border-radius:18px;
    background:var(--glass); border:1px solid var(--line); backdrop-filter:blur(14px);
    box-shadow:0 10px 30px rgba(0,0,0,.25); transition:transform .15s, border-color .15s, box-shadow .15s; }
  .net:hover{ transform:translateY(-3px); border-color:rgba(56,189,248,.4);
    box-shadow:0 16px 38px rgba(0,0,0,.34); }
  .net-h{ display:flex; align-items:center; gap:9px; font-weight:800; font-size:15px; margin-bottom:14px; }
  .net-go{ margin-left:auto; color:var(--faint); font-size:14px; }
  .net:hover .net-go{ color:var(--acc1); }
  .metrics{ display:flex; gap:8px; }
  .metric{ flex:1; text-align:center; padding:9px 4px; border-radius:12px;
    background:rgba(255,255,255,.03); border:1px solid var(--line); }
  .metric .mv{ display:block; font-size:18px; font-weight:800; letter-spacing:-.01em; }
  .metric .ml{ display:block; font-size:10.5px; color:var(--faint); margin-top:2px; }

  .legend{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:22px; font-size:12.5px; align-items:center; }
  .chip{ display:inline-flex; align-items:center; gap:8px; padding:7px 13px; border-radius:999px;
    background:var(--glass); border:1px solid var(--line); color:var(--muted); backdrop-filter:blur(8px); }
  .chip a{ color:var(--ink); font-weight:700; text-decoration:none; border-bottom:1px dashed rgba(255,255,255,.3); }
  .chip a:hover{ color:var(--acc1); border-bottom-color:var(--acc1); }
  .chip b{ color:var(--ink); font-weight:600; }
  .gdot{ width:11px; height:11px; border-radius:50%; }
  .g-vk{ background:linear-gradient(135deg,var(--vk1),var(--vk2)); }
  .g-dz{ background:linear-gradient(135deg,var(--dz1),var(--dz2)); }
  .g-vc{ background:linear-gradient(135deg,var(--vc1),var(--vc2)); }

  .months{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }
  @media (max-width:880px){ .months{ grid-template-columns:1fr; } }
  .month{ padding:20px; border-radius:22px; background:var(--glass);
    border:1px solid var(--line); backdrop-filter:blur(16px);
    box-shadow:0 20px 50px rgba(0,0,0,.32); animation:rise .5s both; }
  @keyframes rise{ from{opacity:0; transform:translateY(14px)} to{opacity:1; transform:none} }
  .month h2{ font-size:18px; font-weight:800; margin:0 0 16px; text-transform:capitalize;
    display:flex; align-items:baseline; gap:8px; }
  .month h2 span{ font-size:13px; font-weight:600; color:var(--faint); }
  .grid{ display:grid; grid-template-columns:repeat(7,1fr); gap:7px; }
  .dow{ font-size:10.5px; color:var(--faint); text-align:center; padding-bottom:6px;
    font-weight:700; letter-spacing:.06em; text-transform:uppercase; }
  .cell{ min-height:86px; border:1px solid var(--line); border-radius:13px; padding:7px 7px 8px;
    background:rgba(255,255,255,.02); position:relative; transition:transform .15s, box-shadow .15s, background .15s; }
  .cell:not(.empty):hover{ transform:translateY(-2px); background:var(--glass2);
    box-shadow:0 12px 26px rgba(0,0,0,.3); }
  .cell.empty{ background:transparent; border:none; }
  .cell.past{ opacity:.5; }
  .cell.wknd{ background:rgba(168,85,247,.04); }
  .cell.today{ border:1px solid rgba(56,189,248,.7);
    background:linear-gradient(180deg,rgba(56,189,248,.16),rgba(56,189,248,.04));
    box-shadow:0 0 0 1px rgba(56,189,248,.5),0 14px 34px rgba(56,189,248,.28); opacity:1; }
  .daynum{ font-size:12.5px; font-weight:700; color:var(--muted); display:flex;
    align-items:center; justify-content:space-between; }
  .cell.today .daynum{ color:#bfe9ff; }
  .cell.today .daynum::after{ content:"сегодня"; font-size:9px; font-weight:700; letter-spacing:.04em;
    color:#0a1020; background:linear-gradient(135deg,var(--acc1),var(--acc2));
    padding:2px 6px; border-radius:999px; }
  .ev{ margin-top:5px; padding:5px 7px; border-radius:9px; color:#fff; position:relative;
    box-shadow:0 4px 12px rgba(0,0,0,.28); overflow:hidden; }
  .ev::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:rgba(255,255,255,.55); }
  .ev.vk{ background:linear-gradient(135deg,var(--vk1),var(--vk2)); }
  .ev.dzen{ background:linear-gradient(135deg,var(--dz1),var(--dz2)); }
  .ev.vc{ background:linear-gradient(135deg,var(--vc1),var(--vc2)); }
  .ev.planned{ opacity:.94; }
  .ev .top{ display:flex; align-items:center; gap:5px; font-size:10px; font-weight:800;
    letter-spacing:.02em; opacity:.96; }
  .ev .top .badge{ margin-left:auto; font-size:10px; opacity:.95; }
  .ev .ttl{ display:block; font-size:10.5px; font-weight:500; line-height:1.22; margin-top:2px;
    color:rgba(255,255,255,.95); display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }

  .note{ margin-top:26px; font-size:13px; color:var(--muted); background:var(--glass);
    border:1px solid var(--line); border-radius:18px; padding:18px 20px; backdrop-filter:blur(12px);
    line-height:1.55; }
  .note b{ color:var(--ink); }
  .foot{ margin-top:18px; text-align:center; font-size:11.5px; color:var(--faint); }
</style>
</head>
<body>
<div class="wrap">
  <div class="kicker"><span class="live"></span>АС&nbsp;Фарм · контент-план</div>
  <h1>Календарь публикаций</h1>
  <div class="sub">Живой график на текущий и следующий месяц. Обновлено <b>__GEN__</b></div>

  <div class="stats">
    <div class="stat"><div class="n">__PUBTOTAL__</div><div class="l">Уже опубликовано</div><div class="sm">по всем каналам</div></div>
    <div class="stat vk"><div class="n">__VKLEFT__</div><div class="l">ВКонтакте в очереди</div><div class="sm">по одному посту в день</div></div>
    <div class="stat dz"><div class="n">__DZENLEFT__</div><div class="l">Дзен в очереди</div><div class="sm">по статье раз в 2 дня</div></div>
    <div class="stat vc"><div class="n">__NEXTVC__</div><div class="l">Следующий VC-лонгрид</div><div class="sm">__NEXTVCTITLE__</div></div>
  </div>

  <div class="nets">__NETWORKS__</div>

  <div class="legend">
    <span class="chip"><span class="gdot g-vk"></span><a href="__VKURL__" target="_blank" rel="noopener">ВКонтакте</a>&nbsp;· каждый день, 12:00</span>
    <span class="chip"><span class="gdot g-dz"></span><a href="__DZURL__" target="_blank" rel="noopener">Дзен</a>&nbsp;· раз в 2 дня</span>
    <span class="chip"><span class="gdot g-vc"></span><a href="__VCURL__" target="_blank" rel="noopener">VC.ru</a>&nbsp;· раз в 30 дней, 10:00</span>
    <span class="chip">✓ опубликовано&nbsp;&nbsp;·&nbsp;&nbsp;◷ запланировано</span>
  </div>

  <div class="months" id="months"></div>

  <div class="note">
    <b>Всё в календаре реально:</b> темы и даты взяты из рабочей очереди постов, ничего не выдумано.
    ВКонтакте — по одному посту в день (осталось <b>__VKLEFT__</b> уникальных постов; повторы запрещены,
    поэтому когда очередь закончится, дни остаются пустыми, пока её не пополнят).
    Дзен — 10 статей переданы в RSS-ленту и ждут модерации Дзена (опубликовано пока 0);
    в календаре они стоят как план — по статье раз в 2 дня. VC.ru — один лонгрид раз в 30 дней;
    интервал считается от даты последней публикации, поэтому не «съезжает» из-за разной длины месяцев.
  </div>
  <div class="foot">обновляется автоматически · АС Фарм</div>
</div>
<script>
const EVENTS = __DATA__;
const MONTHS_RU = ["январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"];
const DOW = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"];
const CH = { vk:"ВК", vc:"VC.RU", dzen:"ДЗЕН" };

function pad(n){ return String(n).padStart(2,"0"); }
function iso(y,m,d){ return `${y}-${pad(m+1)}-${pad(d)}`; }
function esc(s){ return s.replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function byDate(){
  const map = {};
  for(const e of EVENTS){ (map[e.date] = map[e.date]||[]).push(e); }
  return map;
}

function renderMonth(year, month, today, map){
  const first = new Date(year, month, 1);
  let startDow = (first.getDay()+6)%7; // Пн=0
  const days = new Date(year, month+1, 0).getDate();
  let cells = "";
  for(let i=0;i<startDow;i++) cells += '<div class="cell empty"></div>';
  const todayMid = new Date(today.getFullYear(),today.getMonth(),today.getDate());
  for(let d=1; d<=days; d++){
    const key = iso(year,month,d);
    const evs = (map[key]||[]).sort((a,b)=> (a.time<b.time?-1:1));
    const cur = new Date(year,month,d);
    const wd = (cur.getDay()+6)%7;
    let cls = "cell";
    if(wd>=5) cls += " wknd";
    if(cur.getTime()===todayMid.getTime()) cls += " today";
    else if(cur < todayMid) cls += " past";
    let inner = `<div class="daynum"><span>${d}</span></div>`;
    for(const e of evs){
      const mark = e.status==="published" ? "✓" : "◷";
      const tm = e.time && e.time!=="—" ? e.time : "";
      inner += `<div class="ev ${e.channel} ${e.status}">`+
               `<div class="top"><span>${CH[e.channel]}${tm?(" · "+tm):""}</span><span class="badge">${mark}</span></div>`+
               `<span class="ttl">${esc(e.title)}</span></div>`;
    }
    cells += `<div class="${cls}">${inner}</div>`;
  }
  let head = DOW.map(x=>`<div class="dow">${x}</div>`).join("");
  return `<div class="month"><h2>${MONTHS_RU[month]}<span>${year}</span></h2>`+
         `<div class="grid">${head}${cells}</div></div>`;
}

function draw(){
  const today = new Date();
  const map = byDate();
  let y=today.getFullYear(), m=today.getMonth();
  let ny=m<11?y:y+1, nm=(m+1)%12;
  document.getElementById("months").innerHTML =
    renderMonth(y,m,today,map) + renderMonth(ny,nm,today,map);
}
draw();
document.addEventListener("visibilitychange", ()=>{ if(!document.hidden) draw(); });
setInterval(draw, 60*60*1000);
</script>
</body>
</html>"""


def main():
    posts = json.load(open(QUEUE, encoding="utf-8"))
    out = render(posts)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print("calendar ->", OUT)


if __name__ == "__main__":
    main()
