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
GEMINI_MODEL = "gemini-flash-lite-latest"  # 2.0-flash Google лишил free-tier (429) 2026-07 → генерация встала; lite — единственная с реальным free-лимитом

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

# Ракурсы темы — чтобы заголовки не сходились к одному (flash-lite повторяется).
# Много бытовых углов + осенне-сентябрьские (сад/школа, простуды) — сезонно.
ANGLES = [
    "в дороге и путешествии, когда нет раковины",
    "в детском саду и школе, гигиена вне дома",
    "осенью в сезон простуд и болезней",
    "когда режутся зубки у малыша",
    "перед сном и утренний ритуал",
    "первый визит к стоматологу без страха",
    "мифы и заблуждения родителей",
    "как приучить ребёнка к гигиене играючи",
    "сладкое и перекусы: как беречь зубы",
    "уход за молочными зубами с рождения",
    "гигиена у пожилых и маломобильных близких",
    "что взять в поездку/на дачу летом и осенью",
    "почему кровоточат дёсны и что делать",
    "свежее дыхание в течение дня",
    "уход при брекетах и после лечения",
    "гигиена, когда ребёнок болеет и капризничает",
    "экономия времени занятой мамы",
    "чек-лист здоровой улыбки на каждый день",
    "как выбрать формат под возраст ребёнка",
    "уход в офисе и на работе среди дня",
]

BRIEF = """Ты — текстолог бренда «АС Фарм» (российская гигиена полости рта). Пиши спокойно, по-человечески, только факты. БЕЗ эмодзи в тексте (кроме финальной подписи), без канцелярита, без «важно отметить/в заключение», без списков-штампов, без восклицаний.

ЖЁСТКИЕ ФАКТЫ (путать НЕЛЬЗЯ):
- Дентал — это гигиенические САЛФЕТКИ для полости рта (НЕ паста, НЕ таблетки, НЕ прибор). Цифра в названии = число салфеток в упаковке.
- Детские дентал-салфетки — С КСИЛИТОМ. Вкусов РОВНО ЧЕТЫРЕ: груша, земляника, банан-шоколад (это ОДИН вкус — банан и шоколад вместе) и без вкуса. Никогда не пиши «три вкуса».
- Форматы детских: 20/40/100 шт. Взрослые — отдельная линейка, 50 шт.
- Ирригатор тут — это ЖИДКОСТЬ-концентрат 2-в-1 как ополаскиватель, НЕ прибор.
- Запрещено: обещания лечения («лечит», «вылечит», «гарантирует», «избавит от болезни»), реклама-маркеры («купить», «скидка», «переходите», «закажите», «акция»), любые посторонние/выдуманные товары и бренды, темы 18+ и криолиполиз, конкретные цены.

ТОВАР ЭТОГО ПОСТА: {product_fact}.

Напиши УНИКАЛЬНУЮ образовательную статью. РАКУРС (угол) ИМЕННО ЭТОГО поста: {angle}. Раскрой этот угол по-настоящему, естественно связав с товаром — заголовок должен отражать именно этот ракурс, а не общий. НЕ повторяй уже занятые заголовки:
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
        return json.loads(txt, strict=False)  # strict=False: разрешить сырые \n в строках (flash-lite)
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


# РАЗНООБРАЗНЫЕ тематические сцены обложек (согласованный стиль владельца 2026-06-27):
# люди с детьми, детская/взрослая стоматология, здоровые улыбки, немного food, вода.
# НИКАКОЙ упаковки/товара с текстом (Flux рисует фейк-бренды — владелец резко против).
# Для людей: лица в мягком фокусе, РУКИ ВНЕ КАДРА, мягкая улыбка с закрытым ртом
# (открытый рот/детальные зубы Flux деформирует). Каждая сцена — самодостаточный промпт.
_PHOTO = ", professional photography, soft warm bokeh, shallow depth of field, bright airy pastel tones, cozy natural daylight"
_NOTXT = ", no text, no letters, no words, no logos, no brand names, no packaging, no bottles, no jars, no tubes, no labels"
_PPL = ", natural realistic anatomy, no deformed hands, no extra fingers, hands out of frame, gentle soft closed-lip smile, no open mouth, no distorted face, no blurry eyes"
# Замиксованный набор (по просьбе владельца): каждый пост — другой тип, все в тему
# детской гигиены полости рта. Перебор по кругу → соседние обложки всегда разные.
# Люди детей — только БЕЗОПАСНЫЙ кадр (близко «голова-плечи» / со спины), руки не влезают.
# Большой пул РАЗНЫХ сюжетов — чтобы каждый пост был уникален (мало сцен → повторы,
# и один тип даёт почти одинаковые кадры). Все безопасны: близкий кадр (руки не влезают),
# со спины (без лиц/рук) или натюрморт без людей. Кабинета мало (он однообразен).
_KIDCU = " only face and shoulders fill the frame, no hands, no arms" + _PPL + _NOTXT + _PHOTO
_BACK = " seen from behind, soft focus, no faces, no hands visible" + _NOTXT + _PHOTO
_STILL = ", no people, no hands" + _NOTXT + _PHOTO
_SOFT = _PPL + _NOTXT + _PHOTO
SCENES = [
    # дети крупным планом (разный фон/настроение)
    "an extreme close-up portrait of a cheerful healthy child with a gentle soft smile, warm orange background," + _KIDCU,
    "an extreme close-up portrait of a giggling happy little child, soft pastel blue background," + _KIDCU,
    "an extreme close-up portrait of a peaceful smiling toddler, soft green leafy background," + _KIDCU,
    "an extreme close-up portrait of a joyful child looking up happily, bright clean white background," + _KIDCU,
    "an extreme close-up portrait of a happy baby with a tiny gentle smile, warm neutral beige background," + _KIDCU,
    # мама / семья (безопасный кадр)
    "a happy young mother and her small child cheek to cheek by a bright window, warm tender moment, soft focus faces" + _SOFT,
    "a tender extreme close-up of a mother softly kissing her happy baby on the cheek, only heads and shoulders," + _KIDCU,
    "a happy family of three with a small child at a sunny breakfast table, warm joyful morning, soft focus" + _SOFT,
    "a mother reading a colorful picture book to her child on a cozy couch, warm soft focus, hands out of frame" + _SOFT,
    "two little siblings hugging each other cheek to cheek, close, warm bright room, soft focus" + _SOFT,
    "a mother cuddling her toddler wrapped in a soft cozy blanket, warm morning light, soft focus, hands out of frame" + _SOFT,
    # стоматология (немного, разные ракурсы)
    "a bright modern cheerful pediatric dental office interior, cozy children's clinic, soft daylight" + _STILL,
    "a little child sitting happily and relaxed in a friendly bright pediatric dental chair, soft focus" + _SOFT,
    "a cozy children's dental clinic waiting area with soft toys and books, warm and friendly" + _STILL,
    # дети на природе / сезон (со спины)
    "happy children running in a sunny golden autumn park," + _BACK,
    "a child walking along a path covered with golden autumn leaves in a park," + _BACK,
    "children playing together in a bright green summer meadow," + _BACK,
    "a child on a swing in a sunny park in warm daylight," + _BACK,
    "a family walking together holding a small child in a beautiful autumn park," + _BACK,
    # натюрморт / еда / сезон
    "ripe whole pears, fresh red strawberries and a ripe banana with green mint on a light wooden table, natural food photography" + _STILL,
    "a sliced ripe juicy pear and fresh mint leaves on a clean white plate, natural food photography" + _STILL,
    "fresh red strawberries in a ceramic bowl with green mint leaves, natural food photography" + _STILL,
    "a rustic wooden crate of ripe pears and apples by a sunny window, natural food photography" + _STILL,
    "a cozy warm autumn flatlay with a knitted scarf, acorns, pinecones and colorful leaves on a table" + _STILL,
    "a bright back-to-school flatlay with a small kids backpack, colorful autumn leaves and pencils on a table" + _STILL,
    # предметы гигиены (без брендов)
    "colorful children's toothbrushes standing in a ceramic cup on a bright clean bathroom shelf, soft morning light" + _STILL,
    "a single clear glass of clean water with a sprig of fresh green mint on a bright clean table in soft morning light" + _STILL,
    "a clear glass of water on a bright clean bathroom shelf in soft morning sunlight" + _STILL,
    # интерьеры детские
    "a bright cheerful cozy children's room interior with soft pastel toys and warm daylight" + _STILL,
    "a sunny cozy kitchen morning scene with a bowl of oatmeal and fresh berries on the table" + _STILL,
    # стоматология с ДЕТАЛЯМИ + зубы/инструменты (одобрено владельцем 2026-08)
    "a clean set of shiny stainless steel dental instruments, a small round dental mirror and probe, neatly arranged on a soft light blue surface, bright clean macro photography" + _STILL,
    "a friendly dentist gently examining a smiling child's teeth with a small dental mirror in a bright modern clinic, warm reassuring, soft focus, natural realistic anatomy, no deformed hands, no extra fingers" + _NOTXT + _PHOTO,
    "an extreme close-up of a healthy child's bright cheerful smile showing clean white teeth, only face fills the frame, no hands, realistic natural teeth, warm natural light" + _NOTXT + _PHOTO,
    # ребёнок ест что-то сладкое (для тем про сладкое/перекусы) — одобрено
    "a happy little child joyfully eating a sweet cookie snack, close-up, warm cozy light, natural realistic anatomy, no deformed hands, no extra fingers, realistic natural teeth" + _NOTXT + _PHOTO,
    "a cheerful happy child holding and licking a colorful swirl lollipop, close-up, warm bright light, natural realistic anatomy, no deformed hands, no extra fingers" + _NOTXT + _PHOTO,
    # тёплые сцены заботы (болезнь/прорезывание/температура) — одобрено
    "a young mother tenderly cuddling and comforting her little child wrapped in a soft cozy blanket at home, warm loving caring moment, soft focus faces" + _SOFT,
    "a cute peaceful baby sleeping calmly and serenely in a cozy soft pastel crib, warm gentle morning light, tender quiet scene, soft focus, natural realistic anatomy, no deformed hands" + _NOTXT + _PHOTO,
    "a little child resting cozily in bed under a warm soft blanket, gentle daylight through the window, calm and peaceful, soft focus, natural realistic anatomy, no deformed hands" + _NOTXT + _PHOTO,
    "a cozy warm get-well scene on a bedside table, a mug of herbal tea, a soft folded knitted blanket and a small vase of flowers by a sunny window" + _STILL,
]


def generate(n, posts, gkey):
    from scripts.gen_cf import gen as gen_cover
    used_ids = {p["id"] for p in posts}
    used_titles = [p["title"] for p in posts]
    made = 0
    rot = ROTATION[:]
    attempts = 0
    while made < n and attempts < n * 4:
        attempts += 1
        pkey = rot[(len(posts) + made) % len(rot)]
        wb, ozon, fact = PRODUCTS[pkey]
        angle = ANGLES[(len(posts) + attempts) % len(ANGLES)]
        prompt = BRIEF.format(product_fact=fact, angle=angle,
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
            scene = SCENES[(len(posts) + made) % len(SCENES)]
            gen_cover(scene, os.path.join(REPO, img))
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
