"""Адаптер VC (Osnova API).

Эндпоинт и поля подтверждены по рабочему врапперу cmtt-python-wrapper:
  POST https://api.{platform}.ru/v{version}/entry/create
  form-data: title, text, subsite_id
  header:    X-Device-Token
Лимит бесплатного аккаунта VC — ~1 публикация в месяц.
"""

import requests
from .. import config


class VCClient:
    def __init__(self, token=None, subsite_id=None, platform=None, version=None):
        self.token = token or config.VC_TOKEN
        self.subsite_id = subsite_id or config.VC_SUBSITE_ID
        self.platform = platform or config.VC_PLATFORM
        self.version = version or config.VC_API_VERSION
        self.base = f"https://api.{self.platform}.ru/v{self.version}"
        self.headers = {"X-Device-Token": self.token, "User-Agent": config.USER_AGENT}

    def _check_creds(self):
        if not self.token or not self.subsite_id:
            raise RuntimeError("VC_TOKEN / VC_SUBSITE_ID не заданы (см. .env / Secrets).")

    def whoami(self):
        """Проверка токена без публикации."""
        self._check_creds()
        r = requests.get(f"{self.base}/user/me", headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def publish(self, title: str, text: str) -> dict:
        self._check_creds()
        r = requests.post(
            f"{self.base}/entry/create",
            headers=self.headers,
            data={"title": title, "text": text, "subsite_id": self.subsite_id},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        result = data.get("result", data)
        url = result.get("url") if isinstance(result, dict) else None
        return {"raw": data, "url": url}
