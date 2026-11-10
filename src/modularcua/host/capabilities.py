from __future__ import annotations

import json
from typing import Any


GUEST_CAPABILITIES: list[dict[str, Any]] = [
    {"name": "screenshot", "description": "Capture the current guest desktop and attach the image to the model result.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False},
     "output_schema": {"type": "image", "mime_type": "image/jpeg"}},
    {"name": "mouse_click", "description": "Click a point in the displayed model screenshot. Coordinates use the attached image's pixels; ModularCUA converts them to native guest pixels.",
     "input_schema": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "clicks": {"type": "integer"}}, "required": ["x", "y"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"executed": {"type": "boolean"}}}},
    {"name": "mouse_drag", "description": "Drag between points in the displayed model screenshot; ModularCUA converts them to native guest pixels.",
     "input_schema": {"type": "object", "properties": {"start_x": {"type": "number"}, "start_y": {"type": "number"}, "end_x": {"type": "number"}, "end_y": {"type": "number"}, "duration": {"type": "number"}}, "required": ["start_x", "start_y", "end_x", "end_y"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"executed": {"type": "boolean"}}}},
    {"name": "keyboard_type", "description": "Type text into the currently focused guest application.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"executed": {"type": "boolean"}}}},
    {"name": "keyboard_hotkey", "description": "Press a keyboard shortcut in the guest.",
     "input_schema": {"type": "object", "properties": {"keys": {"type": "array", "items": {"type": "string"}}}, "required": ["keys"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"executed": {"type": "boolean"}}}},
    {"name": "mouse_scroll", "description": "Scroll in the guest desktop; optional x/y are coordinates in the displayed model screenshot and are converted to native guest pixels.",
     "input_schema": {"type": "object", "properties": {"clicks": {"type": "integer"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["clicks"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"executed": {"type": "boolean"}}}},
    {"name": "shell", "description": "Run a shell command inside the authorized OSWorld guest.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "array", "items": {"type": "string"}}, "timeout": {"type": "number"}}, "required": ["command"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"returncode": {"type": "integer"}, "stdout": {"type": "string"}, "stderr": {"type": "string"}}}},
    {"name": "file_read", "description": "Read a file from the authorized guest filesystem.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "file_write", "description": "Write a file in the authorized guest filesystem.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "text": {"type": "string"}}, "required": ["path", "text"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"bytes_written": {"type": "integer"}}}},
    {"name": "application_open", "description": "Open a file or application in the guest desktop.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"], "additionalProperties": False},
     "output_schema": {"type": "object", "properties": {"pid": {"type": ["integer", "null"]}}}},
]


def guest_capability_bootstrap() -> str:
    """Return independent guest-side tool implementations, with no Agent-S imports."""
    metadata = json.dumps(GUEST_CAPABILITIES, separators=(",", ":"))
    return r'''import base64, io, json, pathlib, subprocess, types, pyautogui, functools, time, uuid
_cua_meta = {item["name"]: item for item in json.loads(''' + repr(metadata) + r''')}
_cua_action_events = []
_cua_action_depth = [0]
_cua_action_sequence = [0]
_cua_coordinate_context = [None]
_cua_capability_context = [None]
_cua_guest_screen_size = tuple(pyautogui.size())
_cua_model_scale = min(1.0, 1200.0 / max(_cua_guest_screen_size))
_cua_model_image_size = [(int(round(_cua_guest_screen_size[0] * _cua_model_scale)),
                           int(round(_cua_guest_screen_size[1] * _cua_model_scale)))]
_cua_coordinate_available = [True]
def _cua_json_safe(value):
    if value is None or isinstance(value, (bool, int, float, str)): return value
    if isinstance(value, (list, tuple)): return [_cua_json_safe(item) for item in value]
    if isinstance(value, dict): return {str(key): _cua_json_safe(item) for key, item in value.items()}
    return repr(value)
def _cua_persist_actions():
    call_id = globals().get("_modularcua_active_call_id")
    root = globals().get("_modularcua_action_root")
    if not call_id or not root: return
    target = pathlib.Path(root) / "actions" / (str(call_id) + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(_cua_action_events, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
def _cua_wrap_action(name, original):
    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        outermost = _cua_action_depth[0] == 0
        original_args, original_kwargs = args, kwargs
        actual_args, actual_kwargs = args, kwargs
        direct_coordinate = None
        mapping_error = None
        if outermost and _cua_capability_context[0] is None:
            try:
                actual_args, actual_kwargs, direct_coordinate = _cua_scale_direct_action(name, args, kwargs)
            except BaseException as exc:
                mapping_error = exc
                indices = _cua_absolute_xy.get(name) or _cua_relative_xy.get(name)
                if indices is not None:
                    requested_x, requested_y = _cua_get_xy(args, kwargs, indices)
                    direct_coordinate = {"space": "displayed_model_screenshot_pixels",
                        "x": requested_x, "y": requested_y, "mapping_error": type(exc).__name__ + ": " + str(exc)}
        if outermost:
            _cua_action_sequence[0] += 1
            record = {"sequence": _cua_action_sequence[0], "action_id": str(uuid.uuid4()),
                      "method": name, "arguments": {"args": _cua_json_safe(original_args),
                                                       "kwargs": _cua_json_safe(original_kwargs)},
                      "capability": _cua_capability_context[0],
                      "requested_model_coordinates": _cua_json_safe(direct_coordinate or _cua_coordinate_context[0]),
                      "executed_native_coordinates": (None if mapping_error is not None else
                                                      _cua_native_coordinates(name, actual_args, actual_kwargs)),
                      "status": "running", "started_unix": time.time()}
            if mapping_error is not None:
                record["status"] = "error"
                record["exception"] = type(mapping_error).__name__ + ": " + str(mapping_error)
                record["duration_seconds"] = time.time() - record["started_unix"]
                _cua_action_events.append(record); _cua_persist_actions()
                raise mapping_error
        _cua_action_depth[0] += 1
        try:
            result = original(*actual_args, **actual_kwargs)
            if outermost:
                record["status"] = "executed"
                record["duration_seconds"] = time.time() - record["started_unix"]
                _cua_action_events.append(record)
                _cua_persist_actions()
            return result
        except BaseException as exc:
            if outermost:
                record["status"] = "error"
                record["exception"] = type(exc).__name__ + ": " + str(exc)
                record["duration_seconds"] = time.time() - record["started_unix"]
                _cua_action_events.append(record)
                _cua_persist_actions()
            raise
        finally:
            _cua_action_depth[0] -= 1
    return wrapped

_cua_absolute_xy = {"click": (0, 1), "doubleClick": (0, 1), "tripleClick": (0, 1),
                    "rightClick": (0, 1), "middleClick": (0, 1), "moveTo": (0, 1),
                    "dragTo": (0, 1), "mouseDown": (0, 1), "mouseUp": (0, 1),
                    "scroll": (1, 2)}
_cua_relative_xy = {"moveRel": (0, 1), "dragRel": (0, 1)}
def _cua_get_xy(args, kwargs, indices):
    x_index, y_index = indices
    x = args[x_index] if len(args) > x_index else kwargs.get("x")
    y = args[y_index] if len(args) > y_index else kwargs.get("y")
    return x, y
def _cua_replace_xy(args, kwargs, indices, x, y):
    x_index, y_index = indices
    new_args = list(args); new_kwargs = dict(kwargs)
    if len(new_args) > x_index: new_args[x_index] = x
    else: new_kwargs["x"] = x
    if len(new_args) > y_index: new_args[y_index] = y
    else: new_kwargs["y"] = y
    return tuple(new_args), new_kwargs
def _cua_scale_direct_action(name, args, kwargs):
    indices = _cua_absolute_xy.get(name) or _cua_relative_xy.get(name)
    if indices is None: return args, kwargs, None
    x, y = _cua_get_xy(args, kwargs, indices)
    if x is None or y is None: return args, kwargs, None
    if not _cua_coordinate_available[0]:
        raise RuntimeError("Take and attach a fresh full-screen screenshot before a coordinate-based action; "
                           "the most recent attached image is not a registered desktop screenshot.")
    width, height = pyautogui.size()
    model_width, model_height = _cua_model_image_size[0]
    if name in _cua_relative_xy:
        native_x = round(float(x) * width / model_width)
        native_y = round(float(y) * height / model_height)
    else:
        native_x, native_y = _cua_to_native(x, y)
    actual_args, actual_kwargs = _cua_replace_xy(args, kwargs, indices, native_x, native_y)
    return actual_args, actual_kwargs, {"space": "displayed_model_screenshot_pixels",
        "x": x, "y": y, "native_x": native_x, "native_y": native_y,
        "source": "direct PyAutoGUI call scaled against latest full-screen screenshot"}
def _cua_native_coordinates(name, args, kwargs):
    indices = _cua_absolute_xy.get(name) or _cua_relative_xy.get(name)
    if indices is None: return None
    x, y = _cua_get_xy(args, kwargs, indices)
    return {"x": x, "y": y} if x is not None and y is not None else None
_cua_instrumented_methods = []
for _cua_method in ("click", "doubleClick", "tripleClick", "rightClick", "middleClick",
                    "moveTo", "moveRel", "dragTo", "dragRel", "mouseDown", "mouseUp",
                    "scroll", "hscroll", "vscroll", "write", "typewrite", "press",
                    "keyDown", "keyUp", "hotkey"):
    if hasattr(pyautogui, _cua_method):
        setattr(pyautogui, _cua_method, _cua_wrap_action(_cua_method, getattr(pyautogui, _cua_method)))
        _cua_instrumented_methods.append(_cua_method)
def _cua_to_native(x, y):
    if not _cua_coordinate_available[0]:
        raise ValueError("A fresh full-screen screenshot is required before coordinate-based GUI actions")
    width, height = pyautogui.size()
    model_width, model_height = _cua_model_image_size[0]
    if not (0 <= float(x) < model_width and 0 <= float(y) < model_height):
        raise ValueError("cua coordinates must fall within the displayed model screenshot bounds "
                         + str((model_width, model_height)) + "; received " + repr((x, y)))
    native_x = min(width - 1, max(0, round(float(x) * width / model_width)))
    native_y = min(height - 1, max(0, round(float(y) * height / model_height)))
    return native_x, native_y
def _cua_screenshot(path="/tmp/modularcua-screen.png"):
    _cua_action_sequence[0] += 1
    record = {"sequence": _cua_action_sequence[0], "action_id": str(uuid.uuid4()),
              "method": "screenshot", "arguments": {"path": path},
              "capability": _cua_capability_context[0],
              "requested_model_coordinates": None, "status": "running",
              "started_unix": time.time()}
    try:
        image = pyautogui.screenshot().convert("RGB")
        image.save(path, format="PNG")  # Preserve full-resolution guest evidence.
        model_image = image.copy(); model_image.thumbnail((1200, 1200))
        _cua_model_image_size[0] = tuple(model_image.size)
        _cua_coordinate_available[0] = True
        buffer = io.BytesIO(); model_image.save(buffer, format="JPEG", quality=82)
        record.update({"status": "executed", "native_image_size": list(image.size),
                       "model_image_size": list(model_image.size),
                       "duration_seconds": time.time() - record["started_unix"]})
        _cua_action_events.append(record); _cua_persist_actions()
        return ImageAttachment(path, base64.b64encode(buffer.getvalue()).decode("ascii"))
    except BaseException as exc:
        record.update({"status": "error", "exception": type(exc).__name__ + ": " + str(exc),
                       "duration_seconds": time.time() - record["started_unix"]})
        _cua_action_events.append(record); _cua_persist_actions()
        raise
def _cua_click(x, y, clicks=1):
    native_x, native_y = _cua_to_native(x, y)
    _cua_coordinate_context[0] = {"space": "displayed_model_screenshot_pixels", "x": x, "y": y,
                                  "native_x": native_x, "native_y": native_y}
    try: pyautogui.click(x=native_x, y=native_y, clicks=clicks)
    finally: _cua_coordinate_context[0] = None
    return {"executed": True, "coordinate_space": "displayed_model_screenshot_pixels"}
def _cua_drag(start_x, start_y, end_x, end_y, duration=0.5):
    native_start = _cua_to_native(start_x, start_y); native_end = _cua_to_native(end_x, end_y)
    _cua_coordinate_context[0] = {"space": "displayed_model_screenshot_pixels",
        "start": [start_x, start_y], "end": [end_x, end_y],
        "native_start": list(native_start), "native_end": list(native_end)}
    try:
        pyautogui.moveTo(*native_start); pyautogui.dragTo(*native_end, duration=duration)
    finally: _cua_coordinate_context[0] = None
    return {"executed": True, "coordinate_space": "displayed_model_screenshot_pixels"}
def _cua_type(text): pyautogui.write(text); return {"executed": True}
def _cua_hotkey(keys): pyautogui.hotkey(*keys); return {"executed": True}
def _cua_scroll(clicks, x=None, y=None):
    if x is None or y is None:
        pyautogui.scroll(clicks, x=x, y=y)
    else:
        native_x, native_y = _cua_to_native(x, y)
        _cua_coordinate_context[0] = {"space": "displayed_model_screenshot_pixels", "x": x, "y": y,
                                      "native_x": native_x, "native_y": native_y}
        try: pyautogui.scroll(clicks, x=native_x, y=native_y)
        finally: _cua_coordinate_context[0] = None
    return {"executed": True, "coordinate_space": "displayed_model_screenshot_pixels"}
def _cua_shell(command, timeout=60):
    p = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
def _cua_file_read(path): return {"text": pathlib.Path(path).read_text(encoding="utf-8")}
def _cua_file_write(path, text):
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    return {"bytes_written": p.write_text(text, encoding="utf-8")}
def _cua_open(target):
    p = subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"pid": p.pid}
_cua_handlers = {"screenshot": _cua_screenshot, "mouse_click": _cua_click, "mouse_drag": _cua_drag,
 "keyboard_type": _cua_type, "keyboard_hotkey": _cua_hotkey, "mouse_scroll": _cua_scroll,
 "shell": _cua_shell, "file_read": _cua_file_read, "file_write": _cua_file_write,
 "application_open": _cua_open}
def _cua_invoke(name, **kwargs):
    if name not in _cua_meta: raise KeyError("capability not registered: "+str(name))
    missing = [key for key in _cua_meta[name]["input_schema"].get("required", []) if key not in kwargs]
    if missing: raise ValueError("missing capability arguments: "+", ".join(missing))
    previous = _cua_capability_context[0]
    _cua_capability_context[0] = {"name": name, "arguments": _cua_json_safe(kwargs)}
    try: return _cua_handlers[name](**kwargs)
    finally: _cua_capability_context[0] = previous
def _cua_shortcut(name, argument_names):
    def call(*args, **kwargs):
        values = dict(zip(argument_names, args)); values.update(kwargs)
        return _cua_invoke(name, **values)
    return call
cua = types.SimpleNamespace(invoke=_cua_invoke, capabilities=list(_cua_meta.values()),
    screenshot=_cua_shortcut("screenshot", ("path",)),
    click=_cua_shortcut("mouse_click", ("x", "y", "clicks")),
    drag=_cua_shortcut("mouse_drag", ("start_x", "start_y", "end_x", "end_y", "duration")),
    type_text=_cua_shortcut("keyboard_type", ("text",)),
    hotkey=_cua_shortcut("keyboard_hotkey", ("keys",)),
    scroll=_cua_shortcut("mouse_scroll", ("clicks", "x", "y")),
    shell=_cua_shortcut("shell", ("command", "timeout")),
    read_file=_cua_shortcut("file_read", ("path",)),
    write_file=_cua_shortcut("file_write", ("path", "text")),
    open_app=_cua_shortcut("application_open", ("target",)))
print(json.dumps({"registered_capabilities": sorted(_cua_meta),
                  "instrumented_pyautogui_methods": _cua_instrumented_methods}))
'''
