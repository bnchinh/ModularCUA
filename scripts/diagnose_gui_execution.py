#!/usr/bin/env python3
"""Live, disposable OSWorld guest diagnostic for ModularCUA GUI execution.

This intentionally does not load a benchmark task or call its evaluator. It
tests direct /execute, the persistent InteractiveShell, the registered `cua`
capabilities, and a bounded frozen-model -> IPython -> GUI -> screenshot loop.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml
from PIL import Image

from desktop_env.desktop_env import DesktopEnv
from modularcua.host.agent import AgentLoop
from modularcua.host.journal import SessionJournal
from modularcua.host.kernel import GuestIPythonKernel
from modularcua.host.model import OpenAICompatibleModel
from modularcua.host.modules import EventBus


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guest_read(controller, path: str) -> dict | None:
    code = (
        "import pathlib,json,base64; p=pathlib.Path(" + repr(path) + "); "
        "print(json.dumps({'exists':p.exists(),'data':base64.b64encode(p.read_bytes()).decode() "
        "if p.is_file() else None}))"
    )
    result = controller.run_python_script(code, timeout=30)
    if not result:
        return None
    for line in reversed(str(result.get("output", "")).splitlines()):
        try:
            item = json.loads(line)
            if item.get("exists") and item.get("data"):
                import base64
                raw = base64.b64decode(item["data"])
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    return {"text": raw.decode("utf-8", errors="replace")}
            if item.get("exists"):
                return item
        except Exception:
            continue
    return None


def save_screenshot(journal: SessionJournal, controller, label: str) -> dict:
    data = controller.get_screenshot()
    if not data:
        raise RuntimeError(f"OSWorld screenshot endpoint returned no image for {label}")
    ref = journal.artifact(data, ".png", "image/png")
    event = journal.append("screenshot", phase=label, evidence=ref, fed_to_model=False)
    return {"event_id": event["event_id"], **ref}


def locate_point(model: OpenAICompatibleModel, journal: SessionJournal, screenshot: dict,
                 instruction: str) -> dict:
    image = Image.open(screenshot["path"]).convert("RGB")
    image.thumbnail((1200, 1200))
    buffer = io.BytesIO(); image.save(buffer, format="JPEG", quality=82)
    image_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    prompt = ("Inspect only the attached current GUI screenshot. " + instruction +
              " Return only one JSON object exactly as {\"x\": integer, \"y\": integer}; "
              "do not include analysis or other text. Coordinates refer to this displayed screenshot image, "
              "which is at most 1200 pixels wide/high.")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_url}}
    ]}]
    journal.append("visual_target_request", prompt=prompt, screenshot_event_id=screenshot["event_id"],
                   screenshot_sha256=screenshot["sha256"], model=model.model)
    raw = model.complete_aux(messages, max_tokens=512)
    journal.append("visual_target_response", response=raw,
                   screenshot_event_id=screenshot["event_id"], prompt=prompt)
    content = str(raw.get("content") or raw.get("reasoning") or "")
    match = re.search(r"\{\s*\"x\"\s*:\s*(\d+)\s*,\s*\"y\"\s*:\s*(\d+)\s*\}", content)
    if not match:
        return {"status": "PARSE_FAILED", "raw_content": content}
    return {"status": "PARSED", "x": int(match.group(1)), "y": int(match.group(2)),
            "raw_content": content}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ModularCUA/configs/core_v0.yaml")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    storage = output / "docker-storage"
    storage.mkdir(parents=True, exist_ok=True)
    os.environ["OSWORLD_DOCKER_STORAGE_DIR"] = str(storage)
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    env_cfg, model_cfg = cfg["environment"], cfg["model"]
    episode_id = "gui-diagnostic-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    journal = SessionJournal(output, episode_id)
    env = None
    kernel = None
    editor_kernel = None
    result: dict = {"episode_id": episode_id, "status": "RUNNING", "benchmark_task_loaded": False,
                    "official_evaluator_called": False, "phases": {}}
    try:
        env = DesktopEnv(
            provider_name="docker", path_to_vm=str(root / env_cfg["qcow2"]),
            action_space="pyautogui", screen_size=tuple(env_cfg["screen_size"]),
            headless=True, os_type="Ubuntu", require_a11y_tree=False,
            force_disable_recording=True, cache_dir=str(output / "cache"),
        )
        env.reset(task_config=None)
        result["container_id"] = getattr(getattr(env.provider, "container", None), "id", None)
        result["host_ports"] = {k: getattr(env.provider, attr, None) for k, attr in {
            "execute": "server_port", "vnc": "vnc_port", "screenshot_stream": "vlc_port",
        }.items()}
        result["screen_size_configured"] = list(env_cfg["screen_size"])
        result["screenshot_initial"] = save_screenshot(journal, env.controller, "diagnostic_initial")
        # DesktopEnv can return a black boot frame immediately after reset.
        # Let the existing desktop session settle before measuring its APIs.
        time.sleep(5)
        result["screenshot_desktop_settled"] = save_screenshot(journal, env.controller, "diagnostic_desktop_settled")

        # A1: direct OSWorld /execute, separate process from the persistent shell.
        direct_probe = r'''import os,json,shutil,subprocess,pyautogui
keys=['DISPLAY','XAUTHORITY','XDG_SESSION_TYPE','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS']
values={k:os.environ.get(k) for k in keys}
diag={'uid':os.getuid(),'gid':os.getgid(),'cwd':os.getcwd(),'session_env':{
 'DISPLAY':values['DISPLAY'],'XDG_SESSION_TYPE':values['XDG_SESSION_TYPE'],
 'XDG_RUNTIME_DIR_present':bool(values['XDG_RUNTIME_DIR']),
 'XAUTHORITY_present':bool(values['XAUTHORITY']),
 'DBUS_SESSION_BUS_ADDRESS_present':bool(values['DBUS_SESSION_BUS_ADDRESS'])},
 'pyautogui_version':getattr(pyautogui,'__version__','unknown'),
 'screen_size':list(pyautogui.size()),'mouse_before':list(pyautogui.position()),
 'xdotool_path':shutil.which('xdotool'),
 'xdotool_display_geometry':subprocess.run(['xdotool','getdisplaygeometry'],capture_output=True,text=True).stdout.strip(),
 'session_namespaces':{n:os.readlink('/proc/self/ns/'+n) for n in ['pid','mnt','user']}}
try:
 rows=subprocess.check_output(['ps','-eo','pid=,uid=,gid=,comm='],text=True).splitlines()
 display_names={'Xorg','Xwayland','Xvfb','gnome-shell','gnome-session-b','gnome-session-c','mutter','xfce4-session'}
 processes=[]
 for row in rows:
  parts=row.split(None,3)
  if len(parts)==4 and parts[3] in display_names:
   pid=int(parts[0]); proc_env={}
   try:
    env=open('/proc/'+str(pid)+'/environ','rb').read().split(b'\\0')
    envkeys={item.split(b'=',1)[0].decode(errors='ignore') for item in env if b'=' in item}
    proc_env={'DISPLAY_present':b'DISPLAY' in envkeys,'XAUTHORITY_present':b'XAUTHORITY' in envkeys,
      'XDG_RUNTIME_DIR_present':b'XDG_RUNTIME_DIR' in envkeys,'DBUS_SESSION_BUS_ADDRESS_present':b'DBUS_SESSION_BUS_ADDRESS' in envkeys}
   except Exception: pass
   try: namespaces={n:os.readlink('/proc/'+str(pid)+'/ns/'+n) for n in ['pid','mnt','user']}
   except Exception: namespaces={}
   processes.append({'pid':pid,'uid':int(parts[1]),'gid':int(parts[2]),'comm':parts[3],
      'namespaces':namespaces,'session_env_presence':proc_env})
 diag['desktop_processes']=processes
except Exception as e: diag['desktop_process_probe_error']=type(e).__name__+': '+str(e)
try:
 window=subprocess.run(['xdotool','getactivewindow','getwindowname'],capture_output=True,text=True,timeout=3)
 diag['active_window']={'returncode':window.returncode,'title':window.stdout.strip() if window.returncode==0 else None}
except Exception as e: diag['active_window_error']=type(e).__name__+': '+str(e)
try:
 shot=pyautogui.screenshot(); diag['pyautogui_screenshot_size']=list(shot.size)
except Exception as e: diag['pyautogui_screenshot_error']=type(e).__name__+': '+str(e)
w,h=pyautogui.size(); target=(w//2,h//2)
try:
 pyautogui.moveTo(*target,duration=0.1); diag['mouse_after']=list(pyautogui.position())
 diag['move_matches_target']=tuple(pyautogui.position())==target
except Exception as e: diag['move_error']=type(e).__name__+': '+str(e)
print(json.dumps(diag))'''
        direct = env.controller.execute_python_command(direct_probe, timeout=45)
        result["phases"]["direct_execute"] = {"raw_result": direct}
        journal.append("direct_execute_probe", raw_result=direct,
                       interpretation="Separate OSWorld /execute process; mouse position and screenshot were probed")
        result["screenshots"] = [result["screenshot_initial"],
                                  save_screenshot(journal, env.controller, "after_direct_execute")]

        # A2/A3: same guest process owns all InteractiveShell calls and capability state.
        kernel = GuestIPythonKernel(env.controller.execute_python_command,
                                    lambda p: guest_read(env.controller, p), timeout=60)
        kernel_info = kernel.start()
        result["phases"]["kernel_start"] = kernel_info
        journal.append("kernel_started", **kernel_info)
        first = kernel.execute("modularcua_persistence_probe={'value':771,'tag':'same-kernel'}")
        second = kernel.execute("import os,pyautogui,json,subprocess; print(json.dumps({'marker':modularcua_persistence_probe,'pid':os.getpid(),'uid':os.getuid(),'gid':os.getgid(),'display':os.getenv('DISPLAY'),'session_type':os.getenv('XDG_SESSION_TYPE'),'runtime_dir_present':bool(os.getenv('XDG_RUNTIME_DIR')),'xauthority_present':bool(os.getenv('XAUTHORITY')),'dbus_present':bool(os.getenv('DBUS_SESSION_BUS_ADDRESS')),'screen_size':list(pyautogui.size()),'pyautogui_screenshot_size':list(pyautogui.screenshot().size),'xdotool_display_geometry':subprocess.run(['xdotool','getdisplaygeometry'],capture_output=True,text=True).stdout.strip(),'mouse':list(pyautogui.position())}))")
        result["phases"]["persistent_shell"] = {"write_status": first.get("status"),
                                                   "read_status": second.get("status"),
                                                   "read_outputs": second.get("outputs"),
                                                   "worker_pid": kernel_info.get("pid"),
                                                   "kernel_pid": kernel_info.get("kernel_pid")}
        journal.append("persistent_shell_probe", first=first, second=second)

        # Open a harmless GUI target through the guest and ground actions in its screenshot.
        launch = kernel.execute("import subprocess,time; p=subprocess.Popen(['gnome-calendar'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); time.sleep(5); print({'pid':p.pid})")
        result["phases"]["calendar_launch"] = launch
        calendar_before = save_screenshot(journal, env.controller, "calendar_before_actor")
        result["screenshots"].append(calendar_before)
        prompt_path = (root / cfg["system_prompt"]).resolve()
        system = prompt_path.read_text(encoding="utf-8").rstrip()
        instruction = (
            "This is a disposable GUI execution smoke test, not a benchmark task. "
            "Use direct pyautogui.click(x, y) for the two mouse actions in this smoke test; do not use cua mouse actions. "
            "For direct PyAutoGUI mouse actions, coordinates are in the attached full-screen screenshot's displayed pixels, "
            "and ModularCUA converts them to native guest pixels. Do not multiply or otherwise rescale coordinates. "
            "From the screenshot, locate the left month-navigation arrow immediately beside Today in GNOME Calendar. "
            "In one IPython tool call, click that arrow once with pyautogui.click(x, y), save a fresh full-screen screenshot, "
            "and attach it with `await attach_image(path)`. After that screenshot returns to you, use a separate IPython tool call "
            "to click the right month-navigation arrow once with pyautogui.click(x, y), then attach another fresh full-screen "
            "screenshot the same way. Do not use shell, files, DBus, or application APIs to change the calendar. "
            "Finally report only what month labels you can see in the returned screenshots and whether the view returned."
        )
        model = OpenAICompatibleModel(
            endpoint=model_cfg["endpoint"], api_key=os.environ.get(model_cfg.get("api_key_env", "OPENAI_API_KEY"), "EMPTY"),
            model=model_cfg["model"], timeout=model_cfg["request_timeout_seconds"],
            max_tokens=model_cfg["max_tokens"], temperature=model_cfg.get("temperature"),
            top_p=model_cfg.get("top_p"),
        )

        def after_tool(turn: int, call_id: str):
            shot = save_screenshot(journal, env.controller, f"actor_after_tool_turn_{turn}")
            journal.append("fresh_observation", model_turn_id=turn, tool_call_id=call_id,
                           screenshot_event_id=shot["event_id"], fed_to_model=False)
            return shot

        loop = AgentLoop(model, kernel, journal, max_steps=6, compact_after=50,
                         keep_recent=12, modules=EventBus(), after_tool_observer=after_tool,
                         max_wall_seconds=600, max_tool_output_chars=30000)
        actor_result = loop.run(instruction, system, initial_screenshot=env.controller.get_screenshot())
        result["phases"]["model_to_tool_loop"] = {
            "status": actor_result.get("status"), "model_turns": actor_result.get("turns"),
            "ipython_calls": actor_result.get("tool_calls"),
            "input_tokens": actor_result.get("input_tokens"), "output_tokens": actor_result.get("output_tokens"),
            "answer": actor_result.get("answer"),
            "instrumented_pyautogui_action_attempts": actor_result.get("pyautogui_action_attempts"),
            "instrumented_pyautogui_backend_returns": actor_result.get("pyautogui_actions_executed"),
        }
        result["screenshots"].append(save_screenshot(journal, env.controller, "after_actor_loop"))

        # Exercise registered text, hotkey, scroll, and screenshot capabilities
        # in a fresh persistent shell, since an Actor may overwrite a Python
        # global such as `cua`. A vision call selects the text region from its
        # actual screenshot; coordinates are checked against native dimensions.
        kernel.stop()
        editor_kernel = GuestIPythonKernel(env.controller.execute_python_command,
                                           lambda p: guest_read(env.controller, p), timeout=60)
        editor_kernel.root = "/tmp/modularcua-gui-diagnostic-kernel"
        editor_info = editor_kernel.start()
        result["phases"]["editor_kernel"] = editor_info
        editor_launch = editor_kernel.execute(
            "import subprocess,time; p=subprocess.Popen(['gnome-text-editor'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); time.sleep(5); print({'pid':p.pid})"
        )
        editor_shot = save_screenshot(journal, env.controller, "text_editor_before_input")
        result["screenshots"].append(editor_shot)
        point = locate_point(model, journal, editor_shot,
                             "Give a point safely inside the main blank text editing area, away from toolbar buttons and dialogs.")
        native = env.controller.execute_python_command(
            "import pyautogui,json; print(json.dumps({'size':list(pyautogui.size())}))", timeout=30)
        size_match = re.search(r"\"size\"\s*:\s*\[(\d+)\s*,\s*(\d+)\]", str(native))
        screen_size = (int(size_match.group(1)), int(size_match.group(2))) if size_match else tuple(env_cfg["screen_size"])
        model_width = int(round(screen_size[0] * min(1.0, 1200.0 / max(screen_size))))
        model_height = int(round(screen_size[1] * min(1.0, 1200.0 / max(screen_size))))
        point_ok = point.get("status") == "PARSED" and 0 <= point["x"] < model_width and 0 <= point["y"] < model_height
        editor_test: dict = {"launch_result": editor_launch, "target_point": point,
                             "native_screen_size": list(screen_size),
                             "model_screenshot_size": [model_width, model_height], "point_in_bounds": point_ok}
        if point_ok:
            click = editor_kernel.execute(f"cua.invoke('mouse_click',x={point['x']},y={point['y']})")
            typed = editor_kernel.execute("cua.invoke('keyboard_type',text='MODULARCUA_GUI_SMOKE_20261105')")
            typed_shot = save_screenshot(journal, env.controller, "text_editor_after_typing")
            result["screenshots"].append(typed_shot)
            select = editor_kernel.execute("cua.invoke('keyboard_hotkey',keys=['ctrl','a'])")
            selected_shot = save_screenshot(journal, env.controller, "text_editor_after_select_all")
            result["screenshots"].append(selected_shot)
            fill = editor_kernel.execute("""for i in range(70):
    cua.invoke('keyboard_type',text=f'SCROLL_LINE_{i:02d}')
    cua.invoke('keyboard_hotkey',keys=['enter'])
""")
            home = editor_kernel.execute("cua.invoke('keyboard_hotkey',keys=['ctrl','home'])")
            home_shot = save_screenshot(journal, env.controller, "text_editor_before_scroll")
            result["screenshots"].append(home_shot)
            scroll = editor_kernel.execute(f"cua.invoke('mouse_scroll',clicks=-5,x={point['x']},y={point['y']})")
            scroll_shot = save_screenshot(journal, env.controller, "text_editor_after_scroll")
            result["screenshots"].append(scroll_shot)
            editor_test.update({"click": click, "keyboard_type": typed, "hotkey_ctrl_a": select,
                                "multiline_fill": fill, "hotkey_ctrl_home": home,
                                "scroll": scroll, "after_typing_screenshot": typed_shot,
                                "after_select_screenshot": selected_shot,
                                "before_scroll_screenshot": home_shot,
                                "after_scroll_screenshot": scroll_shot})
        else:
            editor_test["live_keyboard_test"] = "SKIPPED: visual target was not parsed/in-bounds"
        result["phases"]["editor_capability_tests"] = editor_test
        journal.append("editor_capability_test", **editor_test)
        result["status"] = "COMPLETED_DIAGNOSTIC"
    except BaseException as exc:
        result["status"] = "DIAGNOSTIC_ERROR"
        result["error"] = type(exc).__name__ + ": " + str(exc)
        journal.append("diagnostic_error", error=result["error"])
        raise
    finally:
        if kernel is not None:
            try:
                kernel.stop()
            except Exception:
                pass
        if editor_kernel is not None:
            try:
                editor_kernel.stop()
            except Exception:
                pass
        if env is not None:
            try:
                env.close()
            except Exception as exc:
                result["cleanup_error"] = repr(exc)
        result["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (output / episode_id / "diagnostic_summary.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "COMPLETED_DIAGNOSTIC" else 1


if __name__ == "__main__":
    raise SystemExit(main())
