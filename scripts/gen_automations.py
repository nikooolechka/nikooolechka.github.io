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
    # WB positions are orchestrated by n8n; the old GitHub workflow is disabled.
    "oz_reviews_weekly": (OZ, "oz_reviews_weekly.yml", 200),
    "oferta":          (OZ, "check.yml", 30),
    "gab_wb":          (OZ, "wb_gabariti_monitor.yml", 200),
    "recipes":         (OZ, "recipes_1c.yml", 200),
    "posts_digest":    (OZ, "posts.yml", 30),
    "poster":          (SELF, "main.yml", 30),
    "fbs_kazan":       (OZ, "fbs_kazan_monitor.yml", 30),
    "uderzhaniya_monitor": (OZ, "uderzhaniya_monitor.yml", 30),
    "prices_snapshot_chat": (OZ, "price_screenshot.yml", 30),
    "calendar_sync":   (SELF, "main.yml", 30),
    "stock_1c_alerts":       (OZ, "ostatki_monitor.yml", 30),
    "wb_ff_lowstock":        (OZ, "wb_ff_lowstock.yml", 30),
    "wb_paid_storage":       (OZ, "wb_paid_storage_watch.yml", 200),
}


def _gh(url):
    req = urllib.request.Request(url, headers={
        "Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
        return json.loads(r.read().decode())


def last_runs(repo, wf, n=8):
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page={n}"
    req = urllib.request.Request(url, headers={
        "Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
        return (json.loads(r.read().decode()).get("workflow_runs") or [])


def _age(run):
    when = run.get("run_started_at") or run.get("updated_at")
    try:
        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except Exception:
        return None, 1e9, "?"
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return dt, age_h, (dt + timedelta(hours=3)).strftime("%d.%m %H:%M")


def check(repo, wf, max_age_h):
    # Смотрим НЕ только последний прогон, а последние N: если был УСПЕШНЫЙ прогон
    # в пределах расписания (max_age_h) — карточка ok, даже если позже случился
    # транзиентный сбой или ретрай упал (напр. 3 прогона/день у сводок, Google 503).
    try:
        runs = last_runs(repo, wf, 8)
    except Exception as e:
        print("  ошибка проверки", wf, str(e)[:60])
        return None  # не трогаем прежний статус
    if not runs:
        return ("wip", "ещё ни разу не запускалась")
    for run in runs:  # newest-first
        if run.get("conclusion") == "success":
            _, age_h, dstr = _age(run)
            if age_h <= max_age_h:
                return ("ok", "")
            return ("broken", f"давно не запускалась (последний успешный {dstr})")
    # ни одного успеха среди последних N — берём последний прогон для причины
    concl = runs[0].get("conclusion")
    _, _, dstr = _age(runs[0])
    if concl in ("failure", "timed_out", "startup_failure"):
        return ("broken", f"последний прогон {dstr} завершился ошибкой")
    if concl == "cancelled":
        return ("broken", f"последний прогон {dstr} отменён")
    return None  # in_progress / queued без прежних успехов — оставляем как было


def _lvl(pct):
    return ("bad", "broken") if pct >= 0.95 else (("warn", "wip") if pct >= 0.8 else ("", "ok"))


def _scrapfly(key):
    with urllib.request.urlopen("https://api.scrapfly.io/account?key=" + key, timeout=25, context=_CTX) as r:
        j = json.loads(r.read().decode())
    u = (j.get("subscription") or {}).get("usage") or {}
    sc = u.get("scrape") or u.get("all") or {}
    return sc.get("current"), sc.get("limit") or 1000


def _railway_cost(tok, ws):
    # Read queries only. Workspace tokens themselves also permit mutations.
    import math
    q = ('query{workspace(workspaceId:"%s"){plan customer{currentUsage '
         'billingPeriod{start end} usageLimit{hardLimit softLimit} '
         'subscriptions{status nextInvoiceCurrentTotal}}} '
         'estimatedUsage(workspaceId:"%s",includeDeleted:true,'
         'measurements:[MEMORY_USAGE_GB,CPU_USAGE,NETWORK_TX_GB,DISK_USAGE_GB,BACKUP_USAGE_GB])'
         '{measurement estimatedValue}}') % (ws, ws)
    req = urllib.request.Request(
        "https://backboard.railway.com/graphql/v2",
        data=json.dumps({"query": q}).encode(),
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (dashboard usage reader)"})
    with urllib.request.urlopen(req, timeout=25, context=_CTX) as r:
        d = json.loads(r.read().decode())
    if d.get("errors"):
        raise RuntimeError("Railway API rejected usage query")
    body = d.get("data") or {}
    rows = body.get("estimatedUsage")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Railway usage measurements unavailable")
    # 30-day tariff month, not the length of this customer's billing cycle.
    # GB-min / vCPU-min and egress GB. Backups use volume pricing.
    rates = {"MEMORY_USAGE_GB": 10.0 / 43200, "CPU_USAGE": 20.0 / 43200,
             "NETWORK_TX_GB": 0.05, "DISK_USAGE_GB": 0.15 / 43200,
             "BACKUP_USAGE_GB": 0.15 / 43200}
    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise RuntimeError("Invalid Railway billing value")
        return value
    forecast = 0.0
    for x in rows:
        measurement = x.get("measurement")
        if measurement not in rates:
            raise RuntimeError("Unsupported Railway billing measurement")
        forecast += number(x.get("estimatedValue")) * rates[measurement]
    if not {"MEMORY_USAGE_GB", "CPU_USAGE"}.issubset({x.get("measurement") for x in rows}):
        raise RuntimeError("Incomplete Railway usage measurements")
    workspace = body.get("workspace") or {}
    customer = workspace.get("customer") or {}
    subscriptions = [x for x in customer.get("subscriptions", []) if x.get("status") == "active"]
    if not subscriptions or not workspace.get("plan"):
        raise RuntimeError("Railway subscription data unavailable")
    return {"forecast": forecast, "current": number(customer.get("currentUsage")),
            "invoice": sum(number(x.get("nextInvoiceCurrentTotal")) for x in subscriptions) / 100.0,
            "plan": workspace["plan"].capitalize(), "period": customer.get("billingPeriod"),
            "limit": (customer.get("usageLimit") or {}).get("hardLimit")}


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
        elif nm.startswith("Railway"):  # Счёт API и ресурсы показываем отдельно
            tok = os.environ.get("RAILWAY_TOKEN", "").strip()
            try:
                if not tok:
                    raise RuntimeError("Railway token missing")
                bill = _railway_cost(tok, "f77f76b2-43eb-48cb-b885-f260662b0eeb")
                s["value"] = f"${bill['invoice']:.2f} счёт"
                limit = bill["limit"]
                limit_note = f"лимит ${limit:g}" if limit is not None else "без жёсткого лимита"
                s["note"] = (f"{bill['plan']} · ресурсы ${bill['current']:.2f} · "
                             f"прогноз ~${bill['forecast']:.2f} · {limit_note}")
                s["level"], s["dot"] = _lvl(bill["forecast"] / (limit or 5.0))
                print(f"  Railway: счёт ${bill['invoice']:.2f}; ресурсы ~${bill['forecast']:.2f}")
            except Exception as e:
                s["value"] = "расход не проверен"
                s["note"] = "нет подтверждённых данных API · Hobby $5/мес"
                s["level"], s["dot"] = "warn", "wip"
                print("  railway:", str(e)[:80])
        elif nm.startswith("Cloudflare"):  # Workers free 100k/сут — приёмник+сторож остатков (не Яндекс/GitHub)
            tok = os.environ.get("CF_TOKEN", "").strip(); acc = os.environ.get("CF_ACCOUNT", "").strip()
            if not (tok and acc):
                continue
            try:
                import datetime as _dt
                q = {"query": "query($acc:String!,$d:String!){viewer{accounts(filter:{accountTag:$acc}){workersInvocationsAdaptive(limit:100,filter:{date:$d}){sum{requests}}}}}",
                     "variables": {"acc": acc, "d": _dt.date.today().isoformat()}}
                req = urllib.request.Request("https://api.cloudflare.com/client/v4/graphql", data=json.dumps(q).encode(),
                        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, context=_CTX, timeout=20).read())
                tot = sum(x["sum"]["requests"] for a in r["data"]["viewer"]["accounts"] for x in a["workersInvocationsAdaptive"])
                s["value"] = f"{tot} / 100k"; s["note"] = "Workers · приёмник+сторож остатков · /сут"
                s["level"], s["dot"] = _lvl(tot / 100000.0)
                print(f"  Cloudflare: {tot}/100k запросов сегодня")
            except Exception as e:
                print("  cloudflare:", str(e)[:80])
        elif nm.startswith("Удал"):  # Удалённый ПК — связь (из облака порты часто закрыты фаерволом → НЕ красним ложно)
            try:
                from google.oauth2 import service_account
                from google.auth.transport.requests import Request
                from zoneinfo import ZoneInfo
                import re as _re
                sa=json.loads(os.environ['GSHEETS_SA_JSON'])
                creds=service_account.Credentials.from_service_account_info(sa,scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
                creds.refresh(Request())
                u='https://sheets.googleapis.com/v4/spreadsheets/1Gz0zU-fT34Tr3LG-WSMZFVy5sgAFgjyC880_79S3Wms/values/'+urllib.parse.quote('Лист1!A4:C4')
                req=urllib.request.Request(u,headers={'Authorization':'Bearer '+creds.token})
                with urllib.request.urlopen(req,timeout=20,context=_CTX)as r: cells=json.loads(r.read()).get('values',[[]])[0]
                states=[]
                now=datetime.now(ZoneInfo('Europe/Moscow'))
                for name,index in [('AF-BOT',2),('Lazareva',0)]:
                    v=str(cells[index]if len(cells)>index else'')
                    m=_re.search(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})',v)
                    stamp=datetime.fromisoformat(m.group(1)+'T'+m.group(2)).replace(tzinfo=ZoneInfo('Europe/Moscow'))if m else None
                    age=(now-stamp).total_seconds()if stamp else None
                    states.append((name,age is not None and -30<=age<=600))
                s['value']=' · '.join(name+(': на связи'if live else': нет свежего сигнала')for name,live in states)
                s['note']='Сигналы агентов C4/A4, до 10 минут. AF-BOT основной, Lazareva резерв; это не проверка формы 1С.'
                s['dot'],s['level']=('ok','')if all(live for _,live in states)else('wip','warn')
            except Exception:
                s['value'],s['dot'],s['level']='связь не подтверждена','wip','warn'
            print('  Удалённые ПК:',s['value'])
        elif nm.startswith("Anthropic"):  # у Anthropic нет API остатка баланса → живой пинг: ключ отвечает / кредиты кончились
            key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not key:
                continue
            req=urllib.request.Request("https://api.anthropic.com/v1/models",headers={"x-api-key":key,"anthropic-version":"2023-06-01"})
            try:
                with urllib.request.urlopen(req,timeout=25,context=_CTX)as r: models=json.loads(r.read())
                if not isinstance(models.get('data'),list):raise ValueError('Invalid models response')
                s['value'],s['note']='API доступен','авторизация проверена; остаток кредитов API не раскрывает'
                s['dot'],s['level']='ok',''
            except Exception:
                s['value'],s['note']='доступ не подтверждён','проверка авторизации не прошла; причина в журнале'
                s['dot'],s['level']='wip','warn'
        elif nm == "GitHub Actions":
            # GitHub убил billing-эндпоинт (404). Считаем сами: сумма длительностей
            # прогонов ПРИВАТНЫХ репо за текущий месяц, каждый округляем вверх до минуты
            # (публичные репо — Actions бесплатны, в лимит 2000 не идут).
            try:
                import math
                inc = 2000
                ms = datetime.now(timezone.utc).strftime("%Y-%m-01")
                used = 0
                for repo in (OZ, SELF):
                    ri = _gh(f"https://api.github.com/repos/{repo}")
                    if not ri.get("private"):
                        continue
                    page = 1
                    while True:
                        d = _gh(f"https://api.github.com/repos/{repo}/actions/runs"
                                f"?created=%3E%3D{ms}&per_page=100&page={page}")
                        runs = d.get("workflow_runs", [])
                        if not runs:
                            break
                        for r in runs:
                            st, en = r.get("run_started_at"), r.get("updated_at")
                            try:
                                a = datetime.fromisoformat(st.replace("Z", "+00:00"))
                                b = datetime.fromisoformat(en.replace("Z", "+00:00"))
                                if b > a:
                                    used += max(1, math.ceil((b - a).total_seconds() / 60))
                            except Exception:
                                pass
                        if len(runs) < 100:
                            break
                        page += 1
                if used == 0:  # все репо публичны → Actions бесплатны и безлимитны
                    s["value"], s["note"] = "безлимит", "оба репо публичны — Actions бесплатны"
                    s["level"], s["dot"] = "", "ok"
                else:
                    s["value"], s["note"] = str(used), f"/ {inc} мин в мес"
                    s["level"], s["dot"] = _lvl(used / inc)
                print("  Actions:", used, "/", inc)
            except Exception as e:
                print("  actions calc:", str(e)[:70])


def update_continuity_archive(data):
    """Check the actual private weekly archive, without model or Railway calls."""
    import base64
    item = next((x for x in data.get('items', []) if x.get('id') == 'codex_continuity_archive'), None)
    if item is None or item.get('status') == 'paused':
        return
    try:
        response = _gh('https://api.github.com/repos/nikooolechka/asfarm-insurance/contents/history/last_backup.json?ref=main')
        backup = json.loads(base64.b64decode(response['content']))
        when = datetime.fromisoformat(backup['captured_at'])
        age = (datetime.now(timezone.utc) - when).total_seconds() / 86400
        manifests = backup.get('verification') or {}
        if backup.get('branch') != 'main' or backup.get('format') != 'asfarm-unified-archive-v1':
            raise ValueError('не подтверждено объединение архива')
        if not backup.get('complete') or not manifests or not any(k.startswith('manifests/mac/') for k in manifests):
            raise ValueError('неполный архив')
        if age < -1:
            raise ValueError('неверная дата архива')
        stamp = when.astimezone(timezone(timedelta(hours=3))).strftime('%d.%m %H:%M')
        item['status'] = 'ok' if age <= 9 else 'broken'
        item['reason'] = ('Архив проверен ' + stamp + ' МСК · ' + str(len(manifests)) + ' снимка') if age <= 9 else ('Недельный архив просрочен: последний ' + stamp + ' МСК')
    except Exception:
        item['status'] = 'broken'
        item['reason'] = 'Не удалось проверить приватный архив; свежесть не подтверждена'



N8N_CHECKS = {'price_wb': ['eOJAWTlgXtZBwIPJ', 3], 'price_watchdog': ['4XHP8gqRcTWGR8LZ', 30], 'unanswered_qa_monitor': ['R8x57gHdbp4A7RYD', 4], 'reviews_weekly': ['3oxxCbBaLIT6ITQL', 28], 'reviews_archive': ['3oxxCbBaLIT6ITQL', 28], 'gab_unit': ['dSxunW3dt5TpcNZb', 7], 'gab_oz_card': ['SjwRoQCRBllf8om0', 30], 'arrivals': ['jEn2seCVh1XlqkVc', 30], 'dategot_sync_n8n_20261119': ['dXJlpENkRQ0CEpda', 3], 'mail_forward_n8n_20261119': ['LxAAMuHLDsrvyJoi', 1], 'ga_claims_mail': ['LxAAMuHLDsrvyJoi', 1], 'ga_cert_monitor': ['dwiak6nGkkFx7JdZ', 200], 'ga_offer': ['tqALHHSSHHdXf929', 3], 'ga_report_alert': ['ubPaNtrpARTtkc5U', 4], 'ga_notifications_monitor': ['Lv6Q6eKBi5na3FHk', 1], 'ga_cards_status_monitor': ['XnZojrVU76Ato8Qk', 30], 'ga_parity_monitor': ['ekU6bakxvo704Zzq', 30], 'newcomers_monitor': ['O2CQYfWAgZSlwUJk', 30], 'plesen': ['8LMzBViIfuBqbxQO', 150], 'dm_prices': ['fkl7F5jB2uJHIRwb', 30], 'price_history_n8n_20261119': ['JIGzZSPtaMRT4gbF', 30], 'wb_search_positions': ['pVe3jJdcr0Kse1cF', 28], 'oz_search_positions': ['oW0mLAopPBkYTHf3', 24], 'search_positions_watchdog_20261119': ['9WgDdRI7W6ygT8gh', 1], 'analyst_queue_n8n_20261119': ['doTPqr80gnQu7qyo', 1], 'content_monitor_n8n_20261119': ['5KPVaUzt4GZw1o2X', 30], 'automation_result_guard_20261119': ['DxZZMkujxtn9gh1i', 1]}
def n8n_api(path):
    key=os.environ.get('N8N_API_KEY','').strip()
    if not key:raise RuntimeError('Missing n8n access')
    req=urllib.request.Request(os.environ.get('N8N_BASE','http://82.148.225.41:5678/api/v1/')+path,headers={'X-N8N-API-KEY':key})
    with urllib.request.urlopen(req,timeout=25,context=_CTX)as r:return json.loads(r.read())
def n8n_result_error(ex):
    rd=ex.get('data',{}).get('resultData',{})
    if ex.get('status')!='success' or rd.get('error'):return 'прогон завершился ошибкой'
    last=rd.get('lastNodeExecuted');runs=rd.get('runData',{})
    for name,attempts in runs.items():
        if name!=last and not any('stdout'in (i.get('json')or{})for a in attempts for branch in a.get('data',{}).get('main',[])for i in (branch or[])):continue
        for a in attempts:
            if a.get('error'):return 'ошибка узла '+name
            for branch in a.get('data',{}).get('main',[]):
                for item in branch or[]:
                    j=item.get('json')or{}
                    if 'stdout'in j:
                        try:j=json.loads(j['stdout'])
                        except Exception:continue
                    if j.get('ok')is False or j.get('error')or j.get('apiError')or (isinstance(j.get('failed'),int)and j['failed']>0):return 'исполнитель не подтвердил конечный результат'
                    if j.get('status')in ['waiting_api_window','api_rate_limited','waiting_shared_api_window']:return 'получение данных продолжается с учётом лимита API'
    return ''
def check_n8n(wid,max_age_h):
    try:
        w=n8n_api('workflows/'+wid)
        if not w.get('active'):return ('broken','процесс n8n выключен')
        runs=n8n_api('executions?workflowId='+wid+'&limit=2').get('data',[])
        if not runs:return ('wip','новый процесс; штатный запуск ещё не наблюдался')
        latest=runs[0]
        if latest.get('status')in ['running','waiting','new']:
            if len(runs)<2:return ('wip','идёт проверка')
            latest=runs[1]
        when=datetime.fromisoformat(latest['startedAt'].replace('Z','+00:00'))
        if (datetime.now(timezone.utc)-when).total_seconds()>max_age_h*3600:return ('broken','нет своевременного запуска n8n')
        ex=n8n_api('executions/'+str(latest['id'])+'?includeData=true');err=n8n_result_error(ex)
        if err:return ('wip'if err.startswith('получение')else'broken',err)
        return ('ok','n8n: результат проверен '+when.astimezone(timezone(timedelta(hours=3))).strftime('%d.%m %H:%M'))
    except Exception:return ('wip','доступ к проверке n8n не подтверждён')

def main():
    data = json.load(open(DOCS, encoding="utf-8"))
    update_services(data)
    update_continuity_archive(data)
    # ссылка «Проверить прогон» на каждую карточку: страница последнего запуска её
    # воркфлоу на GitHub (🟢 прошёл / 🔴 упал + время). Для ПК-парсеров цен (нет своего
    # облачного воркфлоу) — ведём на «Сторож цен», который и проверяет их свежесть.
    CHECK_EXTRA = {
        "oz_reviews_auto": (OZ, "oz_reviews_weekly.yml"),
    }
    for it in data["items"]:
        mm = CHECKS.get(it["id"]) or CHECK_EXTRA.get(it["id"])
        if mm:
            it["check_url"] = f"https://github.com/{mm[0]}/actions/workflows/{mm[1]}"
        else:
            it.pop("check_url", None)
    for it in data["items"]:
        if it.get("status") == "paused":
            continue  # приостановлено вручную — авто-обновлялка НЕ трогает
        nm=N8N_CHECKS.get(it['id'])
        if nm:
            it['status'],it['reason']=check_n8n(*nm)
            it['check_url']='http://82.148.225.41:5678/workflow/'+nm[0]
            continue
        m = CHECKS.get(it["id"])
        if not m:
            continue
        res = check(*m)
        if res is None:
            continue
        it["status"], it["reason"] = res
        # авто-жизненный-цикл: заработавший автомат сам переезжает из «В работе и планах» в свою категорию
        if it.get("done_category") and it["status"] == "ok" and it["category"] == "В работе и планах":
            it["category"] = it["done_category"]
            print(f"  {it['id']}: заработал → переехал в «{it['done_category']}»")
        print(f"  {it['id']}: {it['status']} {it['reason']}")
    # DRIFT-контроль: воркфлоу, которых НЕТ на дашборде (соседняя сессия могла добавить и забыть внести)
    IGNORE = {"oferta_probe.yml", "ym_probe.yml", "ym_probe2.yml", "automations_status.yml",
              "pages-build-deployment", "ok_sync.yml",   # ok_sync покрыт карточкой «Автосверка календаря»
              "digest_eval.yml",  # ручной тест качества классификатора дайджеста (по кнопке, не автомат)
              "oz_reviews_freshness.yml", "monthly_dategot.yml", "dategot_fg_sync.yml",
              "content_depth_alert.yml", "poster_sync_watchdog.yml"}  # монитор запаса контента и сторож постера влиты в объединённую карточку «Автопостер контента»; второй сторож Ozon-отзывов покрыт карточкой «Сторож свежести отзывов Ozon»
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

