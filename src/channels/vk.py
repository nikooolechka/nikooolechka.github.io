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
        srv = self._call("photos.getWallUploadServer", {"group_id": self.group_id})
        with open(image_path, "rb") as f:
            up = requests.post(srv["upload_url"], files={"photo": f}, timeout=120).json()
        saved = self._call("photos.saveWallPhoto", {
            "group_id": self.group_id,
            "server": up["server"], "photo": up["photo"], "hash": up["hash"],
        })
        ph = saved[0]
        return f"photo{ph['owner_id']}_{ph['id']}"

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
