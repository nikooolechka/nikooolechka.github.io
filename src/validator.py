"""Детерминированная проверка текста ПЕРЕД публикацией.

Возвращает список ошибок (errors) и предупреждений (warnings).
Если есть хоть одна ошибка — пост НЕ публикуется. Это и есть «тесты,
чтобы не было ошибок в текстах»: запускаются и в CI (pytest), и в рантайме
перед каждой отправкой.
"""

from . import config


def validate_post(title: str, body: str):
    errors = []
    warnings = []

    title = (title or "").strip()
    body = (body or "").strip()
    low = body.lower()
    low_title = title.lower()

    # --- Заголовок ---
    if not title:
        errors.append("Пустой заголовок.")
    elif len(title) < config.MIN_TITLE_LEN:
        errors.append(f"Заголовок короче {config.MIN_TITLE_LEN} символов ({len(title)}).")
    elif len(title) > config.MAX_TITLE_LEN:
        errors.append(f"Заголовок длиннее {config.MAX_TITLE_LEN} символов ({len(title)}).")

    # --- Тело ---
    if not body:
        errors.append("Пустой текст поста.")
    elif len(body) < config.MIN_TEXT_LEN:
        errors.append(f"Текст короче {config.MIN_TEXT_LEN} символов ({len(body)}).")
    elif len(body) > config.MAX_TEXT_LEN:
        errors.append(f"Текст длиннее {config.MAX_TEXT_LEN} символов ({len(body)}).")

    # --- Реклама (делает пост рекламой по закону РФ -> нужна маркировка) ---
    for w in config.PROMO_WORDS:
        if w in low or w in low_title:
            errors.append(
                f"Рекламный маркер «{w}»: пост станет рекламой и потребует "
                f"маркировки erid/ИНН. Переформулируй образовательно."
            )

    # --- Ложные/медицинские обещания ---
    for w in config.FALSE_CLAIM_WORDS:
        if w in low or w in low_title:
            errors.append(f"Недопустимое обещание/домысел: «{w}». Только факты.")

    # --- Слоп / вода ---
    for w in config.SLOP_WORDS:
        if w in low:
            warnings.append(f"Штамп-вода: «{w}» — лучше убрать (stop-slop).")

    # --- Технические артефакты генерации ---
    if "  " in body:
        warnings.append("Двойные пробелы в тексте.")
    for marker in ("[", "]", "{{", "}}", "TODO", "lorem ipsum"):
        if marker.lower() in low:
            warnings.append(f"Подозрительный артефакт в тексте: «{marker}».")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
