"""Адаптер Дзена через RSS-импорт.

Дзен не имеет API публикации. Официальный путь: отдать размеченную RSS-ленту,
Дзен сам тянет статьи. Требования Дзена: в ленте ≥10 материалов, ссылки ведут
на реальные страницы-источники, картинки ≥700px.

Поэтому генерим СТАТИЧЕСКИЙ САЙТ в DOCS_DIR (раздаётся бесплатно на GitHub Pages):
  docs/index.html          — список статей
  docs/posts/<id>.html     — страница-источник под каждую статью
  docs/feed.xml            — RSS-лента для Дзен Студио
Запускается каждый раз — идемпотентно перестраивает сайт из очереди.
"""

import os
import html
import shutil
from email.utils import format_datetime
from datetime import datetime, timezone

from .. import config


def _paragraphs_html(body: str) -> str:
    parts = [p.strip() for p in body.split("\n\n") if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in parts)


def _links_html(links: dict) -> str:
    if not links:
        return ""
    out = []
    if links.get("wb"):
        out.append(f'<a href="{html.escape(links["wb"])}">Wildberries</a>')
    if links.get("ozon"):
        out.append(f'<a href="{html.escape(links["ozon"])}">Ozon</a>')
    return f'<p>Где купить: {" · ".join(out)}</p>' if out else ""


def _post_url(post: dict) -> str:
    return f"{config.SITE_BASE_URL.rstrip('/')}/posts/{post['id']}.html"


def _render_article_page(post: dict) -> str:
    img = ""
    if post.get("_image_url"):
        img = (
            f'<figure><img src="{html.escape(post["_image_url"])}" '
            f'alt="{html.escape(post["title"])}" width="700"></figure>'
        )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(post['title'])}</title>
<meta name="description" content="{html.escape(post.get('body_long','')[:160])}">
</head>
<body>
<article>
<h1>{html.escape(post['title'])}</h1>
{img}
{_paragraphs_html(post.get('body_long',''))}
{_links_html(post.get('links'))}
</article>
</body>
</html>"""


def _render_index(posts: list) -> str:
    items = "".join(
        f'<li><a href="posts/{p["id"]}.html">{html.escape(p["title"])}</a></li>'
        for p in posts
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>{html.escape(config.SITE_TITLE)}</title>
<meta name="description" content="{html.escape(config.SITE_DESCRIPTION)}"></head>
<body><h1>{html.escape(config.SITE_TITLE)}</h1><ul>{items}</ul></body>
</html>"""


def _render_feed(posts: list) -> str:
    now = format_datetime(datetime.now(timezone.utc))
    items_xml = []
    for p in posts:
        url = _post_url(p)
        content_html = _paragraphs_html(p.get("body_long", ""))
        if p.get("_image_url"):
            content_html = (
                f'<figure><img src="{html.escape(p["_image_url"])}" width="700"></figure>'
                + content_html
            )
        content_html += _links_html(p.get("links"))
        items_xml.append(f"""    <item>
      <title>{html.escape(p['title'])}</title>
      <link>{html.escape(url)}</link>
      <guid isPermaLink="true">{html.escape(url)}</guid>
      <pubDate>{now}</pubDate>
      <description>{html.escape(p.get('body_long','')[:200])}</description>
      <content:encoded><![CDATA[{content_html}]]></content:encoded>
    </item>""")
    items = "\n".join(items_xml)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{html.escape(config.SITE_TITLE)}</title>
    <link>{html.escape(config.SITE_BASE_URL)}</link>
    <description>{html.escape(config.SITE_DESCRIPTION)}</description>
    <language>ru</language>
{items}
  </channel>
</rss>"""


def build_site(posts: list, docs_dir: str = None) -> dict:
    """Перестраивает статический сайт и RSS-фид. Возвращает пути и счётчики."""
    docs_dir = docs_dir or config.DOCS_DIR
    posts_dir = os.path.join(docs_dir, "posts")
    images_dir = os.path.join(docs_dir, "images")
    os.makedirs(posts_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Копируем картинки постов на сайт и проставляем публичный URL.
    for p in posts:
        img = p.get("image")
        if img:
            src = img if os.path.isabs(img) else os.path.join(repo_root, img)
            if os.path.exists(src):
                name = os.path.basename(src)
                shutil.copyfile(src, os.path.join(images_dir, name))
                p["_image_url"] = f"{config.SITE_BASE_URL.rstrip('/')}/images/{name}"

    for p in posts:
        with open(os.path.join(posts_dir, f"{p['id']}.html"), "w", encoding="utf-8") as f:
            f.write(_render_article_page(p))

    with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(_render_index(posts))

    feed_path = os.path.join(docs_dir, "feed.xml")
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(_render_feed(posts))

    # .nojekyll — чтобы GitHub Pages не обрабатывал сайт через Jekyll
    open(os.path.join(docs_dir, ".nojekyll"), "w").close()

    return {
        "feed_path": feed_path,
        "feed_url": f"{config.SITE_BASE_URL.rstrip('/')}/feed.xml",
        "count": len(posts),
        "enough_for_dzen": len(posts) >= 10,
    }
