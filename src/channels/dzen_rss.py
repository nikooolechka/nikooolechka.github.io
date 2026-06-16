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
    out = []
    for p in body.split("\n\n"):
        p = p.strip()
        if not p:
            continue
        if p.startswith("## "):
            out.append(f"<h2>{html.escape(p[3:].strip())}</h2>")
        else:
            out.append(f"<p>{html.escape(p)}</p>")
    return "".join(out)


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
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;background:#fff;color:#1a1a1a;line-height:1.65;}}
  article{{max-width:720px;margin:0 auto;padding:24px 20px 64px;font-size:18px;}}
  h1{{font-size:30px;line-height:1.25;margin:8px 0 20px;}}
  h2{{font-size:22px;margin:32px 0 10px;}}
  figure{{margin:0 0 24px;}}
  figure img{{width:100%;border-radius:14px;display:block;}}
  p{{margin:0 0 16px;}}
  a{{color:#2a5885;}}
</style>
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
    cards = []
    for p in posts:
        img = p.get("_image_url", "")
        thumb = f'<img src="{html.escape(img)}" alt="">' if img else ""
        cards.append(
            f'<a class="card" href="posts/{p["id"]}.html">{thumb}'
            f'<div class="t">{html.escape(p["title"])}</div></a>'
        )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(config.SITE_TITLE)}</title>
<meta name="description" content="{html.escape(config.SITE_DESCRIPTION)}">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;background:#fafafa;color:#1a1a1a;}}
  header{{padding:32px 20px;text-align:center;}}
  header h1{{margin:0 0 6px;font-size:24px;}}
  header p{{margin:0;color:#666;}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px;max-width:1100px;margin:0 auto;padding:0 20px 48px;}}
  .card{{display:block;background:#fff;border-radius:14px;overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 2px 10px rgba(0,0,0,.06);transition:transform .15s;}}
  .card:hover{{transform:translateY(-3px);}}
  .card img{{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;}}
  .card .t{{padding:12px 14px;font-size:15px;font-weight:600;line-height:1.35;}}
</style>
</head>
<body>
  <header><h1>{html.escape(config.SITE_TITLE)}</h1><p>{html.escape(config.SITE_DESCRIPTION)}</p></header>
  <div class="grid">{"".join(cards)}</div>
</body>
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
