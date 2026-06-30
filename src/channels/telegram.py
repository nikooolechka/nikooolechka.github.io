"""Адаптер Telegram: пост в канал бренда через Bot API.

Самый надёжный канал: Bot API — обычные HTTPS-запросы, без антибота и браузера.
Картинка прикрепляется всегда (sendPhoto с подписью). Если текст длиннее лимита
подписи Telegram (1024 символа) — отправляем фото с короткой подписью, а полный
текст следом отдельным сообщением.

Нужно два значения (env / GitHub Secrets):
  TELEGRAM_BOT_TOKEN  — токен бота от @BotFather (вида 123456:ABC-...)
  TELEGRAM_CHANNEL    — канал: @username или числовой chat_id (-100...).
Бот должен быть АДМИНОМ канала с правом публикации.
"""

import os
import requests

from .. import config

CAPTION_LIMIT = 1024


class TelegramClient:
    def __init__(self, token=None, channel=None):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.channel = str(channel or config.TELEGRAM_CHANNEL or "")

    def _check(self):
        if not self.token or not self.channel:
            raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL не заданы (см. .env / Secrets).")

    def _api(self, method: str, data: dict, files=None) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        r = requests.post(url, data=data, files=files, timeout=60)
        payload = r.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error в {method}: {payload}")
        return payload["result"]

    @staticmethod
    def _links_text(links: dict) -> str:
        if not links:
            return ""
        out = []
        if links.get("wb"):
            out.append(f"Wildberries: {links['wb']}")
        if links.get("ozon"):
            out.append(f"Ozon: {links['ozon']}")
        return ("\n\n" + "\n".join(out)) if out else ""

    def _post_url(self, msg: dict) -> str:
        ch = self.channel.lstrip("@")
        mid = msg.get("message_id") if isinstance(msg, dict) else None
        if ch and not ch.lstrip("-").isdigit() and mid:
            return f"https://t.me/{ch}/{mid}"
        return f"https://t.me/{ch}" if ch else ""

    def publish(self, title: str, text: str, image_path: str = None, links: dict = None) -> dict:
        self._check()
        full = f"{title}\n\n{text}".strip() + self._links_text(links)
        if image_path and os.path.exists(image_path):
            if len(full) <= CAPTION_LIMIT:
                with open(image_path, "rb") as f:
                    res = self._api("sendPhoto",
                                    {"chat_id": self.channel, "caption": full},
                                    files={"photo": ("image.jpg", f, "image/jpeg")})
                return {"raw": res, "url": self._post_url(res)}
            # длинный текст: фото с заголовком-подписью + полный текст отдельным сообщением
            with open(image_path, "rb") as f:
                res = self._api("sendPhoto",
                                {"chat_id": self.channel, "caption": title.strip()},
                                files={"photo": ("image.jpg", f, "image/jpeg")})
            self._api("sendMessage",
                      {"chat_id": self.channel, "text": text.strip() + self._links_text(links),
                       "disable_web_page_preview": False})
            return {"raw": res, "url": self._post_url(res)}
        res = self._api("sendMessage", {"chat_id": self.channel, "text": full})
        return {"raw": res, "url": self._post_url(res)}
