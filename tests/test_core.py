import json
import copy
from pathlib import Path

from modularcua.host.agent import AgentLoop, _format_kernel_result
from modularcua.host.context import compact_messages
from modularcua.host.journal import SessionJournal
from modularcua.host.modules import EventBus, HookAction, Module
from modularcua.modules.verified import VerifiedExecutionModule
from modularcua.environments.osworld_v2.runner import _load_config


class FakeKernel:
    def __init__(self):
        self.values = {}

    def execute(self, code, timeout=None):
        if code.startswith("set "):
            _, key, value = code.split(" ", 2)
            self.values[key] = value
            return {"status": "ok", "outputs": [{"type": "text", "text": value}]}
        if code.startswith("get "):
            return {"status": "ok", "outputs": [{"type": "text", "text": self.values[code[4:]]}]}
        if code == "raise":
            return {"status": "error", "error": "RuntimeError: fixture"}
        return {"status": "ok", "outputs": []}


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        return next(self.replies)


def call(turn, call_id, code):
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function", "function": {
            "name": "ipython", "arguments": json.dumps({"code": code})
        }
    }], "_provider": {"usage": {"prompt_tokens": 10, "completion_tokens": 2},
                       "latency_seconds": 0.01, "request_id": f"r{turn}", "finish_reason": "tool_calls"}}


def done(turn):
    return {"role": "assistant", "content": "done", "tool_calls": None,
            "_provider": {"usage": {"prompt_tokens": 12, "completion_tokens": 1},
                          "latency_seconds": 0.01, "request_id": f"r{turn}", "finish_reason": "stop"}}


def test_persistent_tool_state_and_call_correlation(tmp_path):
    model = FakeModel([call(1, "c1", "set answer 42"), call(2, "c2", "get answer"), done(3)])
    kernel = FakeKernel()
    journal = SessionJournal(tmp_path, "episode")
    result = AgentLoop(model, kernel, journal, compact_after=100).run("task", "system")
    assert result["status"] == "finished"
    assert result["turns"] == 3 and result["tool_calls"] == 2
    assert result["input_tokens"] == 32 and result["output_tokens"] == 5
    events = [json.loads(line) for line in journal.path.read_text().splitlines()]
    calls = [e for e in events if e["event_type"] == "tool_call"]
    results = [e for e in events if e["event_type"] == "tool_result"]
    assert [e["tool_call_id"] for e in calls] == ["c1", "c2"]
    assert [e["tool_call_id"] for e in results] == ["c1", "c2"]
    assert "42" in results[1]["content"][0]["text"]


def test_compaction_preserves_original_instruction_and_tool_refs():
    instruction = "Never change the requested date."
    messages = [{"role": "system", "content": "rules"},
                {"role": "user", "content": instruction}]
    for i in range(4):
        messages.append({"role": "assistant", "tool_calls": [{"id": f"c{i}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result {i}"})
    compacted = compact_messages(messages, keep_recent=3, instruction=instruction, event_bus=EventBus())
    assert compacted[1]["content"] == instruction
    assert instruction in compacted[2]["content"]
    assert compacted[-2]["role"] == "assistant"
    assert compacted[-1]["tool_call_id"] == "c3"


def test_repeated_compaction_preserves_initial_screenshot_and_old_summary():
    instruction = "Use the visible desktop to complete the task."
    original_user_content = [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,initial-screen"}},
    ]
    messages = [{"role": "system", "content": "rules"},
                {"role": "user", "content": original_user_content}]
    for i in range(8):
        messages.append({"role": "assistant", "content": f"Observed checkpoint {i}.", "tool_calls": None})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result {i}"})
    first = compact_messages(messages, keep_recent=3, instruction=instruction, event_bus=EventBus())
    assert first[1] == {"role": "user", "content": original_user_content}
    assert first[2]["content"].startswith("Compacted prior interaction.")
    assert "Observed checkpoint 0." in first[2]["content"]

    for i in range(8, 16):
        first.append({"role": "assistant", "content": f"Later checkpoint {i}.", "tool_calls": None})
        first.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"later result {i}"})
    second = compact_messages(first, keep_recent=3, instruction=instruction, event_bus=EventBus())
    assert second[1] == {"role": "user", "content": original_user_content}
    assert second[2]["content"].startswith("Compacted prior interaction.")
    assert "Observed checkpoint 0." in second[2]["content"]
    assert "Later checkpoint 8." in second[2]["content"]


def test_disabled_modules_do_not_intercept_or_change_prompt(tmp_path):
    model = FakeModel([done(1)])
    journal = SessionJournal(tmp_path, "off")
    loop = AgentLoop(model, FakeKernel(), journal, modules=EventBus())
    loop.run("unchanged task", "unchanged system")
    assert model.requests[0][0] == [
        {"role": "system", "content": "unchanged system"},
        {"role": "user", "content": "unchanged task"},
    ]
    assert model.requests[0][1][0]["function"]["name"] == "ipython"


def test_before_finish_is_real_bounded_gate(tmp_path):
    model = FakeModel([done(1), call(2, "c2", "noop"), done(3)])
    module = VerifiedExecutionModule()
    journal = SessionJournal(tmp_path, "v1")
    result = AgentLoop(model, FakeKernel(), journal, modules=EventBus([module])).run("Do the task.", "system")
    assert result["status"] == "finished"
    assert module.finish_audit_used is True
    assert len(model.requests) == 3
    assert "Before finishing" in model.requests[1][0][-1]["content"]
    assert all(e.status == "UNKNOWN" for e in module.contracts)
    assert all(not e.operation_executed and not e.operation_succeeded for e in module.ledger.values())


def test_artifacts_are_content_addressed_and_immutable(tmp_path):
    journal = SessionJournal(tmp_path, "artifacts")
    first = journal.artifact(b"pixels", ".png", "image/png")
    second = journal.artifact(b"pixels", ".png", "image/png")
    assert first["sha256"] == second["sha256"]
    assert Path(first["path"]).read_bytes() == b"pixels"


def test_image_output_uses_typed_payload_not_text_marker(tmp_path):
    import base64
    journal = SessionJournal(tmp_path, "image")
    payload = base64.b64encode(b"jpeg-bytes").decode("ascii")
    content, artifacts = _format_kernel_result({"status": "ok", "outputs": [
        {"type": "text", "text": "a clipped __MODULARCUA_IMAGE__ marker is plain text"},
        {"type": "image", "path": "/tmp/test.jpg", "data": payload},
    ]}, journal)
    assert content[0]["type"] == "text"
    assert "clipped" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    image_url = content[1]["image_url"]["url"]
    assert base64.b64decode(image_url.split(",", 1)[1]) == b"jpeg-bytes"
    assert artifacts[0]["source_path"] == "/tmp/test.jpg"


def test_initial_screenshot_is_real_multimodal_user_content(tmp_path):
    import base64
    import io
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), (25, 80, 140)).save(buffer, format="PNG")
    model = FakeModel([done(1)])
    AgentLoop(model, FakeKernel(), SessionJournal(tmp_path, "initial-shot")).run(
        "Observe the desktop", "system", initial_screenshot=buffer.getvalue())
    content = model.requests[0][0][1]["content"]
    assert content[0]["text"] == "Observe the desktop"
    assert content[1]["type"] == "image_url"
    encoded = content[1]["image_url"]["url"].split(",", 1)[1]
    image = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert image.format == "JPEG" and image.size == (1200, 675)


def test_independent_guest_capability_descriptors_and_bootstrap_are_executable():
    import ast
    from modularcua.host.capabilities import GUEST_CAPABILITIES, guest_capability_bootstrap

    required = {"screenshot", "mouse_click", "mouse_drag", "keyboard_type", "keyboard_hotkey",
                "mouse_scroll", "shell", "file_read", "file_write", "application_open"}
    assert required == {item["name"] for item in GUEST_CAPABILITIES}
    assert all(item["description"] and item["input_schema"] and item["output_schema"]
               for item in GUEST_CAPABILITIES)
    bootstrap = guest_capability_bootstrap()
    ast.parse(bootstrap)
    assert "cua = types.SimpleNamespace" in bootstrap
    assert "Agent-S" not in bootstrap


def test_guest_screenshot_capability_returns_kernel_image_attachment(tmp_path, monkeypatch):
    import base64
    import io
    import sys
    import types
    from PIL import Image
    from modularcua.host.capabilities import guest_capability_bootstrap

    pyautogui = types.ModuleType("pyautogui")
    pyautogui.screenshot = lambda: Image.new("RGB", (1920, 1080), (2, 3, 4))
    pyautogui.size = lambda: (1920, 1080)
    pyautogui.click = pyautogui.moveTo = pyautogui.dragTo = lambda *args, **kwargs: None
    pyautogui.write = pyautogui.hotkey = pyautogui.scroll = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)

    class ImageAttachment:
        def __init__(self, path, data):
            self.path, self.data = path, data

    namespace = {"ImageAttachment": ImageAttachment}
    exec(guest_capability_bootstrap(), namespace)
    image_path = tmp_path / "shot.png"
    image = namespace["cua"].screenshot(path=str(image_path))
    assert isinstance(image, ImageAttachment)
    assert image.path == str(image_path)
    assert Image.open(image_path).size == (1920, 1080)
    model_image = Image.open(io.BytesIO(base64.b64decode(image.data)))
    assert model_image.format == "JPEG" and model_image.size == (1200, 675)


def test_guest_pyautogui_instrumentation_records_actions_without_double_counting(monkeypatch):
    import sys
    import types
    from modularcua.host.capabilities import guest_capability_bootstrap

    pyautogui = types.ModuleType("pyautogui")
    pyautogui.size = lambda: (1920, 1080)
    calls = []
    def mouse_down(*args, **kwargs): calls.append(("mouseDown", args, kwargs))
    def click(*args, **kwargs):
        calls.append(("click", args, kwargs))
        pyautogui.mouseDown(*args, **kwargs)
    pyautogui.click = click
    pyautogui.mouseDown = mouse_down
    pyautogui.moveTo = lambda *args, **kwargs: calls.append(("moveTo", args, kwargs))
    pyautogui.dragTo = lambda *args, **kwargs: calls.append(("dragTo", args, kwargs))
    pyautogui.write = pyautogui.hotkey = pyautogui.scroll = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)

    class ImageAttachment:
        def __init__(self, path, data): self.path, self.data = path, data

    namespace = {"ImageAttachment": ImageAttachment}
    exec(guest_capability_bootstrap(), namespace)
    namespace["cua"].click(12, 34)
    actions = namespace["_cua_action_events"]
    assert len(actions) == 1
    assert actions[0]["method"] == "click"
    assert actions[0]["arguments"] == {"args": [], "kwargs": {"x": 19, "y": 54, "clicks": 1}}
    assert actions[0]["requested_model_coordinates"] == {
        "space": "displayed_model_screenshot_pixels", "x": 12, "y": 34,
        "native_x": 19, "native_y": 54,
    }
    assert actions[0]["status"] == "executed"
    assert [call[0] for call in calls] == ["click", "mouseDown"]


def test_gui_action_journal_links_tool_call_and_post_action_screenshot(tmp_path):
    class ActionKernel(FakeKernel):
        def execute(self, code, timeout=None):
            return {"status": "ok", "outputs": [{"type": "text", "text": "clicked"}],
                    "executed_actions": [
                        {"sequence": 1, "action_id": "action-1", "method": "click",
                         "arguments": {"args": [], "kwargs": {"x": 20, "y": 30}},
                         "status": "executed", "duration_seconds": 0.01},
                        {"sequence": 2, "action_id": "action-2", "method": "screenshot",
                         "capability": {"name": "screenshot", "arguments": {}},
                         "arguments": {"path": "/tmp/shot.png"},
                         "status": "executed", "duration_seconds": 0.01},
                    ]}

    model = FakeModel([call(1, "click-call", "pyautogui.click(20, 30)"), done(2)])
    journal = SessionJournal(tmp_path, "gui-action-links")
    loop = AgentLoop(model, ActionKernel(), journal,
                     after_tool_observer=lambda turn, call_id: {"event_id": "screenshot-after-click"})
    result = loop.run("Click the button", "system")
    events = [json.loads(line) for line in journal.path.read_text().splitlines()]
    call_event = next(e for e in events if e["event_type"] == "tool_call")
    action_events = [e for e in events if e["event_type"] == "gui_action_executed"]
    action_event = next(e for e in action_events if e["primitive"] == "click")
    screenshot_action = next(e for e in action_events if e["primitive"] == "screenshot")
    observation_event = next(e for e in events if e["event_type"] == "gui_action_observation")
    tool_result = next(e for e in events if e["event_type"] == "tool_result")
    assert action_event["model_turn_id"] == 1
    assert action_event["tool_call_id"] == "click-call"
    assert action_event["parent_event_id"] == call_event["event_id"]
    assert observation_event["gui_action_event_id"] == action_event["event_id"]
    assert observation_event["screenshot_event_id"] == "screenshot-after-click"
    assert observation_event["fed_to_model"] is False
    assert observation_event["tool_result_event_id"] == tool_result["event_id"]
    assert observation_event["tool_result_appended_to_context"] is True
    assert observation_event["model_visible_image_artifact_ids"] == []
    assert result["pyautogui_action_attempts"] == 1
    assert result["pyautogui_actions_executed"] == 1
    assert tool_result["pyautogui_action_count"] == 1
    assert tool_result["gui_action_count"] == 2
    assert screenshot_action["instrumentation_scope"] == "registered cua screenshot capability"
    assert screenshot_action["capability"]["name"] == "screenshot"


def test_model_screenshot_coordinate_mapping_corners_and_direct_pyautogui(monkeypatch):
    import sys
    import types
    from modularcua.host.capabilities import guest_capability_bootstrap

    calls = []
    pyautogui = types.ModuleType("pyautogui")
    pyautogui.size = lambda: (1920, 1080)
    pyautogui.click = lambda *args, **kwargs: calls.append((args, kwargs))
    pyautogui.moveTo = pyautogui.dragTo = pyautogui.write = lambda *args, **kwargs: None
    pyautogui.hotkey = pyautogui.scroll = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    class ImageAttachment:
        def __init__(self, path, data): self.path, self.data = path, data
    namespace = {"ImageAttachment": ImageAttachment}
    exec(guest_capability_bootstrap(), namespace)
    invoke = namespace["cua"].invoke
    invoke("mouse_click", x=0, y=0)
    invoke("mouse_click", x=600, y=337)
    invoke("mouse_click", x=1199, y=674)
    # Direct PyAutoGUI calls use the same screenshot-coordinate contract as CUA.
    pyautogui.click(x=137, y=33)
    assert calls == [
        ((), {"x": 0, "y": 0, "clicks": 1}),
        ((), {"x": 960, "y": 539, "clicks": 1}),
        ((), {"x": 1918, "y": 1078, "clicks": 1}),
        ((), {"x": 219, "y": 53}),
    ]
    direct_event = namespace["_cua_action_events"][-1]
    assert direct_event["status"] == "executed"
    assert direct_event["requested_model_coordinates"]["x"] == 137
    assert direct_event["requested_model_coordinates"]["y"] == 33
    assert direct_event["executed_native_coordinates"] == {"x": 219, "y": 53}


def test_direct_pyautogui_uses_displayed_image_bounds_and_fails_closed(monkeypatch):
    import sys
    import types
    import pytest
    from modularcua.host.capabilities import guest_capability_bootstrap

    calls = []
    pyautogui = types.ModuleType("pyautogui")
    pyautogui.size = lambda: (1920, 1080)
    pyautogui.click = lambda *args, **kwargs: calls.append((args, kwargs))
    pyautogui.moveTo = pyautogui.dragTo = pyautogui.write = lambda *args, **kwargs: None
    pyautogui.hotkey = pyautogui.scroll = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    class ImageAttachment:
        def __init__(self, path, data): self.path, self.data = path, data
    namespace = {"ImageAttachment": ImageAttachment}
    exec(guest_capability_bootstrap(), namespace)
    with pytest.raises(ValueError, match="displayed model screenshot bounds"):
        pyautogui.click(1300, 800)
    assert calls == []
    assert namespace["_cua_action_events"][-1]["status"] == "error"
    namespace["_cua_coordinate_available"][0] = False
    with pytest.raises(RuntimeError, match="fresh full-screen screenshot"):
        pyautogui.click(100, 100)
    assert calls == []


def test_cua_rejects_coordinates_outside_displayed_image(monkeypatch):
    import sys
    import types
    import pytest
    from modularcua.host.capabilities import guest_capability_bootstrap
    pyautogui = types.ModuleType("pyautogui")
    pyautogui.size = lambda: (1920, 1080)
    pyautogui.click = pyautogui.moveTo = pyautogui.dragTo = lambda *args, **kwargs: None
    pyautogui.write = pyautogui.hotkey = pyautogui.scroll = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    class ImageAttachment:
        def __init__(self, path, data): self.path, self.data = path, data
    namespace = {"ImageAttachment": ImageAttachment}
    exec(guest_capability_bootstrap(), namespace)
    with pytest.raises(ValueError, match="displayed model screenshot bounds"):
        namespace["cua"].invoke("mouse_click", x=1500, y=850)


def test_cua_drag_and_scroll_convert_displayed_coordinates(monkeypatch):
    import sys
    import types
    from modularcua.host.capabilities import guest_capability_bootstrap
    calls = []
    pyautogui = types.ModuleType("pyautogui")
    pyautogui.size = lambda: (1920, 1080)
    pyautogui.click = lambda *a, **kw: None
    pyautogui.moveTo = lambda *a, **kw: calls.append(("moveTo", a, kw))
    pyautogui.dragTo = lambda *a, **kw: calls.append(("dragTo", a, kw))
    pyautogui.scroll = lambda *a, **kw: calls.append(("scroll", a, kw))
    pyautogui.write = pyautogui.hotkey = lambda *a, **kw: None
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    class ImageAttachment:
        def __init__(self, path, data): self.path, self.data = path, data
    namespace = {"ImageAttachment": ImageAttachment}
    exec(guest_capability_bootstrap(), namespace)
    namespace["cua"].invoke("mouse_drag", start_x=100, start_y=80,
                           end_x=1100, end_y=600, duration=0.25)
    namespace["cua"].invoke("mouse_scroll", clicks=-3, x=600, y=337)
    assert calls == [
        ("moveTo", (160, 128), {}),
        ("dragTo", (1760, 960), {"duration": 0.25}),
        ("scroll", (-3,), {"x": 960, "y": 539}),
    ]
    assert len(namespace["_cua_action_events"]) == 3
    assert all(row["capability"] for row in namespace["_cua_action_events"])


def test_p0_runner_has_no_top_level_egc_import():
    import ast

    path = Path("ModularCUA/src/modularcua/environments/osworld_v2/runner.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level_imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.append(node.module)
    assert not any(name.startswith("modularcua.egc") for name in top_level_imports)


def test_legacy_verified_config_name_resolves_to_observe_only_settings():
    cfg = _load_config(Path("ModularCUA/configs/verified_v1.yaml"))
    assert cfg["name"] == "modularcua-egc-observe-only-v1"
    assert cfg["model"]["revision"] == "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
    assert cfg["agent"]["max_model_steps"] == 150
    assert cfg["modules"]["verification"] is False
    assert cfg["modules"]["memory"] is False
    assert cfg["modules"]["recovery"] is False
    assert cfg["egc"]["modules"]["history_summarizer"] is False


def test_interrupted_runner_records_not_measured_and_partial_counts(tmp_path):
    from types import SimpleNamespace
    from modularcua.environments.osworld_v2.runner import _record_interruption

    journal = SessionJournal(tmp_path, "interrupted")
    manifest_path = journal.root / "run_manifest.json"
    manifest = {"run_id": "interrupted", "task_id": "001", "status": "RUNNING",
                "osworld_release_label": "OSWorld-v2.1"}
    manifest_path.write_text(json.dumps(manifest))
    agent = SimpleNamespace(model_turns=7, tool_calls=6, input_tokens=1200, output_tokens=240)

    event = _record_interruption(journal, manifest_path, manifest, agent)

    saved_manifest = json.loads(manifest_path.read_text())
    saved_result = json.loads((journal.root / "official_result.json").read_text())
    saved_events = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert event["event_type"] == "run_interrupted"
    assert saved_manifest["status"] == "INTERRUPTED_USER_REQUEST"
    assert saved_manifest["partial_counts"]["ipython_tool_calls"] == 6
    assert saved_manifest["partial_counts"]["gui_action_count"] == "NOT_DETERMINED_FROM_TOP_LEVEL_EVENTS"
    assert saved_result["status"] == "NOT_MEASURED"
    assert [row["event_type"] for row in saved_events] == ["run_interrupted"]


def test_interruption_after_evaluation_preserves_returned_official_score(tmp_path):
    from modularcua.environments.osworld_v2.runner import _record_interruption

    journal = SessionJournal(tmp_path, "after-evaluate")
    manifest_path = journal.root / "run_manifest.json"
    manifest = {"run_id": "after-evaluate", "task_id": "014", "status": "RUNNING",
                "osworld_release_label": "OSWorld-v2.1"}
    manifest_path.write_text(json.dumps(manifest))

    _record_interruption(journal, manifest_path, manifest, None, official_score=0.25)

    saved_manifest = json.loads(manifest_path.read_text())
    saved_result = json.loads((journal.root / "official_result.json").read_text())
    assert saved_manifest["status"] == "INTERRUPTED_AFTER_EVALUATION"
    assert saved_result["status"] == "MEASURED"
    assert saved_result["partial_score"] == 0.25
    assert saved_result["binary_success"] is False
