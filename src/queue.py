"""Работа с очередью постов (content/queue.json).

Структура одного поста:
{
  "id": "уникальный-слаг",
  "title": "Заголовок",
  "body_long": "Многоабзацный текст для VC и Дзена",
  "body_vk": "Более короткий вариант для стены ВК",
  "image_url": "https://... (опционально, для Дзена)",
  "channels": {
      "vc":   {"posted_at": null, "url": null},
      "vk":   {"posted_at": null, "url": null},
      "dzen": {"released_at": null}   # когда статья выпущена в RSS-фид
  }
}
VK/VC отмечаются по факту публикации (posted_at). Дзен тянет статьи из фида
сам, поэтому для него фиксируем released_at — момент, когда статья попала в фид.
"""

import json
from datetime import datetime
from . import config

POST_CHANNELS = ("vc", "vk")  # каналы с активной отправкой через API


def load(path: str = None) -> list:
    path = path or config.QUEUE_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for post in data:
        ch = post.setdefault("channels", {})
        for c in POST_CHANNELS:
            ch.setdefault(c, {"posted_at": None, "url": None})
        ch.setdefault("dzen", {"released_at": None})
    return data


def save(posts: list, path: str = None) -> None:
    path = path or config.QUEUE_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


# --- VK / VC ---

def next_unposted(posts: list, channel: str):
    for post in posts:
        if not post["channels"].get(channel, {}).get("posted_at"):
            return post
    return None


def iter_unposted(posts: list, channel: str):
    """Все ещё не опубликованные в канал посты, по порядку очереди.
    Нужен, чтобы при сбое на одном посте перейти к следующему, а не застрять."""
    for post in posts:
        if not post["channels"].get(channel, {}).get("posted_at"):
            yield post


def mark_posted(post: dict, channel: str, when: str, url: str = None) -> None:
    post["channels"][channel] = {"posted_at": when, "url": url}


def next_for_channel(posts: list, channel: str):
    """Следующий пост для канала. Сначала ещё не опубликованные; когда все
    опубликованы — РЕЦИКЛИНГ: берём самый давно публиковавшийся (поток не
    прерывается никогда). Возвращает (post, is_recycle)."""
    fresh = next_unposted(posts, channel)
    if fresh:
        return fresh, False
    dated = [
        (p["channels"][channel]["posted_at"], p)
        for p in posts if p["channels"].get(channel, {}).get("posted_at")
    ]
    if not dated:
        return None, False
    dated.sort(key=lambda t: t[0])
    return dated[0][1], True


def last_posted_at(posts: list, channel: str):
    """Самый свежий момент публикации в канал (datetime) или None."""
    stamps = [
        p["channels"][channel]["posted_at"]
        for p in posts
        if p["channels"].get(channel, {}).get("posted_at")
    ]
    return max((datetime.fromisoformat(s) for s in stamps), default=None)


# --- Дзен (RSS-фид) ---

def dzen_released(posts: list) -> list:
    return [p for p in posts if p["channels"]["dzen"].get("released_at")]


def next_unreleased_dzen(posts: list):
    for post in posts:
        if not post["channels"]["dzen"].get("released_at"):
            return post
    return None


def last_released_at(posts: list):
    stamps = [
        p["channels"]["dzen"]["released_at"]
        for p in posts
        if p["channels"]["dzen"].get("released_at")
    ]
    return max((datetime.fromisoformat(s) for s in stamps), default=None)


def release_dzen(post: dict, when: str) -> None:
    post["channels"]["dzen"]["released_at"] = when


def feed_posts(posts: list, limit: int = None):
    """В фид Дзена идут только выпущенные статьи — НОВЕЙШИЕ `limit` штук.
    Сортируем по дате релиза (по убыванию), иначе срез брал старейшие и новые
    релизы после FEED_MAX_ITEMS не попадали в фид (фид замерзал)."""
    limit = limit or config.FEED_MAX_ITEMS
    rel = dzen_released(posts)
    rel.sort(key=lambda p: p["channels"]["dzen"]["released_at"], reverse=True)
    return rel[:limit]
