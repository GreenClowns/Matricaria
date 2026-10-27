## Главное окно (версия 0.3.5 «Окно мира»).
##
## Сверху — время и кнопки, в центре — схема мира, справа — лист
## персонажа и журнал. Каждое нажатие уходит в ядро как намерение,
## ядро проверяет его и присылает новое состояние мира.
##
## Параметры после `--` в командной строке:
##   --port=8765          порт ядра
##   --screenshot=путь    сохранить картинку окна и выйти (для проверки)
##   --select=id          сразу открыть лист персонажа (для проверки)
extends Control

const RULE_MODES := ["strict", "narrative", "free"]

var core := CoreClient.new()
var map_view := MapView.new()
var state: Dictionary = {}
var selected_character := ""

var _title := Label.new()
var _time := Label.new()
var _rules := OptionButton.new()
var _snapshots := OptionButton.new()
var _sheet := RichTextLabel.new()
var _log := RichTextLabel.new()
var _status := Label.new()
var _tabs := TabContainer.new()
var _screenshot_path := ""
var _screenshot_frames := -1


func _ready() -> void:
	var port := 8765
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--port="):
			port = int(arg.get_slice("=", 1))
		elif arg.begins_with("--screenshot="):
			_screenshot_path = arg.get_slice("=", 1)
		elif arg.begins_with("--select="):
			selected_character = arg.get_slice("=", 1)
	_build_ui()
	add_child(core)
	core.connected.connect(_on_connected)
	core.disconnected.connect(func(): _say("Lost connection to the core. Reconnecting..."))
	core.message_received.connect(_on_message)
	core.start(port)
	_say("Connecting to the core at %s ..." % core.url)


# --- Интерфейс -------------------------------------------------------------------


func _build_ui() -> void:
	var background := ColorRect.new()
	background.color = Color("#1f2228")
	background.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(background)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 6)
	add_child(root)

	var bar := HBoxContainer.new()
	bar.add_theme_constant_override("separation", 8)
	root.add_child(bar)
	_title.add_theme_font_size_override("font_size", 20)
	bar.add_child(_title)
	_time.add_theme_font_size_override("font_size", 18)
	_time.add_theme_color_override("font_color", Color("#f5c542"))
	bar.add_child(_time)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bar.add_child(spacer)
	bar.add_child(_button("+1 hour", func(): core.send("time.skip", {"minutes": 60})))
	bar.add_child(_button("+1 day", func(): core.send("time.skip", {"minutes": 1440})))
	bar.add_child(_label("Rules:"))
	for mode in RULE_MODES:
		_rules.add_item(mode)
	_rules.item_selected.connect(func(index): core.send("rules.set_mode", {"mode": RULE_MODES[index]}))
	bar.add_child(_rules)
	bar.add_child(_button("Snapshot", func(): core.send("snapshot.take", {"label": "from the window"})))
	_snapshots.custom_minimum_size.x = 220
	bar.add_child(_snapshots)
	bar.add_child(_button("Roll back", _on_rollback))

	var split := HSplitContainer.new()
	split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(split)
	map_view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	map_view.size_flags_stretch_ratio = 2.2
	map_view.tooltip_text = " "
	map_view.place_clicked.connect(func(id): core.send("player.move", {"to": id}))
	map_view.character_clicked.connect(_select_character)
	split.add_child(map_view)

	_tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_tabs.custom_minimum_size.x = 360
	split.add_child(_tabs)
	for pair in [["Character", _sheet], ["Log", _log]]:
		var text: RichTextLabel = pair[1]
		text.name = pair[0]
		text.bbcode_enabled = true
		text.selection_enabled = true
		text.scroll_following = text == _log
		_tabs.add_child(text)
	_sheet.text = "Click a character on the map to see who they are and what they know."

	_status.add_theme_color_override("font_color", Color("#c9cdd4"))
	root.add_child(_status)


func _button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.pressed.connect(action)
	return button


func _label(text: String) -> Label:
	var label := Label.new()
	label.text = text
	return label


func _say(text: String, is_error := false) -> void:
	_status.text = text
	_status.add_theme_color_override("font_color", Color("#ff7b6b") if is_error else Color("#c9cdd4"))


# --- Сообщения ядра --------------------------------------------------------------


func _on_connected() -> void:
	_say("Connected to the core.")
	core.send("world.get")


func _on_message(type: String, data: Dictionary) -> void:
	match type:
		"world.state":
			_show_state(data)
		"character.sheet":
			_show_sheet(data)
		"error":
			_say("Not possible: %s" % data.get("message", "unknown error"), true)
		_:
			push_warning("Unknown message from the core: %s" % type)


func _show_state(data: Dictionary) -> void:
	state = data
	var world: Dictionary = data["world"]
	_title.text = "  %s (%s)" % [world["name"], world["setting"]]
	_time.text = str(world["time_text"])
	_rules.select(RULE_MODES.find(world["rule_mode"]))
	_snapshots.clear()
	for snapshot in data.get("snapshots", []):
		var label := "#%d %s" % [snapshot["id"], snapshot["time_text"]]
		if str(snapshot["label"]) != "":
			label += " — " + str(snapshot["label"])
		_snapshots.add_item(label, int(snapshot["id"]))
	if _snapshots.item_count > 0:
		_snapshots.select(_snapshots.item_count - 1)
	_log.text = "\n".join(PackedStringArray(data.get("log", [])))
	map_view.show_state(data)
	if selected_character != "":
		core.send("character.get", {"id": selected_character})
	if _screenshot_path != "" and _screenshot_frames < 0:
		_screenshot_frames = 20
	_say("Click a place to walk there, click a character to see their sheet.")


func _select_character(character_id: String) -> void:
	selected_character = character_id
	_tabs.current_tab = 0
	core.send("character.get", {"id": character_id})


func _show_sheet(c: Dictionary) -> void:
	var lines := PackedStringArray()
	lines.append("[font_size=20][b]%s[/b][/font_size]" % c["name"])
	lines.append("%s · %s" % [c["role"] if c["role"] != "" else "no role", c["profession"] if c["profession"] != "" else "no profession"])
	var alive := "alive" if c["alive"] else "[color=#ff7b6b]dead[/color]"
	lines.append("%s · health %d/%d · at %s" % [alive, c["health"], c["max_health"], c["location_id"]])
	if not c["conditions"].is_empty():
		lines.append("Conditions: " + ", ".join(PackedStringArray(c["conditions"])))
	var stats: Dictionary = c["stats"]
	lines.append("")
	lines.append("[b]Stats[/b]  STR %d · AGI %d · END %d · INT %d · CHA %d" % [
		stats["strength"], stats["agility"], stats["endurance"], stats["intellect"], stats["charisma"]])
	var body: Dictionary = c["body"]
	lines.append("[b]Body[/b]  %s · muscles %d · fatness %d · %s" % [
		_height(int(body["height_cm"])), body["muscles"], body["fatness"], body["build"]])
	lines.append("[b]Money[/b]  cash %d · bank %d" % [c["cash"], c["bank"]])
	if not c["abilities"].is_empty():
		lines.append("[b]Abilities[/b]  " + ", ".join(PackedStringArray(c["abilities"])))
	lines.append("")
	lines.append("[b]Items[/b]")
	if c["items"].is_empty():
		lines.append("  none")
	for item in c["items"]:
		var equipped := " (%s)" % item["equipped"] if item["equipped"] != null else ""
		lines.append("  • %s%s" % [item["name"], equipped])
	if not c["relations"].is_empty():
		lines.append("")
		lines.append("[b]Feels about others[/b]")
		for r in c["relations"]:
			lines.append("  • %s: liking %d, trust %d, fear %d, respect %d, love %d" % [
				r["to"], r["liking"], r["trust"], r["fear"], r["respect"], r["love"]])
	lines.append("")
	lines.append("[b]Knows[/b]")
	if c["knows"].is_empty():
		lines.append("  nothing yet")
	for k in c["knows"]:
		var flags := PackedStringArray()
		if k["status"] != "truth":
			flags.append(k["status"])
		if not k["believes"]:
			flags.append("does not believe")
		if not k["current"]:
			flags.append("out of date")
		var tail := " [color=#f5c542][%s][/color]" % ", ".join(flags) if not flags.is_empty() else ""
		lines.append("  • %s%s" % [k["text"], tail])
	_sheet.text = "\n".join(lines)


func _height(cm: int) -> String:
	if cm >= 1000:
		return "%.1f m" % (cm / 100.0)
	return "%d cm" % cm


func _on_rollback() -> void:
	if _snapshots.item_count == 0:
		_say("No snapshots yet. Press Snapshot first.", true)
		return
	var snapshot_id := _snapshots.get_item_id(_snapshots.selected)
	core.send("snapshot.restore", {"id": snapshot_id})


# --- Проверочный снимок экрана -------------------------------------------------


func _process(_delta: float) -> void:
	if _screenshot_frames > 0:
		_screenshot_frames -= 1
		if _screenshot_frames == 0:
			var image := get_viewport().get_texture().get_image()
			image.save_png(_screenshot_path)
			get_tree().quit()
