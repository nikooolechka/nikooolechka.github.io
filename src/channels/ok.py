"""Адаптер Одноклассников (OK API) — пост текста с фото в группу.

OK API устроен сложнее ВК: каждый запрос подписывается (sig).
Нужны 4 значения (из аккаунта OK / настроек приложения):
  OK_ACCESS_TOKEN       — токен доступа (с правами VALUABLE_ACCESS, GROUP_CONTENT, PHOTO_CONTENT)
  OK_APP_KEY            — публичный ключ приложения (Application key)
  OK_APP_SECRET         — секретный ключ приложения (Application secret key)
  OK_GROUP_ID           — числовой id группы (gid), куда постим

Подпись (для серверных запросов с access_token):
  secret = md5(access_token + OK_APP_SECRET)
  sig    = md5( "".join(f"{k}={v}" for k,v in sorted(params)) + secret )   # без sig и без access_token
Запрос: POST https://api.ok.ru/fb.do  с параметрами + access_token + sig.

Поток фото-поста в группу:
  1) photosV2.getUploadUrl (gid, count=1) -> upload_url + photo_ids
  2) POST файла на upload_url -> {photos:{<id>:{token:...}}}
  3) mediatopic.post (type=GROUP_THEME, gid, attachment=JSON с media: text + photo по token)

⚠️ Код требует живой проверки с реальными ключами (OK API капризен к подписи и правам).
"""

import os
import json
import hashlib
import requests

from .. import config

API = "https://api.ok.ru/fb.do"


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class OKClient:
    def __init__(self, access_token=None, app_key=None, app_secret=None, group_id=None):
        self.token = access_token or config.OK_ACCESS_TOKEN
        self.app_key = app_key or config.OK_APP_KEY
        self.app_secret = app_secret or config.OK_APP_SECRET
        self.group_id = str(group_id or config.OK_GROUP_ID or "")

    def _check(self):
        if not all([self.token, self.app_key, self.app_secret, self.group_id]):
            raise RuntimeError("OK: не заданы OK_ACCESS_TOKEN / OK_APP_KEY / OK_APP_SECRET / OK_GROUP_ID")

    def _sig(self, params: dict) -> str:
        secret = _md5(self.token + self.app_secret)
        base = "".join(f"{k}={params[k]}" for k in sorted(params))
        return _md5(base + secret)

    def _call(self, method: str, params: dict, http_files=None) -> dict:
        p = {**params, "method": method, "application_key": self.app_key, "format": "json"}
        p["sig"] = self._sig(p)               # sig считается БЕЗ access_token
        p["access_token"] = self.token
        r = requests.post(API, data=p, files=http_files, timeout=60)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("error_code"):
            raise RuntimeError(f"OK API error в {method}: {data}")
        return data

    def _upload_photo(self, image_path: str) -> str:
        up = self._call("photosV2.getUploadUrl", {"gid": self.group_id, "count": "1"})
        upload_url = up["upload_url"]
        with open(image_path, "rb") as f:
            res = requests.post(upload_url, files={"pic1": f}, timeout=120).json()
        photos = res.get("photos") or {}
        # вернётся {"<photo_id>": {"token": "..."}}
        token = next(iter(photos.values()))["token"]
        return token

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

    def publish(self, title: str, text: str, image_path: str = None, links: dict = None) -> dict:
        self._check()
        message = f"{title}\n\n{text}".strip() + self._links_text(links)
        media = [{"type": "text", "text": message}]
        if image_path and os.path.exists(image_path):
            token = self._upload_photo(image_path)
            media.append({"type": "photo", "list": [{"id": token}]})
        attachment = json.dumps({"media": media}, ensure_ascii=False)
        resp = self._call("mediatopic.post", {
            "type": "GROUP_THEME", "gid": self.group_id, "attachment": attachment,
        })
        topic_id = resp if isinstance(resp, (str, int)) else (resp.get("id") if isinstance(resp, dict) else None)
        url = f"https://ok.ru/group/{self.group_id}/topic/{topic_id}" if topic_id else f"https://ok.ru/group/{self.group_id}"
        return {"raw": resp, "url": url}
