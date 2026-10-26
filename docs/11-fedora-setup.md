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

Дальнейшие шаги появятся по мере разработки.
