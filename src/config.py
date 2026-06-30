"""Конфигурация и правила. Всё, что отделяет «полезный пост» от «рекламы»
и от «текста с ошибками», задаётся здесь — валидатор читает отсюда."""

import os

# --- VC / Osnova API ---
# Токен берётся в настройках аккаунта VC -> «Инструменты для разработчика».
# В GitHub Actions кладётся в Secrets, локально — в .env (не коммитить!).
VC_SUBSITE_ID = os.environ.get("VC_SUBSITE_ID", "6010646")
# Durable refresh-токен VC. НЕ хранить в публичном репо — только env или локальный файл.
VC_REFRESH_TOKEN = os.environ.get("VC_REFRESH_TOKEN", "")
VC_CREDS_PATH = os.environ.get("VC_CREDS_PATH", "/Users/nikol/Desktop/files/vc_creds.txt")
USER_AGENT = "asfarm-poster/1.0"

# --- ВКонтакте API ---
# Токен сообщества с правами wall, manage. owner_id группы — ОТРИЦАТЕЛЬНЫЙ.
VK_TOKEN = os.environ.get("VK_TOKEN", "")
VK_OWNER_ID = os.environ.get("VK_OWNER_ID", "")   # напр. -123456789 (минус = группа)
VK_API_VERSION = os.environ.get("VK_API_VERSION", "5.199")

# --- Одноклассники (OK API) ---
# Группа бренда: https://ok.ru/group/70000052376502
OK_ACCESS_TOKEN = os.environ.get("OK_ACCESS_TOKEN", "")
OK_APP_KEY = os.environ.get("OK_APP_KEY", "")          # публичный Application key
OK_APP_SECRET = os.environ.get("OK_APP_SECRET", "")    # секретный Application secret key
OK_GROUP_ID = os.environ.get("OK_GROUP_ID", "70000052376502")

# --- Telegram (Bot API) ---
# Токен бота от @BotFather. Канал: @username или числовой chat_id (-100...).
# Бот должен быть АДМИНОМ канала с правом публикации.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "")

# --- Дзен (через RSS-импорт) ---
# Дзен не имеет API публикации: мы генерим статические страницы + RSS-фид,
# хостим на GitHub Pages, а в Дзен Студио добавляем URL фида.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://nikooolechka.github.io")
SITE_TITLE = "АС Фарм — уход за полостью рта"
SITE_DESCRIPTION = "Полезные материалы об уходе за зубами, дёснами и гигиене полости рта."
DOCS_DIR = os.environ.get(
    "DOCS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs"),
)
FEED_MAX_ITEMS = 30  # Дзену для первой разметки нужно ≥10 материалов в ленте
# Код подтверждения прав на сайт в Яндекс.Вебмастере (метатег). Вставляется в <head>.
YANDEX_VERIFICATION = os.environ.get("YANDEX_VERIFICATION", "689cbf0b17a97500")
# ID счётчика Яндекс.Метрики (число). Сниппет добавляется на страницы сайта.
YANDEX_METRIKA_ID = os.environ.get("YANDEX_METRIKA_ID", "109902136")
# Код подтверждения прав в Дзене (метатег zen-verification).
ZEN_VERIFICATION = os.environ.get("ZEN_VERIFICATION", "qD3ELLkWlgXvUqwekj4taLbUgW0RBlJnZDDvCSt1Ctqn6nI7pU9u8oXRK28fV0J9")
DZEN_BACKFILL_MIN = 10  # столько статей выпускаем сразу (бэкфилл), чтобы фид прошёл разметку

# --- Безопасная частота публикаций (соблюдается автоматически) ---
# Минимальный интервал между постами в канал, в днях. Даже если workflow
# запускается чаще, код пропустит канал, пока интервал не выдержан.
CADENCE_DAYS = {
    "vk": 1,     # ВК: безопасно 1/день (жёсткий лимит ~50/день)
    "dzen": 2,   # Дзен: ~1 раз в 2 дня = 3–4/нед
    "vc": 30,    # VC: ~1/мес на free-аккаунте
    "tg": 1,     # Telegram: 1/день (Bot API, без жёстких лимитов для канала)
}

# --- Файл очереди постов ---
QUEUE_PATH = os.environ.get(
    "QUEUE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "content", "queue.json"),
)

# --- Правила валидатора ---
# Длина текста поста (символы). VC-лонгриды могут быть длиннее, но для
# «лёгкого поста» держим разумные рамки.
MIN_TEXT_LEN = 350
MAX_TEXT_LEN = 8000
MIN_TITLE_LEN = 15
MAX_TITLE_LEN = 120

# Слова-маркеры ПРЯМОЙ рекламы. Если они есть — пост становится рекламой
# по закону РФ и требует маркировки (erid/ИНН). Мы намеренно держим контент
# образовательным, поэтому такие слова ЗАПРЕЩЕНЫ.
PROMO_WORDS = [
    "купить", "купите", "закажи", "закажите", "заказать", "скидк", "промокод",
    "акция", "распродаж", "по ссылке", "переходите", "успей", "только сегодня",
    "выгодно", "дешевле", "бесплатная доставка", "оформи заказ", "в корзину",
]

# Недопустимые медицинские/ложные обещания (домыслы и обещания лечения).
# Соответствует правилу проекта: только факты, без обещаний результата.
FALSE_CLAIM_WORDS = [
    "вылечит", "вылечивает", "лечит", "излечивает", "гарантир", "на 100%",
    "навсегда избавит", "избавит от болезни", "доказано лечит", "панацея",
    "мгновенно", "без побочных", "официальная медицина скрывает",
]

# Стоп-слова «воды»/слопа (правило stop-slop). Если встречаются — предупреждение.
SLOP_WORDS = [
    "в современном мире", "не секрет, что", "как известно",
    "в наше время", "ни для кого не секрет", "стоит отметить, что",
]

# Разрешённые бренды/названия (факт-чек: упоминания должны совпадать
# со справочником АС Фарм). Лишние выдуманные названия — повод для проверки.
KNOWN_BRAND = "АС Фарм"
