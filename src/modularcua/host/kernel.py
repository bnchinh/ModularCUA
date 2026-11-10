from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any, Callable

from modularcua.host.capabilities import GUEST_CAPABILITIES, guest_capability_bootstrap


class GuestKernelTimeout(TimeoutError):
    def __init__(self, message: str, executed_actions: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.executed_actions = executed_actions or []


class GuestIPythonKernel:
    """Host bridge for an IPython kernel in the guest.

    The DesktopEnv /execute endpoint is the only transport. A small guest
    worker owns one persistent IPython InteractiveShell and processes cells
    serially through an atomic file mailbox. No host-side code can bypass the
    VM permission boundary.
    """

    def __init__(self, guest_exec: Callable[[str], dict[str, Any] | None],
                 guest_read: Callable[[str], dict[str, Any] | None],
                 *, timeout: float = 120):
        self.guest_exec = guest_exec
        self.guest_read = guest_read
        self.timeout = timeout
        self.root = "/tmp/modularcua-kernel"
        self.worker_pid: int | None = None

    @staticmethod
    def _q(s: str) -> str:
        return "'" + s.replace("'", "'\\''") + "'"

    def start(self) -> dict[str, Any]:
        root = self.root
        bootstrap = f'''import os, sys, time, json, uuid, pathlib, subprocess, textwrap
root=pathlib.Path({root!r}); root.mkdir(parents=True, exist_ok=True)
worker=root/"worker.py"
source={_GUEST_WORKER!r}
worker.write_text(source, encoding="utf-8")
log=open(root/"worker.log","ab",buffering=0)
p=subprocess.Popen([sys.executable,str(worker),str(root)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)
print(json.dumps({{"pid":p.pid,"worker":str(worker)}}))
'''
        result = self.guest_exec(bootstrap)
        output = str((result or {}).get("output", ""))
        payload = _last_json_line(output)
        if not payload or "pid" not in payload:
            raise RuntimeError(f"Guest IPython bridge failed to start: {result!r}")
        self.worker_pid = int(payload["pid"])
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = self.guest_read(f"{root}/ready.json")
            if state and state.get("status") == "ready":
                capability_result = self.execute(guest_capability_bootstrap(), timeout=45)
                if capability_result.get("status") != "ok":
                    raise RuntimeError(f"Could not register guest capabilities: {capability_result}")
                capability_text = "\n".join(
                    output.get("text", "") for output in capability_result.get("outputs", [])
                    if output.get("type") == "text")
                capability_metadata = _last_json_line(capability_text) or {}
                return {"pid": self.worker_pid, "kernel_pid": state.get("kernel_pid"),
                        "kernel_name": "ipykernel", "transport": "guest-file-mailbox-v1",
                        "capabilities": GUEST_CAPABILITIES,
                        "instrumented_pyautogui_methods": capability_metadata.get("instrumented_pyautogui_methods", [])}
            time.sleep(0.5)
        logs = self.guest_read(f"{root}/worker.log")
        raise TimeoutError(f"Guest kernel did not become ready: {logs}")

    def execute(self, code: str, *, timeout: float | None = None) -> dict[str, Any]:
        call_id = str(uuid.uuid4())
        root = self.root
        request = json.dumps({"call_id": call_id, "code": code}, ensure_ascii=False)
        write_code = (
            "import pathlib, json; p=pathlib.Path(" + repr(f"{root}/inbox/{call_id}.json") + "); "
            "p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix('.tmp'); "
            "tmp.write_text(" + repr(request) + ",encoding='utf-8'); tmp.replace(p); print('QUEUED')"
        )
        queued = self.guest_exec(write_code)
        if queued is None:
            raise RuntimeError("Could not submit IPython cell to guest bridge")
        deadline = time.monotonic() + (timeout or self.timeout)
        result_path = f"{root}/outbox/{call_id}.json"
        while time.monotonic() < deadline:
            result = self.guest_read(result_path)
            if result and result.get("call_id") == call_id:
                return result
            time.sleep(0.4)
        # The persistent IPython process owns the shell; SIGINT is its bounded
        # interruption path and preserves namespace whenever the cell unwinds.
        action_path = f"{root}/actions/{call_id}.json"
        try:
            action_payload = self.guest_read(action_path)
        except Exception:
            action_payload = None
        executed_actions = action_payload if isinstance(action_payload, list) else []
        if self.worker_pid:
            try:
                self.guest_exec("import os,signal; os.kill(" + str(self.worker_pid) + ", signal.SIGINT)")
            except Exception:
                pass
        raise GuestKernelTimeout(f"IPython cell {call_id} exceeded {timeout or self.timeout}s",
                                 executed_actions=executed_actions)

    def stop(self) -> None:
        self.guest_exec("import pathlib; pathlib.Path(" + repr(f"{self.root}/stop") + ").touch()")


def _last_json_line(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    return None


_GUEST_WORKER = r'''from __future__ import annotations
import base64, contextlib, io, json, os, pathlib, signal, sys, time, traceback
from IPython.core.interactiveshell import InteractiveShell

root=pathlib.Path(sys.argv[1]); inbox=root/"inbox"; outbox=root/"outbox"
inbox.mkdir(parents=True,exist_ok=True); outbox.mkdir(parents=True,exist_ok=True)
shell=InteractiveShell.instance()
ns=shell.user_ns
ns["_modularcua_action_root"]=str(root)
async def attach_image(path):
    from PIL import Image
    image=Image.open(path).convert("RGB")
    source_size=tuple(image.size); image.thumbnail((1200,1200))
    model_size=tuple(image.size)
    if "_cua_model_image_size" in globals():
        current=tuple(_cua_model_image_size[0])
        native=tuple(globals().get("_cua_guest_screen_size", ()))
        is_fullscreen=(source_size == current or source_size == native or model_size == current)
        _cua_coordinate_available[0]=is_fullscreen
        if is_fullscreen: _cua_model_image_size[0]=model_size
    buffer=io.BytesIO(); image.save(buffer,format="JPEG",quality=82)
    return ImageAttachment(str(path),base64.b64encode(buffer.getvalue()).decode("ascii"))
class ImageAttachment:
    def __init__(self,path,data): self.path,self.data=path,data
    def __repr__(self): return "ImageAttachment(path="+repr(self.path)+")"
ns["attach_image"]=attach_image
ns["ImageAttachment"]=ImageAttachment
(root/"ready.json").write_text(json.dumps({"status":"ready","kernel_pid":os.getpid()}))

def publish(req, result):
    target=outbox/(req["call_id"]+".json"); tmp=target.with_suffix(".tmp")
    tmp.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8"); tmp.replace(target)

while not (root/"stop").exists():
    if (root/"interrupt").exists():
        (root/"interrupt").unlink(missing_ok=True)
    requests=sorted(inbox.glob("*.json"))
    if not requests:
        time.sleep(0.1); continue
    p=requests[0]
    action_events=[]; action_start=0
    try:
        req=json.loads(p.read_text(encoding="utf-8")); p.unlink(missing_ok=True)
        ns["_modularcua_active_call_id"]=req["call_id"]
        action_events=ns.get("_cua_action_events", [])
        action_start=len(action_events)
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result=shell.run_cell(req["code"],store_history=True)
        cell_actions=action_events[action_start:]
        del action_events[action_start:]
        ns["_modularcua_active_call_id"]=None
        outputs=[]
        if stdout.getvalue(): outputs.append({"type":"text","text":stdout.getvalue()})
        if stderr.getvalue(): outputs.append({"type":"text","text":"STDERR: "+stderr.getvalue()})
        if result.result is not None:
            try:
                if isinstance(result.result, ImageAttachment):
                    outputs.append({"type":"image","path":result.result.path,"data":result.result.data})
                else:
                    outputs.append({"type":"text","text":repr(result.result)})
            except Exception: pass
        err=None
        if result.error_before_exec is not None: err=repr(result.error_before_exec)
        if result.error_in_exec is not None: err=repr(result.error_in_exec)
        publish(req,{"call_id":req["call_id"],"status":"error" if err else "ok",
                     "execution_count":result.execution_count,"outputs":outputs,"error":err,
                     "executed_actions":cell_actions})
    except BaseException as exc:
        try:
            cell_actions=action_events[action_start:]
            del action_events[action_start:]
            ns["_modularcua_active_call_id"]=None
            publish(req,{"call_id":req.get("call_id","unknown"),"status":"error",
                         "error":traceback.format_exc(),"executed_actions":cell_actions})
        except Exception: pass
'''
