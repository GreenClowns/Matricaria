# 09. Карточки и сценарии (черновик)

## Карточка персонажа

Один файл `.png`. Сама картинка — это портрет, а внутри (в чанке PNG `matricaria`) лежит JSON:

```json
{
  "format": "matricaria-character",
  "version": 1,
  "name": "Кира",
  "body": { "age_years": 19, "height_cm": 163, "weight_kg": 52, "parts": { "hair": 2 } },
  "sprite": { "skin": "light", "hair": { "style": "long", "color": "#c9ced8" } },
  "portraits": { "style": "pixel", "pixel_preset": "hibit", "seed": 48213, "emotions": ["neutral", "happy", "angry"] },
  "personality": {
    "traits": { "kind": 60, "social": 20, "honest": 40 },
    "speech": "Коротко, с иронией",
    "goals": ["Найти брата"],
    "fears": ["Огонь"]
  },
  "backstory": "...",
  "example_lines": ["Ну и где тут обещанное приключение?"]
}
```

Телосложение и вариант спрайта вычисляются из `body` ([12](12-art-and-body.md)).

Поле `version` обязательно: при изменении формата старые карточки конвертируются автоматически.

## Сценарий (мир)

Папка или архив `.matricaria`:
```
manifest.json   — название, сеттинг, seed, версия формата
lore/           — записи лорбука
npcs/           — карточки NPC
events/         — шаблоны событий
map/            — заготовки карты (необязательно)
```

Любой герой может войти в любой сценарий. Сценарий можно отдать другому человеку, и он сыграет в нём своим персонажем.

## Совместимость

Позже можно добавить импорт карточек в формате Character Card (SillyTavern) с переводом в наш формат.
