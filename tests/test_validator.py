"""Тесты валидатора — это и есть «проверка, чтобы не было ошибок в текстах».
Гоняются в CI перед каждой публикацией."""

from src import validator

GOOD_TITLE = "Уход за полостью рта: с чего начать новичку"
GOOD_BODY = (
    "Полость рта — это не только зубы, но и дёсны, язык и межзубные промежутки. "
    "Налёт скапливается не только на эмали, поэтому одной щётки часто мало.\n\n"
    "Язык стоит мягко очищать утром и вечером — это влияет на свежесть дыхания. "
    "Межзубные промежутки закрывают нить, ёршики или ополаскиватель.\n\n"
    "Регулярность тут важнее, чем выбор конкретного средства: система привычек "
    "даёт более стабильный результат, чем разовые усилия раз в неделю."
)


def test_good_post_passes():
    res = validator.validate_post(GOOD_TITLE, GOOD_BODY)
    assert res["ok"], res["errors"]


def test_promo_word_fails():
    body = GOOD_BODY + "\n\nКупить со скидкой можно по ссылке в профиле."
    res = validator.validate_post(GOOD_TITLE, body)
    assert not res["ok"]
    assert any("Рекламный маркер" in e for e in res["errors"])


def test_medical_claim_fails():
    body = GOOD_BODY + "\n\nЭто средство гарантированно вылечит любые проблемы."
    res = validator.validate_post(GOOD_TITLE, body)
    assert not res["ok"]
    assert any("обещание" in e.lower() for e in res["errors"])


def test_too_short_fails():
    res = validator.validate_post(GOOD_TITLE, "Короткий текст.")
    assert not res["ok"]


def test_empty_title_fails():
    res = validator.validate_post("", GOOD_BODY)
    assert not res["ok"]


def test_slop_is_warning_not_error():
    body = "В современном мире " + GOOD_BODY
    res = validator.validate_post(GOOD_TITLE, body)
    assert res["ok"]  # слоп — предупреждение, не блокирует
    assert res["warnings"]
