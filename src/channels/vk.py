"""Адаптер ВКонтакте (wall.post).

  GET/POST https://api.vk.com/method/wall.post
  params: owner_id (минус = группа), from_group=1, message, access_token, v
Токен — сообщества, с правами wall+manage.
"""

import requests
from .. import config

VK_API = "https://api.vk.com/method/wall.post"


class VKClient:
    def __init__(self, token=None, owner_id=None, version=None):
        self.token = token or config.VK_TOKEN
        self.owner_id = owner_id or config.VK_OWNER_ID
        self.version = version or config.VK_API_VERSION

    def _check_creds(self):
        if not self.token or not self.owner_id:
            raise RuntimeError("VK_TOKEN / VK_OWNER_ID не заданы (см. .env / Secrets).")

    def publish(self, title: str, text: str) -> dict:
        self._check_creds()
        # На стене ВК нет отдельного заголовка — выносим его первой строкой.
        message = f"{title}\n\n{text}".strip()
        params = {
            "owner_id": self.owner_id,
            "from_group": 1,
            "message": message,
            "access_token": self.token,
            "v": self.version,
        }
        r = requests.post(VK_API, data=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"VK API error: {data['error']}")
        post_id = data["response"]["post_id"]
        owner = str(self.owner_id).lstrip("-")
        url = f"https://vk.com/wall-{owner}_{post_id}"
        return {"raw": data, "url": url}
