## Связь с Python-ядром по WebSocket (D5, docs/05-protocol.md).
##
## Отправляет намерения игрока и получает ответы ядра.
## Если ядро ещё не запустилось, пробует подключиться снова раз в секунду.
extends Node

signal connected
signal disconnected
signal message_received(type: String, data: Dictionary)

const RETRY_SECONDS := 1.0

var url := "ws://127.0.0.1:8765"
var _socket := WebSocketPeer.new()
var _open := false
var _retry_in := 0.0
var _next_id := 1


func start(port: int) -> void:
	url = "ws://127.0.0.1:%d" % port
	_socket.connect_to_url(url)


func is_open() -> bool:
	return _open


func send(type: String, data: Dictionary = {}) -> void:
	if not _open:
		return
	var message := {"type": type, "id": _next_id, "data": data}
	_next_id += 1
	_socket.send_text(JSON.stringify(message))


func _exit_tree() -> void:
	# Вежливо закрываем соединение, чтобы ядро не считало это ошибкой.
	_socket.close()


func _process(delta: float) -> void:
	_socket.poll()
	var state := _socket.get_ready_state()
	if state == WebSocketPeer.STATE_OPEN:
		if not _open:
			_open = true
			connected.emit()
		while _socket.get_available_packet_count() > 0:
			_receive(_socket.get_packet().get_string_from_utf8())
	elif state == WebSocketPeer.STATE_CLOSED:
		if _open:
			_open = false
			disconnected.emit()
		# Ядро ещё не готово или закрылось: пробуем снова.
		_retry_in -= delta
		if _retry_in <= 0.0:
			_retry_in = RETRY_SECONDS
			_socket = WebSocketPeer.new()
			_socket.connect_to_url(url)


func _receive(text: String) -> void:
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("Core sent something that is not JSON: %s" % text)
		return
	var message: Dictionary = parsed
	var data: Variant = message.get("data", {})
	message_received.emit(str(message.get("type", "")), data if data is Dictionary else {})
