# 05. Протокол Godot ⇄ Python (черновик)

WebSocket на `ws://127.0.0.1:<порт>` (по умолчанию 8765). Каждое сообщение — это JSON с полями `type`, `id` и `data`.
Ответ ядра приходит с тем же `id`, что и запрос.

## Сделано в 0.3.5 «Окно мира»

Код: `core/matricaria/server.py` (ядро), `game/core_client.gd` (Godot). Запуск ядра: `matricaria serve <мир> --port 8765`.

| Godot → ядро | data | Ответ |
|---|---|---|
| `world.get` | `{}` | `world.state` |
| `character.get` | `{ "id": "boris" }` | `character.sheet` |
| `player.move` | `{ "to": "tavern" }` | `world.state` (пока по местам, по клеткам — в 0.7) |
| `time.skip` | `{ "minutes": 60 }` | `world.state` со сводкой `report` (0.4) |
| `time.tick` | `{ "minutes": 1 }` (1–60) | `world.state`; ход часов «×1 / ×4», без события в журнале (0.4, D53) |
| `snapshot.take` | `{ "label": "..." }` | `world.state` |
| `snapshot.restore` | `{ "id": 1 }` | `world.state` |
| `rules.set_mode` | `{ "mode": "strict" }` | `world.state` |

- `world.state`: мир (имя, сеттинг, время, режим правил), герой, места с прямоугольниками на схеме (`x`, `y`, `w`, `h`, `depth` — раскладку считает ядро), персонажи, предметы на земле, снимки, последние 40 строк журнала.
- С 0.4 в `world.state` есть `world.date_text` (полная дата по календарю D50), у персонажей — `activity` (чем занят житель), а после `time.skip` — `report`: строки сводки пропуска.
- `character.sheet`: характеристики, тело, деньги, предметы, отношения, знания (статус, верит ли, устарело ли); с 0.4 — `home_id`, `work_id`, `activity`, `needs` (food, rest, social, safety), `wage_owed`.
- `error`: `{ "code": "bad_message" / "unknown_type" / "rule", "message": "..." }`. Код `rule` — ядро не разрешило действие.

Ниже — полный план протокола; остальное появится в 0.5–0.8.

## Godot → ядро (намерения игрока)

| type | data | Что делает |
|---|---|---|
| `world.load` | `{ "save": "eldmar" }` | Загрузить мир |
| `player.move` | `{ "x": 21, "y": 13 }` | Перейти на клетку |
| `dialog.start` | `{ "with": "npc_17" }` | Начать разговор |
| `dialog.say` | `{ "text": "..." }` | Реплика игрока |
| `dialog.call` | `{ "who": "npc_22" }` | Позвать персонажа с заднего плана |
| `dialog.leave` | `{}` | Закончить разговор |
| `time.set_speed` | `{ "speed": 0 / 1 / 4 }` | Пауза или скорость |
| `time.skip` | `{ "hours": 168 }` | Пропустить время |
| `snapshot.restore` | `{ "id": "s_12" }` | Откатиться |
| `pending.resolve` | `{ "id": "p_3", "accept": true }` | Принять или отклонить факт |
| `rules.set_mode` | `{ "mode": "strict" / "narrative" / "free" }` | Сменить режим правил |
| `check.decide` | `{ "outcome": "success" }` | «Решить самому» вместо броска |
| `author.edit` | `{ "target": "npc_17", "change": {…} }` | Действие режима рассказчика |

## Ядро → Godot (состояние)

| type | data | Когда приходит |
|---|---|---|
| `world.state` | карта, персонажи на экране, время | после загрузки и изменений |
| `actors.update` | позиции и анимации NPC | каждый тик |
| `dialog.scene` | фон, передний план (до 5), задний план | при входе в диалог и изменениях |
| `dialog.line` | автор, текст, эмоция | новая реплика (может приходить по частям) |
| `dialog.effects` | изменения отношений, новые факты | после реплики |
| `time.report` | хроника и события | после пропуска времени |
| `asset.ready` | id и путь картинки | когда генерация завершилась |
| `error` | код и сообщение | ошибка |
