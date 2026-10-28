## Схема мира: места — прямоугольники, жители — фигурки.
##
## Это временная картинка до настоящей пиксельной карты (0.7):
## раскладку мест присылает ядро, здесь она только рисуется.
## Щелчок по месту — герой идёт туда, по фигурке — открыть лист персонажа.
extends Control

signal place_clicked(location_id: String)
signal character_clicked(character_id: String)

const MARGIN := 16.0
const FIGURE := 26.0
const KIND_COLORS := {
	"village": Color("#cfe3b4"),
	"street": Color("#d6d2c8"),
	"square": Color("#e2d9c3"),
	"tavern": Color("#d9a86c"),
	"house": Color("#efd9b0"),
	"forest": Color("#8fbf7f"),
	"park": Color("#a6d39a"),
	"cafe": Color("#e7b98f"),
	"police station": Color("#a9bfdc"),
	"clinic": Color("#e6eef2"),
	"apartments": Color("#d8cfe6"),
}

var state: Dictionary = {}
var _scale := 10.0
var _origin := Vector2.ZERO
var _place_rects: Dictionary = {}  # id -> Rect2 на экране
var _figures: Array = []  # [{id, rect}]
var _items: Array = []  # [{name, rect}]


func show_state(new_state: Dictionary) -> void:
	state = new_state
	queue_redraw()


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	resized.connect(queue_redraw)


func _fit() -> void:
	var width := 1.0
	var height := 1.0
	for loc in state.get("locations", []):
		width = maxf(width, float(loc["x"] + loc["w"]))
		height = maxf(height, float(loc["y"] + loc["h"]))
	var room := size - Vector2(MARGIN, MARGIN) * 2.0
	_scale = maxf(4.0, minf(room.x / width, room.y / height))
	var used := Vector2(width, height) * _scale
	_origin = Vector2(MARGIN, MARGIN) + (room - used) / 2.0


func _rect_of(loc: Dictionary) -> Rect2:
	return Rect2(
		_origin + Vector2(float(loc["x"]), float(loc["y"])) * _scale,
		Vector2(float(loc["w"]), float(loc["h"])) * _scale
	)


func _color_of(kind: String, depth: int) -> Color:
	var color: Color = KIND_COLORS.get(kind, Color.from_hsv(float(hash(kind) % 360) / 360.0, 0.25, 0.9))
	return color.darkened(0.0 if depth > 0 else 0.05)


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), Color("#2b2f36"))
	if state.is_empty():
		return
	_fit()
	_place_rects.clear()
	_figures.clear()
	_items.clear()
	var font := get_theme_default_font()
	var player_id: String = str(state.get("player_id", ""))
	var player_location := ""
	for c in state.get("characters", []):
		if c["id"] == player_id:
			player_location = str(c["location_id"])

	# Места: сначала внешние, потом вложенные поверх.
	var locations: Array = state.get("locations", []).duplicate()
	locations.sort_custom(func(a, b): return a["depth"] < b["depth"])
	for loc in locations:
		var rect := _rect_of(loc)
		_place_rects[loc["id"]] = rect
		draw_rect(rect, _color_of(str(loc["kind"]), int(loc["depth"])))
		var border := Color("#f5c542") if loc["id"] == player_location else Color("#4a4136")
		draw_rect(rect, border, false, 3.0 if loc["id"] == player_location else 1.5)
		var title := str(loc["name"])
		if loc.get("discovered_by") != null:
			title += " *"
		draw_string(font, rect.position + Vector2(6, 16), title, HORIZONTAL_ALIGNMENT_LEFT,
			rect.size.x - 12, 14, Color("#2a2420"))

	# Жители и предметы — в своих местах.
	var crowd := {}
	for c in state.get("characters", []):
		var where := str(c["location_id"])
		if not crowd.has(where):
			crowd[where] = []
		crowd[where].append(c)
	var loot := {}
	for item in state.get("items", []):
		var where := str(item["location_id"])
		if not loot.has(where):
			loot[where] = []
		loot[where].append(item)

	for loc in locations:
		var rect: Rect2 = _place_rects[loc["id"]]
		# У места с вложенными местами жители стоят во «дворе» внизу.
		var area := rect
		if _has_children(str(loc["id"])):
			area = Rect2(rect.position.x, rect.end.y - 4.0 * _scale, rect.size.x, 4.0 * _scale)
		var slot := 0
		for c in crowd.get(loc["id"], []):
			_draw_figure(c, _slot_position(area, slot), c["id"] == player_id, font)
			slot += 1
		for item in loot.get(loc["id"], []):
			_draw_item(item, _slot_position(area, slot))
			slot += 1


func _has_children(location_id: String) -> bool:
	for loc in state.get("locations", []):
		if str(loc.get("parent_id")) == location_id:
			return true
	return false


func _slot_position(area: Rect2, slot: int) -> Vector2:
	var step := FIGURE + 30.0
	var columns := maxi(1, int((area.size.x - 12.0) / step))
	var row := slot / columns
	var column := slot % columns
	return area.position + Vector2(12.0 + column * step + FIGURE / 2.0, 42.0 + row * (FIGURE + 26.0))


func _figure_size(height_cm: int) -> float:
	# Крошки рисуются меньше, великаны — больше (D38), в разумных пределах.
	if height_cm < 60:
		return 0.5
	if height_cm > 400:
		return 1.6
	return 1.0


func _draw_figure(c: Dictionary, center: Vector2, is_player: bool, font: Font) -> void:
	var k := _figure_size(int(c.get("height_cm", 170)))
	var body_color := Color.from_hsv(float(hash(str(c["id"])) % 360) / 360.0, 0.55, 0.85)
	if not c["alive"]:
		body_color = Color("#8a8a8a")
	var head := center + Vector2(0, FIGURE * 0.15 - FIGURE * 0.25 * k)
	var body := Rect2(center + Vector2(-FIGURE * 0.25 * k, FIGURE * 0.15), Vector2(FIGURE * 0.5 * k, FIGURE * 0.45 * k))
	if is_player:
		draw_circle(center + Vector2(0, FIGURE * 0.2), FIGURE * 0.75 * k, Color(1.0, 0.85, 0.3, 0.45))
	draw_rect(body, body_color.darkened(0.25))
	draw_circle(head, FIGURE * 0.3 * k, body_color)
	draw_arc(head, FIGURE * 0.3 * k, 0.0, TAU, 24, Color("#2a2420"), 1.5)
	if not c["alive"]:
		var r := FIGURE * 0.2 * k
		draw_line(head - Vector2(r, r), head + Vector2(r, r), Color("#3a0000"), 2.0)
		draw_line(head + Vector2(-r, r), head + Vector2(r, -r), Color("#3a0000"), 2.0)
	var label := str(c["name"])
	draw_string(font, center + Vector2(-30, FIGURE * 0.15 + FIGURE * 0.45 * k + 13), label,
		HORIZONTAL_ALIGNMENT_CENTER, 60, 12, Color("#1d1a17"))
	_figures.append({"id": c["id"], "name": label, "activity": c.get("activity"), "rect": Rect2(center - Vector2(FIGURE, FIGURE) * 0.6, Vector2(FIGURE, FIGURE * 1.6) * 1.2)})


func _draw_item(item: Dictionary, center: Vector2) -> void:
	var r := 7.0
	var points := PackedVector2Array([
		center + Vector2(0, -r), center + Vector2(r, 0), center + Vector2(0, r), center + Vector2(-r, 0)
	])
	draw_colored_polygon(points, Color("#f2d24b"))
	draw_polyline(points + PackedVector2Array([points[0]]), Color("#5a4a10"), 1.5)
	_items.append({"name": str(item["name"]), "rect": Rect2(center - Vector2(r, r) * 1.5, Vector2(r, r) * 3.0)})


func _figure_at(point: Vector2) -> Dictionary:
	for figure in _figures:
		if figure["rect"].has_point(point):
			return figure
	return {}


func _place_at(point: Vector2) -> String:
	# Самое вложенное место под курсором.
	var best := ""
	var best_depth := -1
	for loc in state.get("locations", []):
		var rect: Rect2 = _place_rects.get(loc["id"], Rect2())
		if rect.has_point(point) and int(loc["depth"]) > best_depth:
			best = str(loc["id"])
			best_depth = int(loc["depth"])
	return best


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		var figure := _figure_at(event.position)
		if not figure.is_empty():
			character_clicked.emit(str(figure["id"]))
			return
		var place := _place_at(event.position)
		if place != "":
			place_clicked.emit(place)


func _get_tooltip(at_position: Vector2) -> String:
	var figure := _figure_at(at_position)
	if not figure.is_empty():
		if figure["activity"] != null:
			return "%s (%s) — click to see the character sheet" % [figure["name"], figure["activity"]]
		return "%s — click to see the character sheet" % figure["name"]
	for item in _items:
		if item["rect"].has_point(at_position):
			return "Item: %s" % item["name"]
	var place := _place_at(at_position)
	if place != "":
		return "Click to walk here"
	return ""
