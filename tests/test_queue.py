"""Тесты логики очереди: загрузка, выбор следующего, отметка опубликованного."""

import json
import pytest
from src import queue as q


@pytest.fixture
def sample(tmp_path):
    data = [
        {"id": "a", "title": "T", "body_long": "L", "body_vk": "V"},
        {"id": "b", "title": "T", "body_long": "L", "body_vk": "V"},
    ]
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_normalizes_channels(sample):
    posts = q.load(sample)
    assert posts[0]["channels"]["vc"] == {"posted_at": None, "url": None}
    assert posts[0]["channels"]["vk"] == {"posted_at": None, "url": None}


def test_next_unposted_returns_first(sample):
    posts = q.load(sample)
    assert q.next_unposted(posts, "vk")["id"] == "a"


def test_mark_posted_advances_queue(sample):
    posts = q.load(sample)
    first = q.next_unposted(posts, "vk")
    q.mark_posted(first, "vk", "2026-06-15T00:00:00+00:00", "https://vk.com/wall-1_1")
    assert q.next_unposted(posts, "vk")["id"] == "b"
    # для другого канала очередь не сдвинулась
    assert q.next_unposted(posts, "vc")["id"] == "a"


def test_save_roundtrip(sample, tmp_path):
    posts = q.load(sample)
    q.mark_posted(posts[0], "vc", "2026-06-15T00:00:00+00:00")
    out = str(tmp_path / "out.json")
    q.save(posts, out)
    reloaded = q.load(out)
    assert reloaded[0]["channels"]["vc"]["posted_at"] == "2026-06-15T00:00:00+00:00"


def test_feed_posts_only_released(sample):
    posts = q.load(sample)
    assert q.feed_posts(posts) == []          # пока ничего не выпущено — фид пуст
    q.release_dzen(posts[0], "2026-06-15T00:00:00+00:00")
    assert len(q.feed_posts(posts)) == 1


def test_last_posted_at_returns_latest(sample):
    posts = q.load(sample)
    assert q.last_posted_at(posts, "vk") is None
    q.mark_posted(posts[0], "vk", "2026-06-10T00:00:00+00:00")
    q.mark_posted(posts[1], "vk", "2026-06-12T00:00:00+00:00")
    assert q.last_posted_at(posts, "vk").isoformat() == "2026-06-12T00:00:00+00:00"


def test_next_unreleased_dzen(sample):
    posts = q.load(sample)
    assert q.next_unreleased_dzen(posts)["id"] == "a"
    q.release_dzen(posts[0], "2026-06-15T00:00:00+00:00")
    assert q.next_unreleased_dzen(posts)["id"] == "b"
