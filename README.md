# Что я сделал

Это безопасный первый этап рефакторинга.

## Новая структура
- `main.py` — только запуск бота
- `app/core.py` — токен, admin ids, bot/dp/router, логгер
- `app/db.py` — подключение и инициализация SQLite
- `app/handlers.py` — вся логика и хендлеры

## Зачем так
Раньше всё было в одном файле.
Теперь:
1. запуск отдельно
2. база отдельно
3. конфиг отдельно
4. логика отдельно

## Как запускать
```bash
python main.py
```

## Следующий этап
Дальше уже можно без боли разбивать `app/handlers.py` на:
- `handlers/economy.py`
- `handlers/games.py`
- `handlers/rp.py`
- `handlers/profile.py`
- `handlers/admin.py`
