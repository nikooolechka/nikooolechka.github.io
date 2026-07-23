"""Адаптер ВКонтакте: пост на стену с картинкой и ссылками.

Картинка прикрепляется ВСЕГДА (требование владельца). Поток загрузки фото:
  photos.getWallUploadServer -> POST файла на upload_url -> photos.saveWallPhoto
  -> attachment вида photo{owner}_{id} -> wall.post(attachments=...).
Внешние ссылки (ВБ/Озон) в ВК нельзя «вшить в слово» — даём текстом, ВК сам
подцепит карточку-превью по первой ссылке.
"""

import requests
from .. import config

VK_API = "https://api.vk.com/method/"


class VKClient:
    def __init__(self, token=None, owner_id=None, version=None):
        self.token = token or config.VK_TOKEN
        self.owner_id = str(owner_id or config.VK_OWNER_ID)
        self.version = version or config.VK_API_VERSION
        self.group_id = self.owner_id.lstrip("-")

    def _check_creds(self):
        if not self.token or not self.owner_id:
            raise RuntimeError("VK_TOKEN / VK_OWNER_ID не заданы (см. .env / Secrets).")

    def _call(self, method: str, params: dict) -> dict:
        params = {**params, "access_token": self.token, "v": self.version}
        r = requests.post(VK_API + method, data=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"VK API error в {method}: {data['error']}")
        return data["response"]

    def _upload_photo(self, image_path: str) -> str:
        import time
        last = ""
        for _ in range(3):
            srv = self._call("photos.getWallUploadServer", {"group_id": self.group_id})
            with open(image_path, "rb") as f:
                # Явные имя файла + content-type: без них VK иногда отдаёт пустое photo.
                up = requests.post(
                    srv["upload_url"],
                    files={"photo": ("image.jpg", f, "image/jpeg")},
                    timeout=120,
                ).json()
            photo = up.get("photo") or ""
            if photo and photo not in ("[]", "null"):
                saved = self._call("photos.saveWallPhoto", {
                    "group_id": self.group_id,
                    "server": up["server"], "photo": photo, "hash": up["hash"],
                })
                ph = saved[0]
                return f"photo{ph['owner_id']}_{ph['id']}"
            last = str(up)
            time.sleep(2)
        raise RuntimeError(f"VK: загрузка фото вернула пустое photo 3 раза: {last[:160]}")

    @staticmethod
    def _links_block(links: dict) -> str:
        if not links:
            return ""
        lines = []
        if links.get("wb"):
            lines.append(f"Wildberries: {links['wb']}")
        if links.get("ozon"):
            lines.append(f"Ozon: {links['ozon']}")
        return ("\n\n" + "\n".join(lines)) if lines else ""

    def posted_today(self) -> bool:
        """Авторитетная анти-дубль проверка: есть ли на стене пост от сегодня (МСК).

        Читает саму стену ВК — источник правды, НЕ зависит от git-состояния.
        Защищает от дубля при любой гонке (потерянный push отметки, лишний прогон).
        Ошибка чтения → False (не блокируем публикацию из-за сбоя API; тогда
        работает запасной механизм — отметка в queue.json).
        """
        from datetime import datetime, timezone, timedelta
        try:
            self._check_creds()
            resp = self._call("wall.get", {
                "owner_id": self.owner_id, "count": 8, "filter": "owner",
            })
            msk = timezone(timedelta(hours=3))
            today = datetime.now(msk).date()
            for it in resp.get("items", []):
                ts = it.get("date")
                if ts and datetime.fromtimestamp(ts, msk).date() == today:
                    return True
            return False
        except Exception as e:
            print(f"vk: не смог прочитать стену для анти-дубль проверки ({e}); "
                  f"полагаюсь на git-отметку.")
            return False

    def publish(self, title: str, text: str, image_path: str = None, links: dict = None) -> dict:
        self._check_creds()
        message = f"{title}\n\n{text}".strip() + self._links_block(links)
        params = {"owner_id": self.owner_id, "from_group": 1, "message": message}
        if image_path:
            params["attachments"] = self._upload_photo(image_path)
        resp = self._call("wall.post", params)
        post_id = resp["post_id"]
        url = f"https://vk.com/wall{self.owner_id}_{post_id}"
        return {"raw": resp, "url": url}
