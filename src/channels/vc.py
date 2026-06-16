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
_HEADERS = {"Origin": "https://vc.ru", "User-Agent": "Mozilla/5.0", "Referer": "https://vc.ru/"}


def text_block(text: str) -> dict:
    return {"type": "text", "cover": False, "hidden": False, "anchor": "", "data": {"text": text}}


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
        os.makedirs(os.path.dirname(self.creds_path), exist_ok=True)
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

    def publish(self, title: str, text: str, image_path: str = None, links: dict = None) -> dict:
        """Публикует статью. text — на абзацы (\n\n); ссылки добавляются в конец."""
        self._refresh()
        blocks = [text_block(p.strip()) for p in text.split("\n\n") if p.strip()]
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
