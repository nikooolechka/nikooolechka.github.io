"""Генерация обложек через Gemini image API (Nano Banana).

Использование:
  python3 scripts/gen_image.py "<prompt>" <output.png> [model]

Ключ читается из /Users/nikol/Desktop/files/gemini_key.txt (локально, не в репо).
"""
import sys, os, json, base64, ssl, urllib.request

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl._create_unverified_context()

KEY_PATH = "/Users/nikol/Desktop/files/gemini_key.txt"
DEFAULT_MODEL = "gemini-2.5-flash-image"


def gen(prompt: str, out_path: str, model: str = DEFAULT_MODEL) -> str:
    key = open(KEY_PATH).read().strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120, context=_SSL) as r:
        data = json.load(r)

    cand = (data.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    for p in parts:
        inline = p.get("inlineData") or p.get("inline_data")
        if inline and inline.get("data"):
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(inline["data"]))
            return out_path
    # картинки нет — покажем, что вернула модель
    raise RuntimeError("Нет изображения в ответе: " + json.dumps(data)[:800])


if __name__ == "__main__":
    prompt, out = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MODEL
    print(gen(prompt, out, model))
