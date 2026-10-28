# 11. Установка на Fedora

Пока программы нет, здесь описано, как подготовить систему. Команды вводятся в «Терминал».

## 1. Базовые инструменты

```bash
sudo dnf install git python3 python3-devel uv gcc-c++ cmake
```

## 2. Видеокарта

Узнать, какая у вас видеокарта:
```bash
lspci | grep -iE "vga|3d"
```

- **AMD или Intel:** ничего ставить не нужно, работает через Vulkan.
  ```bash
  sudo dnf install vulkan-tools vulkan-loader-devel glslc
  vulkaninfo --summary
  ```
- **NVIDIA:** нужен драйвер из RPM Fusion (инструкция: https://rpmfusion.org/Howto/NVIDIA).

## 3. Godot 4

Вариант через Flathub:
```bash
flatpak install flathub org.godotengine.Godot
```
Или скачайте с https://godotengine.org/download/linux/.

## 4. Получить проект

```bash
git clone https://github.com/GreenClowns/Matricaria.git
cd Matricaria
```

## 5. Ядро мира в терминале (версия 0.3)

Всё запускается из папки `Matricaria`. Миры сохраняются в `saves/<имя>/world.db`, снимки — рядом, в `saves/<имя>/snapshots/`.

```bash
uv run --project core matricaria --help          # список команд
uv run --project core matricaria new demo        # мир «Alder Village» (фэнтези)
uv run --project core matricaria new town --template city   # «Maple Street» (современность)
uv run --project core matricaria status demo     # время, герой, места, кто где
uv run --project core matricaria show demo boris # лист персонажа и что он знает
uv run --project core matricaria log demo        # журнал событий
```

Снимки и откат:

```bash
uv run --project core matricaria snapshot demo "before the fight"
uv run --project core matricaria kill demo hero
uv run --project core matricaria rollback demo 1
```

Команды рассказчика (пишутся в журнал с основанием `author`): `revive`, `kill`, `health`, `give`, `take`, `money`, `move`, `stat`, `body`, `relation`, `ability`, `controller`, `fact`, `teach`, `rules`, `wait`. Подсказка по любой команде: `matricaria <команда> --help`.

Чтобы не писать каждый раз длинное начало, можно завести короткое имя (действует до закрытия терминала):

```bash
alias mx='uv run --project core matricaria'
mx status demo
```

Тесты ядра:

```bash
uv run --project core --with pytest pytest tests -q
```

## 6. Окно мира (версия 0.3.5)

Один раз поставить Godot 4 (см. шаг 3):
```bash
flatpak install flathub org.godotengine.Godot
```

Запуск (ядро и окно вместе):
```bash
./tools/play.sh          # мир demo; если его нет, создаётся деревня
./tools/play.sh town     # другой мир из saves/
```

В окне: щелчок по месту — герой идёт туда, щелчок по фигурке — лист персонажа справа. Сверху — пропуск времени, режим правил, снимок и откат. Закройте окно — ядро остановится само.
Пока окно открыто, команды рассказчика в терминале (`mx kill demo boris` и т.п.) лучше не запускать: окно узнает о них только после следующего действия.

Дальнейшие шаги появятся по мере разработки.
