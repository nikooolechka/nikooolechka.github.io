"""Адаптер VC (vc.ru / Osnova) — durable-доступ через refresh-токен.

Авторизация (разгадано 2026-06-16, см. CLAUDE.md):
- короткий JWT (5 мин) + долгий refresh-токен RT (одноразовый, ротируется, ~60 дней);
- обновление: POST https://api.vc.ru/v3.4/auth/refresh, form `token=<RT>`
  → {"data":{"accessToken":"<JWT>","refreshToken":"<новый RT>", ...}}; новый RT СОХРАНЯТЬ;
- запросы: заголовок `JWTAuthorization: Bearer <JWT>`;
- публикация: POST https://api.vc.ru/v2.31/editor, form `entry=<JSON>`, где блоки
  ВЛОЖЕНЫ в entry.entry.blocks. Текстовый блок:
  {"type":"text","cover":false,"hidden":false,"anchor":"","data":{"text":"..."}}.

⚠️ RT нельзя хранить в публичном репо. Берётся из VC_REFRESH_TOKEN (env) или из
локального файла creds; после обмена новый RT персистится туда же.
"""

import os
import json
import requests
from .. import config

API = "https://api.vc.ru"
REFRESH_URL = f"{API}/v3.4/auth/refresh"
EDITOR_URL = f"{API}/v2.31/editor"
UPLOAD_URL = "https://upload.vc.ru/v2.8/uploader/upload"
_HEADERS = {"Origin": "https://vc.ru", "User-Agent": "Mozilla/5.0", "Referer": "https://vc.ru/"}

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".gif": "image/gif", ".webp": "image/webp"}


def text_block(text: str) -> dict:
    return {"type": "text", "cover": False, "hidden": False, "anchor": "", "data": {"text": text}}


def header_block(text: str, level: str = "h2") -> dict:
    return {"type": "header", "cover": False, "hidden": False, "anchor": "",
            "data": {"style": level, "text": text}}


def para_block(p: str) -> dict:
    """Текст или заголовок — определяет по префиксу ##/###."""
    if p.startswith("### "):
        return header_block(p[4:].strip(), "h3")
    if p.startswith("## "):
        return header_block(p[3:].strip(), "h2")
    return text_block(p)


def media_block(image_obj: dict) -> dict:
    return {"type": "media", "cover": False, "hidden": False, "anchor": "",
            "data": {"items": [{"title": "", "image": image_obj}], "size": "full"}}


class VCClient:
    def __init__(self, refresh_token=None, subsite_id=None, creds_path=None):
        self.creds_path = creds_path or config.VC_CREDS_PATH
        self.subsite_id = int(subsite_id or config.VC_SUBSITE_ID or 0)
        self.rt = refresh_token or config.VC_REFRESH_TOKEN or self._read_rt()
        self.jwt = None

    # --- хранение/ротация RT ---
    def _read_rt(self):
        try:
            for line in open(self.creds_path):
                if line.startswith("refresh-token="):
                    return line.split("=", 1)[1].strip()
        except FileNotFoundError:
            pass
        return ""

    def _save_rt(self, new_rt, exp=None):
        if not self.creds_path:
            return
        d = os.path.dirname(self.creds_path)
        if d:  # для голого имени файла (напр. vc_creds_ci.txt в CI) dirname='' → makedirs('') падает
            os.makedirs(d, exist_ok=True)
        with open(self.creds_path, "w") as f:
            f.write(f"subsite_id={self.subsite_id}\nrefresh-token={new_rt}\nrefresh-exp={exp or ''}\n")

    def _check(self):
        if not self.rt or not self.subsite_id:
            raise RuntimeError("VC: нет refresh-токена или subsite_id (см. VC_REFRESH_TOKEN / creds).")

    def _refresh(self):
        """RT -> свежий JWT, ротирует и сохраняет новый RT."""
        self._check()
        r = requests.post(REFRESH_URL, headers=_HEADERS, files={"token": (None, self.rt)}, timeout=40)
        r.raise_for_status()
        data = r.json().get("data") or {}
        if not data.get("accessToken"):
            raise RuntimeError(f"VC refresh не дал токен: {r.text[:200]}")
        self.jwt = data["accessToken"]
        self.rt = data["refreshToken"]                       # RT проротировался
        self._save_rt(self.rt, data.get("refreshExpTimestamp"))
        return self.jwt

    def upload_image(self, image_path: str) -> dict:
        """Загружает файл на upload.vc.ru, возвращает image-объект для media_block."""
        if not self.jwt:
            self._refresh()
        ext = os.path.splitext(image_path)[1].lower()
        mime = _MIME.get(ext, "image/jpeg")
        with open(image_path, "rb") as f:
            r = requests.post(
                UPLOAD_URL,
                headers={**_HEADERS, "JWTAuthorization": f"Bearer {self.jwt}"},
                files={"file": (os.path.basename(image_path), f, mime)},
                timeout=60,
            )
        r.raise_for_status()
        data = r.json()
        # API отдаёт либо {"result":[image_obj,...]} либо сам список
        result = data.get("result") if isinstance(data, dict) else data
        if isinstance(result, list):
            return result[0]
        return result

    def publish(self, title: str, text: str, image_path: str = None, links: dict = None) -> dict:
        """Публикует статью. text — на абзацы (\n\n); image_path — вставляется после первого абзаца."""
        self._refresh()
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        blocks: list[dict] = []

        # Первый абзац
        if paragraphs:
            blocks.append(para_block(paragraphs[0]))

        # Картинка после первого абзаца
        if image_path and os.path.exists(image_path):
            image_obj = self.upload_image(image_path)
            blocks.append(media_block(image_obj))

        # Остальные абзацы
        for p in paragraphs[1:]:
            blocks.append(para_block(p))

        if links:
            tail = []
            if links.get("wb"):
                tail.append(f"Wildberries: {links['wb']}")
            if links.get("ozon"):
                tail.append(f"Ozon: {links['ozon']}")
            if tail:
                blocks.append(text_block("\n".join(tail)))
        entry = {
            "id": 0, "user_id": self.subsite_id, "type": 1, "subsite_id": self.subsite_id,
            "title": title, "entry": {"blocks": blocks},
            "external_access_link": "", "path": None, "is_editorial": False,
            "is_advertisement": False, "is_enabled_comments": True, "is_enabled_likes": True,
            "withheld": False, "is_enabled_ad": True, "is_holdonflash": False,
            "forced_to_mainpage": 0, "is_holdonmain": False, "is_published": True,
            "is_adult": False, "repostId": None, "repostData": None,
        }
        r = requests.post(
            EDITOR_URL,
            headers={**_HEADERS, "JWTAuthorization": f"Bearer {self.jwt}"},
            files={"entry": (None, json.dumps(entry, ensure_ascii=False))},
            timeout=60,
        )
        r.raise_for_status()
        e = (r.json().get("result") or {}).get("entry") or {}
        return {"raw": r.json(), "url": e.get("url")}
