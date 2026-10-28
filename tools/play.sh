#!/usr/bin/env bash
# Окно мира Matricaria: запускает ядро и окно Godot одной командой.
#
#   ./tools/play.sh            мир "demo" (если его нет — создаётся деревня)
#   ./tools/play.sh town       мир "town"
#
# Закройте окно — ядро остановится само.
set -euo pipefail
cd "$(dirname "$0")/.."

WORLD="${1:-demo}"
PORT="${MATRICARIA_PORT:-8765}"

# Найти Godot: обычная программа или Flatpak.
if command -v godot >/dev/null 2>&1; then
    GODOT=(godot)
elif command -v godot4 >/dev/null 2>&1; then
    GODOT=(godot4)
elif command -v flatpak >/dev/null 2>&1 && flatpak info org.godotengine.Godot >/dev/null 2>&1; then
    GODOT=(flatpak run --filesystem="$PWD/game" org.godotengine.Godot)
else
    echo "Godot 4 is not installed. Install it with:"
    echo "  flatpak install flathub org.godotengine.Godot"
    exit 1
fi

if [ ! -f "saves/$WORLD/world.db" ]; then
    echo "World '$WORLD' does not exist yet. Creating it from the village template..."
    uv run --project core matricaria new "$WORLD"
fi

uv run --project core matricaria serve "$WORLD" --port "$PORT" &
CORE=$!
trap 'kill "$CORE" 2>/dev/null || true; wait "$CORE" 2>/dev/null || true' EXIT

"${GODOT[@]}" --path game -- --port="$PORT" "${@:2}"
