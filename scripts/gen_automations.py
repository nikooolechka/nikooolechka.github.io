#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Обновляет реальные статусы автоматизаций в docs/automations.json.
Проверяет последние прогоны воркфлоу через GitHub API. Если упало — пишет причину.
Запускается 2×/день (07:00 и 19:00 МСК). Секрет: STATUS_PAT (repo-scope, оба репо)."""
import os, ssl, json, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

_CTX = ssl.create_default_context()
try:
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE  # на маке бывает CERTIFICATE_VERIFY_FAILED; в CI не мешает
except Exception:
    pass

TOKEN = os.environ.get("STATUS_PAT", "").strip()
OZ = "nikooolechka/wb-oz-monitor"
SELF = "nikooolechka/nikooolechka.github.io"
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs", "automations.json")

# id -> (repo, файл воркфлоу, макс. возраст успешного прогона в часах)
CHECKS = {
    "price_wb":        (OZ, "wb_prices.yml", 30),
    "price_watchdog":  (OZ, "price_watchdog.yml", 20),
    "reviews_weekly":  (OZ, "wb_reviews_weekly.yml", 200),
    "reviews_archive": (OZ, "wb_reviews_weekly.yml", 200),
    "plesen":          (OZ, "plesen_monitor.yml", 150),
    "oferta":          (OZ, "check.yml", 30),
    "gab_unit":        (OZ, "gabariti_monitor.yml", 4),
    "gab_oz_card":     (OZ, "oz_gabariti_monitor.yml", 30),
    "gab_wb":          (OZ, "wb_gabariti_monitor.yml", 200),
    "wb_pnl":          (OZ, "wb_pnl.yml", 30),
    "recipes":         (OZ, "recipes_1c.yml", 200),
    "posts_digest":    (OZ, "posts.yml", 30),
    "poster_watchdog": (OZ, "poster_sync_watchdog.yml", 30),
    "poster":          (SELF, "main.yml", 30),
    "calendar_sync":   (SELF, "main.yml", 30),
}


def latest_run(repo, wf):
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page=1"
    req = urllib.request.Request(url, headers={
        "Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
        runs = (json.loads(r.read().decode()).get("workflow_runs") or [])
    return runs[0] if runs else None


def check(repo, wf, max_age_h):
    try:
        run = latest_run(repo, wf)
    except Exception as e:
        print("  ошибка проверки", wf, str(e)[:60])
        return None  # не трогаем прежний статус
    if not run:
        return ("wip", "ещё ни разу не запускалась")
    concl = run.get("conclusion")
    when = run.get("run_started_at") or run.get("updated_at")
    try:
        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except Exception:
        dt = None
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600 if dt else 1e9
    dstr = (dt + timedelta(hours=3)).strftime("%d.%m %H:%M") if dt else "?"
    if concl in ("failure", "timed_out", "startup_failure"):
        return ("broken", f"последний прогон {dstr} завершился ошибкой")
    if concl == "cancelled":
        return ("broken", f"последний прогон {dstr} отменён")
    if concl == "success":
        if age_h > max_age_h:
            return ("broken", f"давно не запускалась (последний успешный {dstr})")
        return ("ok", "")
    return None  # in_progress / queued — оставляем как было


def main():
    data = json.load(open(DOCS, encoding="utf-8"))
    for it in data["items"]:
        m = CHECKS.get(it["id"])
        if not m:
            continue
        res = check(*m)
        if res is None:
            continue
        it["status"], it["reason"] = res
        print(f"  {it['id']}: {it['status']} {it['reason']}")
    data["generated_at"] = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M") + " МСК"
    json.dump(data, open(DOCS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("обновлено:", data["generated_at"])


if __name__ == "__main__":
    main()
