"""Генерация картинок через Cloudflare Workers AI (Flux-1-schnell, бесплатно).

  python3 scripts/gen_cf.py "<prompt>" <output.jpg> [model]

Токен и Account ID — локально в /Users/nikol/Desktop/files/ (не в репо).
"""
import sys, os, json, base64, ssl, urllib.request

FILES = "/Users/nikol/Desktop/files"


def _cred(envname, fname):
    v = os.environ.get(envname)
    if v:
        return v.strip()
    try:
        return open(f"{FILES}/{fname}").read().strip()
    except FileNotFoundError:
        return ""


TOKEN = _cred("CF_TOKEN", "cloudflare_token.txt")
ACCOUNT = _cred("CF_ACCOUNT", "cloudflare_account.txt")
DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_SSL = ssl._create_unverified_context()


def gen(prompt: str, out_path: str, model: str = DEFAULT_MODEL,
        width: int = 1344, height: int = 768) -> str:
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{model}"
    body = json.dumps({"prompt": prompt, "steps": 8, "width": width, "height": height}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120, context=_SSL) as r:
        data = json.load(r)
    if not data.get("success", True):
        raise RuntimeError("CF error: " + json.dumps(data.get("errors"))[:400])
    img_b64 = data.get("result", {}).get("image")
    if not img_b64:
        raise RuntimeError("Нет картинки в ответе: " + json.dumps(data)[:400])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(img_b64))
    return out_path


if __name__ == "__main__":
    prompt, out = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MODEL
    print(gen(prompt, out, model))
