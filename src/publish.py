"""Оркестратор: валидирует посты, соблюдает частоту, строит фид Дзена,
публикует в VK и VC.

Использование:
  python -m src.publish --dry-run           # только проверить тексты
  python -m src.publish --channel dzen      # пересобрать сайт+фид для Дзена
  python -m src.publish --channel vk        # опубликовать следующий пост в ВК
  python -m src.publish --channel vc        # опубликовать следующий пост в VC
  python -m src.publish --channel all       # все каналы, с соблюдением интервалов
  python -m src.publish --channel all --force  # игнорировать интервалы (для теста)

Безопасная частота берётся из config.CADENCE_DAYS и соблюдается автоматически:
канал пропускается, пока не выдержан интервал, даже если workflow запустился раньше.
"""

import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs_image(rel):
    if not rel:
        return None
    p = rel if os.path.isabs(rel) else os.path.join(REPO_ROOT, rel)
    return p if os.path.exists(p) else None

from . import queue as q
from . import validator
from . import config


def _now():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now().isoformat()


def _cadence_ok(last_dt, channel, force=False):
    """True, если интервал между постами выдержан.

    Запас 6ч компенсирует плавающее время запуска GitHub Actions: иначе при
    интервале ровно N*24ч запуск, случившийся чуть раньше, пропускал день.
    """
    if force or last_dt is None:
        return True
    interval = timedelta(days=config.CADENCE_DAYS.get(channel, 1)) - timedelta(hours=6)
    return _now() - last_dt >= interval


def _days_left(last_dt, channel):
    interval = timedelta(days=config.CADENCE_DAYS.get(channel, 1))
    left = (last_dt + interval) - _now()
    return max(0, left.days + (1 if left.seconds else 0))


# --- Валидация ---

def validate_all(posts):
    all_ok = True
    report = []
    for p in posts:
        res = validator.validate_post(p.get("title", ""), p.get("body_long", ""))
        if p.get("body_vk"):
            res_vk = validator.validate_post(p.get("title", ""), p["body_vk"])
            res["errors"] += [f"[vk] {e}" for e in res_vk["errors"]]
            res["ok"] = not res["errors"]
        if not res["ok"]:
            all_ok = False
        report.append((p.get("id", "?"), res))
    return all_ok, report


def print_report(report):
    for pid, res in report:
        print(f"[{'OK ' if res['ok'] else 'FAIL'}] {pid}")
        for e in res["errors"]:
            print(f"    ✗ {e}")
        for w in res["warnings"]:
            print(f"    ! {w}")


# --- Дзен: дрип-выпуск статей в фид с соблюдением частоты ---

def do_dzen(posts, force=False):
    from .channels import dzen_rss

    released = q.dzen_released(posts)
    changed = False

    # 1) Бэкфилл: чтобы фид прошёл первую разметку (нужно ≥10), сразу выпускаем
    #    недостающие до DZEN_BACKFILL_MIN.
    while len(q.dzen_released(posts)) < config.DZEN_BACKFILL_MIN:
        nxt = q.next_unreleased_dzen(posts)
        if not nxt:
            break
        q.release_dzen(nxt, _now_iso())
        changed = True

    # 2) После бэкфилла — выпускаем по одной статье не чаще, чем раз в CADENCE_DAYS.
    if len(q.dzen_released(posts)) >= config.DZEN_BACKFILL_MIN:
        if _cadence_ok(q.last_released_at(posts), "dzen", force):
            nxt = q.next_unreleased_dzen(posts)
            if nxt:
                q.release_dzen(nxt, _now_iso())
                changed = True
                print(f"Дзен: выпущена новая статья «{nxt['id']}».")
        else:
            left = _days_left(q.last_released_at(posts), "dzen")
            print(f"Дзен: интервал не выдержан, новую статью можно через ~{left} дн.")

    info = dzen_rss.build_site(q.feed_posts(posts))
    print(f"Дзен: фид пересобран, статей в нём — {info['count']}.")
    print(f"      RSS: {info['feed_url']}")
    if not info["enough_for_dzen"]:
        print("      ⚠ Для первой разметки в Дзене нужно ≥10 статей в фиде.")
    return changed


# --- VK / VC: публикация с соблюдением частоты ---

def do_channel_post(posts, channel, ClientCls, body_field, force=False):
    if not _cadence_ok(q.last_posted_at(posts, channel), channel, force):
        left = _days_left(q.last_posted_at(posts, channel), channel)
        print(f"{channel}: интервал не выдержан, следующий пост можно через ~{left} дн.")
        return False

    post = q.next_unposted(posts, channel)
    if not post:
        print(f"{channel}: уникальных постов в очереди нет — нужно пополнить (повторы запрещены).")
        return False

    body = post.get(body_field) or post.get("body_long", "")
    res = validator.validate_post(post.get("title", ""), body)
    if not res["ok"]:
        print(f"{channel}: пост «{post['id']}» НЕ прошёл валидацию, пропуск:")
        for e in res["errors"]:
            print(f"    ✗ {e}")
        return False

    try:
        out = ClientCls().publish(
            post["title"], body,
            image_path=_abs_image(post.get("image")),
            links=post.get("links"),
        )
    except Exception as e:
        print(f"{channel}: ошибка публикации «{post['id']}»: {e}")
        return False
    q.mark_posted(post, channel, _now_iso(), out.get("url"))
    print(f"{channel}: опубликован «{post['id']}» → {out.get('url')}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="АС Фарм мульти-канальный постер")
    parser.add_argument("--channel", default="all", choices=["all", "vc", "vk", "dzen"])
    parser.add_argument("--dry-run", action="store_true", help="только валидация")
    parser.add_argument("--force", action="store_true", help="игнорировать интервалы частоты")
    args = parser.parse_args(argv)

    posts = q.load()

    ok, report = validate_all(posts)
    print_report(report)
    if not ok:
        print("\nЕсть посты с ошибками. Публикация остановлена.")
        return 1
    if args.dry_run:
        print("\ndry-run: все тексты валидны, публикация пропущена.")
        return 0

    changed = False
    if args.channel in ("all", "dzen"):
        changed |= do_dzen(posts, args.force)
    if args.channel in ("all", "vk"):
        from .channels.vk import VKClient
        changed |= do_channel_post(posts, "vk", VKClient, "body_vk", args.force)
    if args.channel in ("all", "vc"):
        from .channels.vc import VCClient
        changed |= do_channel_post(posts, "vc", VCClient, "body_long", args.force)

    # Живые счётчики соцсетей (раз в сутки) + календарь — обновляем при каждом запуске.
    try:
        from scripts.gen_stats import main as _stats_main
        _stats_main()
    except Exception as _e:
        print(f"Статистика: не удалось обновить ({_e}).")
    try:
        from scripts.gen_calendar import render as _cal_render
        _out = os.path.join(REPO_ROOT, "docs", "calendar.html")
        with open(_out, "w", encoding="utf-8") as _f:
            _f.write(_cal_render(posts))
        print("Календарь: docs/calendar.html обновлён.")
    except Exception as _e:
        print(f"Календарь: не удалось обновить ({_e}).")

    if changed:
        q.save(posts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
