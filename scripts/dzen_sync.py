"""Авто-детект реальных публикаций Дзена и отметка их в очереди.

У Дзена НЕТ API: публикации видны только на странице канала, которая закрыта
антиботом/редиректом на Яндекс-вход. Берём её через Scrapfly (ASP + render_js +
RU), сверяем заголовки наших постов с тем, что реально на канале, и проставляем
channels.dzen.published_at для НОВО обнаруженных. Так календарь отражает
реальность сам, без ручных пометок.

Дату ставим = момент ПЕРВОГО обнаружения (точную дату публикации Дзен не отдаёт).
Если Scrapfly недоступен / ключа нет — тихо выходим (пайплайн не ломаем).
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(REPO_ROOT, "content", "queue.json")
STATE = os.path.join(REPO_ROOT, "data", "dzen_watch.json")
CHANNEL_URL = "https://dzen.ru/asfarm_ru"
MSK = timezone(timedelta(hours=3))


def fetch_channel_html(key: str) -> str:
    api = ("https://api.scrapfly.io/scrape?key=" + key
           + "&url=" + quote(CHANNEL_URL, safe="")
           + "&asp=true&render_js=true&country=ru&rendering_wait=4000")
    r = requests.get(api, timeout=180)
    r.raise_for_status()
    return ((r.json().get("result") or {}).get("content") or "")


def main():
    key = os.environ.get("SCRAPFLY_KEY", "").strip()
    if not key:
        print("dzen_sync: SCRAPFLY_KEY не задан — пропуск.")
        return 0
    try:
        html = fetch_channel_html(key)
    except Exception as e:
        print(f"dzen_sync: Scrapfly недоступен ({str(e)[:120]}) — пропуск.")
        return 0
    if len(html) < 5000:
        print("dzen_sync: страница канала пустая/короткая — пропуск.")
        return 0

    posts = json.load(open(QUEUE, encoding="utf-8"))
    now = datetime.now(MSK).replace(microsecond=0).isoformat()
    newly = []
    for p in posts:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        dz = p.setdefault("channels", {}).setdefault("dzen", {})
        if dz.get("published_at"):
            continue
        if title in html:                       # статья реально на канале
            dz["published_at"] = now
            newly.append(title)

    total = sum(1 for p in posts if p.get("channels", {}).get("dzen", {}).get("published_at"))
    if newly:
        json.dump(posts, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"dzen_sync: обнаружены НОВЫЕ публикации Дзена ({len(newly)}):")
        for t in newly:
            print("   ✓", t)
    else:
        print("dzen_sync: новых публикаций Дзена нет.")
    print(f"dzen_sync: всего опубликовано Дзеном по факту — {total}.")

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"checked_at": now, "dzen_published_count": total},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
