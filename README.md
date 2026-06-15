# vc-asfarm-poster

Мульти-канальный автопостер образовательного контента АС Фарм: **ВКонтакте + Дзен (RSS) + VC**.
Тексты проходят валидатор (нет рекламных слов и обещаний лечения), затем публикуются.

## Структура

```
src/
  config.py              правила валидатора, креды (из env)
  validator.py           проверка текста перед публикацией
  queue.py               очередь постов (content/queue.json)
  publish.py             оркестратор (CLI)
  channels/vc.py         VC (Osnova API, entry/create)
  channels/vk.py         ВКонтакте (wall.post)
  channels/dzen_rss.py   Дзен: генерит docs/ + feed.xml для RSS-импорта
content/queue.json       посты (черновик-заглушка, переписывается)
tests/                   pytest
.github/workflows/       cron-публикация
```

## Локальный запуск

```bash
pip install -r requirements.txt
python -m pytest -q                 # тесты текстов
python -m src.publish --dry-run     # проверить все посты, ничего не публикуя
python -m src.publish --channel dzen   # пересобрать сайт+фид Дзена в docs/
```

## Деплой (бесплатно)

1. Создать **приватный** репозиторий на GitHub, запушить код.
2. Settings → Secrets and variables → Actions → добавить:
   `VK_TOKEN`, `VK_OWNER_ID`, `VC_TOKEN`, `VC_SUBSITE_ID`, `SITE_BASE_URL`.
3. Для Дзена: Settings → Pages → Deploy from branch → `main` / `/docs`.
   Затем в Дзен Студио добавить RSS-фид `SITE_BASE_URL/feed.xml`
   (нужно ≥10 материалов в фиде).
4. Расписание уже в `.github/workflows/publish.yml`
   (еженедельно VK+Дзен, VC — 1-го числа). Запуск вручную: вкладка Actions.

## Где брать токены

- **VK** — токен сообщества с правами `wall`, `manage`; `VK_OWNER_ID` = ID группы со знаком минус.
- **VC** — vc.ru → Настройки → «Инструменты для разработчика».
