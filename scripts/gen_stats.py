"""Сборщик РЕАЛЬНОЙ статистики соцсетей АС Фарм → docs/stats.json.

Только факты из API; чего нет — помечаем null (в календаре не показываем).
Запускается раз в сутки из publish.py перед генерацией календаря.

- ВКонтакте: подписчики, постов на стене, сумма просмотров (token из env VK_TOKEN
  или /Users/nikol/Desktop/files/vk_token.txt). Источник правды — VK API.
- Дзен: число наших статей в ленте (из очереди). Подписчики/просмотры публичного
  API не имеют — оставляем null.
- VC.ru: число наших публикаций (из очереди). Просмотры/подписчики best-effort.
"""
import os, json, ssl, urllib.request, urllib.parse
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "docs", "stats.json")
HIST = os.path.join(REPO_ROOT, "docs", "stats_history.json")
QUEUE = os.path.join(REPO_ROOT, "content", "queue.json")
CTX = ssl._create_unverified_context()

VK_GROUP_ID = "239602265"      # owner_id = -239602265
VK_SCREEN = "asfarm_ru"
DZEN_URL = "https://dzen.ru/asfarm_ru"
VC_URL = "https://vc.ru/id6010646"
TG_URL = "https://t.me/asfarm_ru"
TG_CHAT = "@asfarm_ru"          # bot @asfarmru_post_bot — админ канала
OK_URL = "https://ok.ru/group/70000052376502"


def _tg_token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not t:
        p = os.path.expanduser("~/.asfarm_tg")
        t = open(p).read().strip() if os.path.exists(p) else ""
    # файл/значение может быть в формате dotenv (KEY=VALUE, несколько строк) — достаём токен
    if "=" in t or "\n" in t:
        val = ""
        for line in t.splitlines():
            line = line.strip()
            if "TELEGRAM_BOT_TOKEN" in line:
                val = line.split("=", 1)[-1].strip(); break
        t = val or t.splitlines()[0].split("=", 1)[-1].strip()
    return t


def _vk_token():
    t = os.environ.get("VK_TOKEN", "").strip()
    if t:
        return t
    p = "/Users/nikol/Desktop/files/vk_token.txt"
    if os.path.exists(p):
        return open(p).read().strip()
    return ""


def vk_stats():
    tok = _vk_token()
    if not tok:
        return None
    def call(method, **params):
        params.update(access_token=tok, v="5.199")
        url = f"https://api.vk.com/method/{method}?" + urllib.parse.urlencode(params)
        return json.load(urllib.request.urlopen(url, context=CTX, timeout=30))
    try:
        g = call("groups.getById", group_id=VK_GROUP_ID, fields="members_count")
        grp = g["response"]["groups"][0] if "groups" in g.get("response", {}) else g["response"][0]
        members = grp.get("members_count")
        screen = grp.get("screen_name", VK_SCREEN)
        w = call("wall.get", owner_id=f"-{VK_GROUP_ID}", count=100)
        items = w["response"]["items"]
        total = w["response"]["count"]
        views = sum(it.get("views", {}).get("count", 0) for it in items)
        return dict(subscribers=members, posts=total, views=views or None,
                    url=f"https://vk.com/{screen}")
    except Exception as e:
        print("vk_stats error:", e)
        return dict(url=f"https://vk.com/{VK_SCREEN}")


def dzen_stats(posts):
    # Дзен сам публикует из RSS. Считаем РЕАЛЬНО вышедшие статьи — их по факту
    # отмечает dzen_sync.py (Scrapfly) полем channels.dzen.published_at.
    # released_at (отдано в ленту) — НЕ публикация, не считаем. Подписчиков/просмотров
    # публичного API у канала нет → null.
    published = len([p for p in posts if p["channels"].get("dzen", {}).get("published_at")])
    return dict(subscribers=None, posts=published, views=None, url=DZEN_URL)


def vc_stats(posts):
    published = len([p for p in posts if p["channels"].get("vc", {}).get("posted_at")])
    return dict(subscribers=None, posts=published, views=None, url=VC_URL)


def _tg_views_total():
    """Сумма просмотров по всем постам канала с публичной превью-страницы t.me/s/<chan>
    (с пагинацией по ?before=). Возвращает int или None."""
    import re
    def num(s):
        s = s.strip().replace(" ", "").replace(" ", "")
        mul = 1
        if s[-1:].upper() == "K":
            mul, s = 1000, s[:-1]
        elif s[-1:].upper() == "M":
            mul, s = 1_000_000, s[:-1]
        try:
            return int(float(s.replace(",", ".")) * mul)
        except ValueError:
            return 0
    total, before, seen = 0, None, set()
    try:
        for _ in range(12):  # предохранитель от бесконечной пагинации
            url = f"https://t.me/s/{TG_CHAT.lstrip('@')}"
            if before:
                url += f"?before={before}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, context=CTX, timeout=30).read().decode("utf-8", "ignore")
            ids = [int(x) for x in re.findall(r'data-post="[^"]*?/(\d+)"', html)]
            fresh = [i for i in ids if i not in seen]
            if not fresh:
                break
            for v in re.findall(r'tgme_widget_message_views">([^<]+)<', html):
                total += num(v)
            seen.update(ids)
            before = min(ids) if ids else None
            if not before:
                break
    except Exception as e:
        print("tg_views error:", e)
        return None
    return total or None


def tg_stats(posts):
    # посты — по факту отправки (tg.posted_at); подписчики — Bot API getChatMemberCount
    # (бот @asfarmru_post_bot админ канала); просмотры — сумма с t.me/s (публично).
    published = len([p for p in posts if p["channels"].get("tg", {}).get("posted_at")])
    subs = None
    tok = _tg_token()
    if tok:
        try:
            url = f"https://api.telegram.org/bot{tok}/getChatMemberCount?chat_id={TG_CHAT}"
            d = json.load(urllib.request.urlopen(url, context=CTX, timeout=20))
            if d.get("ok"):
                subs = d.get("result")
        except Exception as e:
            print("tg_stats error:", e)
    return dict(subscribers=subs, posts=published, views=_tg_views_total(), url=TG_URL)


def ok_stats(posts):
    # OK постим вручную; факт публикации отмечает ok_sync.py (Scrapfly) полем
    # channels.ok.published_at. Публичного API подписчиков/просмотров нет → null.
    published = len([p for p in posts if p["channels"].get("ok", {}).get("published_at")])
    return dict(subscribers=None, posts=published, views=None, url=OK_URL)


def collect():
    posts = json.load(open(QUEUE, encoding="utf-8"))
    return {
        "vk": vk_stats() or dict(url=f"https://vk.com/{VK_SCREEN}"),
        "dzen": dzen_stats(posts),
        "vc": vc_stats(posts),
        "tg": tg_stats(posts),
        "ok": ok_stats(posts),
    }


# --- история снимков в ЛИЧНОЙ таблице Claude «АС ФАРМ клод код», вкладка stats_history ---
STATS_SHEET_ID = os.environ.get("STATS_SHEET_ID", "1Gz0zU-fT34Tr3LG-WSMZFVy5sgAFgjyC880_79S3Wms")
STATS_TAB = os.environ.get("STATS_HISTORY_TAB", "stats_history")
CH_ORDER = ["vk", "tg", "dzen", "ok", "vc"]
HIST_HEADER = ["date"] + [f"{c}_{m}" for c in CH_ORDER for m in ("subs", "views", "posts")]


def _sheets_creds():
    """Credentials из GSHEETS_SA_JSON (json-строка) / GOOGLE_APPLICATION_CREDENTIALS /
    локального файла сервис-аккаунта. None — если ничего нет (тогда историю пропускаем)."""
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    raw = os.environ.get("GSHEETS_SA_JSON", "").strip()
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    for p in (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
              "/Users/nikol/Desktop/files/claude-sheets-497816-f533a416fa81.json"):
        if p and os.path.exists(p):
            return Credentials.from_service_account_file(p, scopes=scopes)
    return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pick_prev(rows, today_iso):
    """Строка для сравнения: с датой ≤ сегодня−7 (ближайшая); если истории меньше
    недели — самая ранняя из прошлых. rows — список dict по HIST_HEADER."""
    from datetime import date as _date
    y, m, d = map(int, today_iso.split("-"))
    target = (_date(y, m, d) - __import__("datetime").timedelta(days=7)).isoformat()
    past = sorted([r for r in rows if r.get("date", "") < today_iso], key=lambda r: r["date"])
    if not past:
        return None
    le7 = [r for r in past if r["date"] <= target]
    return le7[-1] if le7 else past[0]


def _save_history_sheet(data):
    """Апсертит строку за сегодня в stats_history и возвращает снимок ~7-дневной
    давности {channel: {subs, views}} для стрелок. Тихо пропускает без кредов."""
    try:
        import gspread
        creds = _sheets_creds()
        if not creds:
            print("history: нет кредов Google — снимок в таблицу пропущен"); return {}
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(STATS_SHEET_ID)
        try:
            ws = sh.worksheet(STATS_TAB)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=STATS_TAB, rows=400, cols=len(HIST_HEADER))
            ws.update([HIST_HEADER], "A1", value_input_option="RAW")
        today_iso = date.today().isoformat()
        row = [today_iso]
        for c in CH_ORDER:
            s = data.get(c, {}) or {}
            row += [s.get("subscribers"), s.get("views"), s.get("posts")]
        existing = ws.get_all_records()  # список dict по заголовку (без строки сегодня учитываем ниже)
        col_a = ws.col_values(1)
        if today_iso in col_a:
            ws.update([row], f"A{col_a.index(today_iso) + 1}", value_input_option="RAW")
        else:
            ws.append_row(row, value_input_option="RAW")
        print(f"history: снимок за {today_iso} записан в {STATS_TAB}")
        prev = _pick_prev(existing, today_iso)
        if not prev:
            return {}
        return {c: {"subs": _num(prev.get(f"{c}_subs")), "views": _num(prev.get(f"{c}_views"))}
                for c in CH_ORDER}
    except Exception as e:
        print("history: ошибка записи в таблицу:", str(e)[:150])
        return {}


def main():
    data = collect()
    prev = _save_history_sheet(data)          # пишет снимок + отдаёт значения 7-дн давности
    for c, p in (prev or {}).items():          # вкладываем «неделю назад» для стрелок в календаре
        if c in data:
            data[c]["prev"] = p
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("stats ->", OUT)
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
