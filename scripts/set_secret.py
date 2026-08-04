"""Установить/обновить GitHub Actions секрет через API (libsodium sealed box).
Использование: GH_PAT=<token> python scripts/set_secret.py <SECRET_NAME> <value>
Нужен PAT со scope repo (или admin) на репо. Применяется для ротации VC_REFRESH_TOKEN.
"""
import os
import sys
import ssl
import json
import base64
import urllib.request

from nacl import encoding, public

REPO = os.environ.get("SECRET_REPO", "nikooolechka/nikooolechka.github.io")
PAT = os.environ.get("GH_PAT") or os.environ.get("PAT_SECRETS_WRITE")

_CTX = ssl.create_default_context()
try:
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE  # на маке нет локальных сертов; в CI тоже ок
except Exception:
    pass


def _api(path, method="GET", data=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        data=data, method=method,
        headers={"Authorization": f"token {PAT}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "asfarm-set-secret"},
    )
    with urllib.request.urlopen(req, timeout=40, context=_CTX) as r:
        body = r.read()
        return r.status, (json.loads(body) if body else None)


def main():
    if not PAT:
        print("нет PAT (GH_PAT/PAT_SECRETS_WRITE)"); sys.exit(1)
    name, value = sys.argv[1], sys.argv[2]
    _, key = _api("actions/secrets/public-key")
    pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode("utf-8"))
    enc = base64.b64encode(sealed).decode("utf-8")
    body = json.dumps({"encrypted_value": enc, "key_id": key["key_id"]}).encode()
    status, _ = _api(f"actions/secrets/{name}", method="PUT", data=body)
    print(f"секрет {name}: HTTP {status}")


if __name__ == "__main__":
    main()
