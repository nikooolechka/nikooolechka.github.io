"""Автодолив контента: держит очередь заполненной ВСЕГДА до конца следующего месяца.

Запускается ежедневно из GitHub Actions (перед публикацией). Логика:
- считает, сколько постов нужно, чтобы ежедневный ВК дотянул до конца СЛЕДУЮЩЕГО месяца;
- если в очереди неопубликованных меньше — дописывает недостающее (но не больше MAX_PER_RUN за запуск);
- текст пишет Gemini (бесплатный текстовый лимит) строго по бренд-брифу;
- обложку рисует Cloudflare (Flux schnell, бесплатно);
- каждый пост проходит validator + бренд-факт-чек; брак не попадает в очередь.

Никаких повторов: тема привязана к товару из фиксированного списка (ссылки заданы нами,
Gemini их не выдумывает), а уже использованные заголовки передаются Gemini как стоп-список.

Ключи: GEMINI_KEY / CF_TOKEN / CF_ACCOUNT из env (в CI — GitHub Secrets),
локально — из /Users/nikol/Desktop/files/{gemini_key,cloudflare_token,cloudflare_account}.txt.
"""

import os
import re
import json
import time
import calendar
import unicodedata
from datetime import date

import requests

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, validator  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(REPO, "content", "queue.json")
FILES = "/Users/nikol/Desktop/files"
MAX_PER_RUN = 3
GEMINI_MODEL = "gemini-2.0-flash"

# --- Товары: ключ -> ссылки + точные факты для брифа (Gemini ничего не выдумывает) ---
PRODUCTS = {
    "dental100":     ("https://www.wildberries.ru/catalog/205348527/detail.aspx", "https://www.ozon.ru/product/1420874181",
                      "детские дентальные салфетки с ксилитом, вкус груша, 100 штук в упаковке"),
    "dental40":      ("https://www.wildberries.ru/catalog/140759945/detail.aspx", "https://www.ozon.ru/product/823756780",
                      "детские дентальные салфетки с ксилитом, вкус груша, 40 штук в упаковке"),
    "dental20":      ("https://www.wildberries.ru/catalog/76952248/detail.aspx", "https://www.ozon.ru/product/562217972",
                      "детские дентальные салфетки с ксилитом, вкус груша, 20 штук — компактный формат"),
    "dental50":      ("https://www.wildberries.ru/catalog/140595726/detail.aspx", "https://www.ozon.ru/product/735634625",
                      "взрослые дентальные салфетки, 50 штук — для дороги и ухода за пожилыми/лежачими"),
    "dental100_zem": ("https://www.wildberries.ru/catalog/583154383/detail.aspx", "https://www.ozon.ru/product/3044396307",
                      "детские дентальные салфетки с ксилитом, вкус земляника, 100 штук"),
    "dental40_zem":  ("https://www.wildberries.ru/catalog/860793985/detail.aspx", "https://www.ozon.ru/product/3571493450",
                      "детские дентальные салфетки с ксилитом, вкус земляника, 40 штук"),
    "pasta_det":     ("https://www.wildberries.ru/catalog/917665198/detail.aspx", "https://www.ozon.ru/product/3761797186",
                      "детская зубная паста для молочных зубов"),
    "irrigator500":  ("https://www.wildberries.ru/catalog/227067968/detail.aspx", "https://www.ozon.ru/product/1560047806",
                      "жидкость-концентрат для ирригатора (НЕ прибор), работает 2-в-1 как ополаскиватель, 500 мл"),
    "irrigator1000": ("https://www.wildberries.ru/catalog/363137625/detail.aspx", "https://www.ozon.ru/product/1938973353",
                      "жидкость-концентрат для ирригатора (НЕ прибор), 2-в-1 как ополаскиватель, 1000 мл"),
    "optika":        ("https://www.wildberries.ru/catalog/206024627/detail.aspx", "https://www.ozon.ru/product/736267318",
                      "спрей для чистки стёкол очков"),
}
# порядок ротации по товарам (детский уход чаще — ~половина)
ROTATION = ["dental100", "pasta_det", "dental40", "irrigator1000", "dental20",
            "dental50", "dental100_zem", "irrigator500", "dental40_zem", "optika"]

BRIEF = """Ты — текстолог бренда «АС Фарм» (российская гигиена полости рта). Пиши спокойно, по-человечески, только факты. БЕЗ эмодзи в тексте (кроме финальной подписи), без канцелярита, без «важно отметить/в заключение», без списков-штампов, без восклицаний.

ЖЁСТКИЕ ФАКТЫ (путать НЕЛЬЗЯ):
- Дентал — это гигиенические САЛФЕТКИ для полости рта (НЕ паста, НЕ таблетки, НЕ прибор). Цифра в названии = число салфеток в упаковке.
- Детские дентал-салфетки — С КСИЛИТОМ. Вкусов РОВНО ЧЕТЫРЕ: груша, земляника, банан-шоколад (это ОДИН вкус — банан и шоколад вместе) и без вкуса. Никогда не пиши «три вкуса».
- Форматы детских: 20/40/100 шт. Взрослые — отдельная линейка, 50 шт.
- Ирригатор тут — это ЖИДКОСТЬ-концентрат 2-в-1 как ополаскиватель, НЕ прибор.
- Запрещено: обещания лечения («лечит», «вылечит», «гарантирует», «избавит от болезни»), реклама-маркеры («купить», «скидка», «переходите», «закажите», «акция»), любые посторонние/выдуманные товары и бренды, темы 18+ и криолиполиз, конкретные цены.

ТОВАР ЭТОГО ПОСТА: {product_fact}.

Напиши УНИКАЛЬНУЮ образовательную статью на тему вокруг этого товара. НЕ повторяй уже занятые заголовки:
{avoid}

Верни СТРОГО JSON с ключами:
"title": строка 25–90 символов, без точки в конце, не из списка занятых;
"body_long": лонгрид не короче 1900 символов, с 3–5 подзаголовками вида "## Подзаголовок", абзацы разделены двумя переводами строки, последний абзац — ровно "С любовью, ваш АС-Фарм 🤍";
"body_vk": 420–700 символов, 2–4 коротких абзаца через двойной перевод строки, последний абзац — ровно "С любовью, ваш АС-Фарм 🤍".
"""

BANNED = ["криолиполи", "минет", "лубрикант", "18+", "интим",
          "три вкуса", "3 вкуса", "тремя вкусами", "трёх вкус", "трех вкус"]


def _read(envname, fname):
    v = os.environ.get(envname)
    if v:
        return v.strip()
    return open(os.path.join(FILES, fname)).read().strip()


def _slug(title, used):
    s = unicodedata.normalize("NFKD", title.lower())
    s = re.sub(r"[^a-z0-9а-я]+", "-", s).strip("-")[:24] or "auto"
    base, i = f"auto-{s}", 1
    sid = base
    while sid in used:
        i += 1
        sid = f"{base}-{i}"
    return sid


def _gemini(prompt, key, _tries=4):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.95, "responseMimeType": "application/json"},
    }
    for attempt in range(_tries):
        r = requests.post(url, params={"key": key}, json=payload, timeout=90)
        if r.status_code == 429 and attempt < _tries - 1:
            delay = 50
            try:
                for d in r.json().get("error", {}).get("details", []):
                    if d.get("@type", "").endswith("RetryInfo"):
                        delay = int(re.sub(r"\D", "", d.get("retryDelay", "50")) or 50)
            except Exception:
                pass
            print(f"  429: жду {delay + 3}с и повторяю")
            time.sleep(delay + 3)
            continue
        r.raise_for_status()
        data = r.json()
        txt = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(txt)
    raise RuntimeError("Gemini: исчерпаны попытки (429)")


def _brand_ok(post):
    blob = (post["title"] + " " + post["body_long"] + " " + post["body_vk"]).lower()
    return not any(b in blob for b in BANNED)


def _valid(post):
    if not _brand_ok(post):
        return False
    for field in ("body_long", "body_vk"):
        res = validator.validate_post(post["title"], post.get(field, ""))
        if not res["ok"]:
            return False
    return True


def end_of_next_month(today):
    y, m = today.year, today.month + 1
    if m > 12:
        y, m = y + 1, 1
    return date(y, m, calendar.monthrange(y, m)[1])


def needed_count(posts, today):
    horizon = (end_of_next_month(today) - today).days  # ВК = 1/день
    unposted = sum(1 for p in posts if not p.get("channels", {}).get("vk", {}).get("posted_at"))
    return max(0, horizon - unposted)


def generate(n, posts, gkey):
    from scripts.gen_cf import gen as gen_cover
    SUF = (", soft pastel palette, bright airy, clean minimal, professional product photography, "
           "shallow depth of field, no text, no watermark, no logos, no brand names, no faces")
    used_ids = {p["id"] for p in posts}
    used_titles = [p["title"] for p in posts]
    made = 0
    rot = ROTATION[:]
    attempts = 0
    while made < n and attempts < n * 4:
        attempts += 1
        pkey = rot[(len(posts) + made) % len(rot)]
        wb, ozon, fact = PRODUCTS[pkey]
        prompt = BRIEF.format(product_fact=fact,
                              avoid="\n".join("- " + t for t in used_titles[-40:]))
        try:
            post = _gemini(prompt, gkey)
        except Exception as e:
            print(f"  Gemini ошибка: {str(e)[:90]}"); time.sleep(2); continue
        if not all(k in post for k in ("title", "body_long", "body_vk")):
            continue
        if post["title"] in used_titles or not _valid(post):
            print(f"  отбраковано: «{post.get('title','?')[:40]}»"); continue
        pid = _slug(post["title"], used_ids)
        img = f"content/images/{pid}.jpg"
        # короткий визуальный промпт по товару
        try:
            gen_cover(f"clean tidy still life related to oral hygiene and family care, {fact}" + SUF,
                      os.path.join(REPO, img))
        except Exception as e:
            print(f"  обложка не вышла ({str(e)[:50]}), пропуск"); continue
        post.update(id=pid, image=img, links={"wb": wb, "ozon": ozon},
                    channels={"vc": {}, "vk": {}, "dzen": {}})
        posts.append(post)
        used_ids.add(pid); used_titles.append(post["title"]); made += 1
        print(f"  + «{post['title']}» [{pkey}] → {pid}")
    return made


def main():
    today = date.today()
    posts = json.load(open(QUEUE, encoding="utf-8"))
    need = needed_count(posts, today)
    force = int(os.environ.get("GEN_FORCE", "0") or "0")
    if force:
        print(f"Автодолив: ручной форс GEN_FORCE={force}.")
        need = max(need, force)
    if need <= 0:
        print(f"Автодолив: очередь уже покрывает до конца следующего месяца ({len(posts)} постов). Ничего не делаю.")
        return 0
    todo = min(need, MAX_PER_RUN)
    print(f"Автодолив: до конца следующего месяца не хватает {need} постов, добавляю {todo} (лимит {MAX_PER_RUN}/запуск).")
    gkey = _read("GEMINI_KEY", "gemini_key.txt")
    made = generate(todo, posts, gkey)
    if made:
        json.dump(posts, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"Автодолив: добавлено {made}, в очереди теперь {len(posts)}.")
    else:
        print("Автодолив: за этот запуск ничего валидного не получилось (попробую завтра).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
