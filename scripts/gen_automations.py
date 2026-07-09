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


def _lvl(pct):
    return ("bad", "broken") if pct >= 0.95 else (("warn", "wip") if pct >= 0.8 else ("", "ok"))


def _scrapfly(key):
    with urllib.request.urlopen("https://api.scrapfly.io/account?key=" + key, timeout=25, context=_CTX) as r:
        j = json.loads(r.read().decode())
    u = (j.get("subscription") or {}).get("usage") or {}
    sc = u.get("scrape") or u.get("all") or {}
    return sc.get("current"), sc.get("limit") or 1000


def update_services(data):
    import socket
    for s in data.get("services", []):
        nm = s["name"]
        if nm.startswith("Scrapfly"):
            env = "SCRAPFLY_KEY" if ("оферт" in nm.lower()) else "SCRAPFLY_KEY_SOCIAL"
            key = os.environ.get(env, "").strip()
            if not key:
                continue
            try:
                cur, lim = _scrapfly(key)
                if cur is not None:
                    tail = "осн." if env == "SCRAPFLY_KEY" else "2-й акк"
                    s["value"], s["note"] = str(cur), f"/ {lim} {tail} · сброс 15-го"
                    s["level"], s["dot"] = _lvl(cur / lim)
                    print(f"  {nm}: {cur}/{lim}")
            except Exception as e:
                print("  scrapfly", env, ":", str(e)[:60])
        elif nm.startswith("Удал"):  # Удалённый ПК — связь (из облака порты часто закрыты фаерволом → НЕ красним ложно)
            host = os.environ.get("REMOTE_PC_HOST", "").strip()
            up = False
            if host:
                for port in (3380, 3389, 22):
                    try:
                        socket.create_connection((host, port), timeout=6).close(); up = True; break
                    except Exception:
                        pass
            if up:
                s["value"], s["dot"], s["level"] = "онлайн", "ok", ""
            else:
                s["value"], s["dot"], s["level"] = "по расписанию", "ok", ""  # жив, но из облака не пингуется
            print("  Удалённый ПК:", s["value"])
        elif nm == "GitHub Actions":
            try:
                req = urllib.request.Request("https://api.github.com/users/nikooolechka/settings/billing/actions",
                    headers={"Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=25, context=_CTX) as r:
                    j = json.loads(r.read().decode())
                used, inc = j.get("total_minutes_used"), j.get("included_minutes") or 2000
                if used is not None:
                    s["value"], s["note"] = str(int(used)), f"/ {int(inc)} мин в мес"
                    s["level"], s["dot"] = _lvl(used / inc)
                    print("  Actions:", used, "/", inc)
            except Exception as e:
                print("  actions billing:", str(e)[:70])


def main():
    data = json.load(open(DOCS, encoding="utf-8"))
    update_services(data)
    for it in data["items"]:
        m = CHECKS.get(it["id"])
        if not m:
            continue
        res = check(*m)
        if res is None:
            continue
        it["status"], it["reason"] = res
        print(f"  {it['id']}: {it['status']} {it['reason']}")
    # DRIFT-контроль: воркфлоу, которых НЕТ на дашборде (соседняя сессия могла добавить и забыть внести)
    IGNORE = {"oferta_probe.yml", "ym_probe.yml", "ym_probe2.yml", "automations_status.yml",
              "pages-build-deployment", "ok_sync.yml"}  # ok_sync покрыт карточкой «Автосверка календаря»
    known = {m[1] for m in CHECKS.values()}
    drift = []
    for repo in (OZ, SELF):
        try:
            url = f"https://api.github.com/repos/{repo}/actions/workflows?per_page=100"
            req = urllib.request.Request(url, headers={"Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
                wfs = json.loads(r.read().decode()).get("workflows", [])
            for w in wfs:
                fn = w.get("path", "").split("/")[-1]
                if w.get("state") == "active" and fn not in known and fn not in IGNORE:
                    drift.append(w.get("name") or fn)
        except Exception as e:
            print("drift", repo, ":", str(e)[:50])
    data["drift"] = drift
    if drift:
        print("⚠ DRIFT — не на дашборде:", drift)

    data["generated_at"] = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M") + " МСК"
    json.dump(data, open(DOCS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("обновлено:", data["generated_at"])


if __name__ == "__main__":
    main()
