"""Авто-детект реальных публикаций в Одноклассниках и отметка их в очереди.

В OK посты выкладываются ВРУЧНУЮ (авто-API закрыт), поэтому пайплайн не знает,
что уже вышло. Берём страницу группы через Scrapfly (ASP + render_js + RU),
сверяем заголовки наших постов с тем, что на странице, и проставляем
channels.ok.published_at для обнаруженных (снимая флаг planned). Так календарь
сам отражает реальность OK, без ручных пометок.

Дату ставим = момент первого обнаружения (точную OK не отдаёт). Без ключа/при
ошибке Scrapfly — тихо выходим (пайплайн не ломаем).
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(REPO_ROOT, "content", "queue.json")
STATE = os.path.join(REPO_ROOT, "data", "ok_watch.json")
GROUP_URL = "https://ok.ru/group/70000052376502"
MSK = timezone(timedelta(hours=3))
THROTTLE_H = 72  # OK ручной и редкий — скрейпить дорогим Scrapfly не чаще раза в ~3 сут


def _hours_since_last_check() -> float:
    try:
        st = json.load(open(STATE, encoding="utf-8"))
        prev = datetime.fromisoformat(st["checked_at"])
        return (datetime.now(MSK) - prev).total_seconds() / 3600
    except Exception:
        return 1e9


def fetch_html(key: str) -> str:
    api = ("https://api.scrapfly.io/scrape?key=" + key
           + "&url=" + quote(GROUP_URL, safe="")
           + "&asp=true&render_js=true&country=ru&rendering_wait=5000")
    r = requests.get(api, timeout=180)
    r.raise_for_status()
    return ((r.json().get("result") or {}).get("content") or "")


def main():
    key = os.environ.get("SCRAPFLY_KEY", "").strip()
    if not key:
        print("ok_sync: SCRAPFLY_KEY не задан — пропуск.")
        return 0

    # Троттл: не чаще раза в THROTTLE_H (экономим кредиты Scrapfly).
    hrs = _hours_since_last_check()
    if hrs < THROTTLE_H:
        print(f"ok_sync: последняя сверка {hrs:.0f} ч назад (< {THROTTLE_H} ч) — пропуск.")
        return 0

    try:
        html = fetch_html(key)
    except Exception as e:
        print(f"ok_sync: Scrapfly недоступен ({str(e)[:120]}) — пропуск.")
        return 0
    if len(html) < 5000:
        print("ok_sync: страница группы пустая/короткая — пропуск.")
        return 0

    posts = json.load(open(QUEUE, encoding="utf-8"))
    now = datetime.now(MSK).replace(microsecond=0).isoformat()
    newly = []
    for p in posts:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        ok = p.setdefault("channels", {}).setdefault("ok", {})
        if ok.get("published_at"):
            continue
        if title[:30] in html:                    # пост реально на странице группы
            ok["published_at"] = now
            ok.pop("planned", None)
            newly.append(title)

    total = sum(1 for p in posts if p.get("channels", {}).get("ok", {}).get("published_at"))
    if newly:
        json.dump(posts, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"ok_sync: обнаружены НОВЫЕ публикации OK ({len(newly)}):")
        for t in newly:
            print("   ✓", t)
    else:
        print("ok_sync: новых публикаций OK нет.")
    print(f"ok_sync: всего опубликовано в OK по факту — {total}.")

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"checked_at": now, "ok_published_count": total},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
