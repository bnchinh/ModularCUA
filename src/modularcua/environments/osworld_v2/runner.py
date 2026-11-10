from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

from modularcua.host.agent import AgentLoop
from modularcua.host.journal import SessionJournal
from modularcua.host.kernel import GuestIPythonKernel
from modularcua.host.model import OpenAICompatibleModel
from modularcua.host.modules import EventBus
from modularcua.host.prompt import IPYTHON_TOOL
from modularcua.host.skills import SKILL_SYSTEM_ADDENDUM, SkillCatalog, SkillRuntime
from task_loader import load_task_config


TASK_CLASS_SHA256 = {
    "001": "9f8731d02aacb37f6eed0e6e4c7738758c3d7c9fb1b1fa83a9ea08751af19839",
    "003": "0936ff7694f6ede9e0f1d51e02b590e711ff744e006d16e1b8465467160ccf18",
    "013": "75ea95a35b3cba2e98ad1e95dbaf883bcb1408f09201927a376804a62a94a1d6",
    "014": "73084d48899dbbb388d8747369ca0c3bd5fc338528cdff3045153a5f6698c4ff",
    "061": "cb25da0250c4b2e29488032e4e9da6bee89ef8af3a4e06ddceea3b411b2425c1",
}
ASSETS_REVISION = "384b3834faba5700a7b589e6cc181490c9808949"
PRIME_COMMIT = "a9b5d88b50db50860088772a408e867f8071b507"
TASK001_ASSET_HASHES = {
    "task_001/task_001_thunderbird-profile_fixed.tar.gz": "12fb0ff9786d1e1379de62455ce16989400306e3962a15ac3e3002bf3093eb05",
    "task_001/initial_calendar.ics": "f41735e9a6d1f3d1a5ee833c640aaa742ba816f6a9482fae0d18fe86d4df6e74",
    "task_001/gold_calendar.ics": "203f9ff6daddbb4dc41d2f2550d6f25bcf9e6e78ddcf36650fb1e4ba1542b081",
}
SUPPORTED_TASKS = {"001", "003", "013", "014", "061"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _configure_assets(repo_root: Path, task_id: str = "001") -> tuple[str, dict[str, str]]:
    """Pin task setup assets to local OSWorld-v2.1 sources; never expose GT to guest."""
    base = (repo_root / "cache/osworld_v2_assets").resolve()
    task_id = str(task_id).zfill(3)
    required: list[str]
    evaluator_only: list[str] = []
    if task_id == "001":
        required = ["task_001/task_001_thunderbird-profile_fixed.tar.gz",
                    "task_001/initial_calendar.ics"]
        evaluator_only = ["task_001/gold_calendar.ics"]
        file_hashes = TASK001_ASSET_HASHES
    elif task_id == "003":
        # This archived, checksummed local snapshot came from the gated OSWorld-v2.1
        # asset revision. Golden images remain on the host and are fetched only by evaluate().
        data_root = Path(os.environ.get("OSWORLD_DATA_ROOT", "/media/vlilab/DATA1/OSWorld-V2")).expanduser().resolve()
        base = (data_root / "task003_infra/assets/osworld_v2_assets_384b").resolve()
        task003_manifest_path = base / "manifest.json"
        task003_manifest = json.loads(task003_manifest_path.read_text(encoding="utf-8"))
        if task003_manifest.get("source_revision") != ASSETS_REVISION:
            raise RuntimeError(f"Task003 asset revision mismatch: {task003_manifest.get('source_revision')}")
        file_hashes = {"task_003/" + item["source_path"].split("task_003/", 1)[-1]: item["sha256"]
                       for item in task003_manifest.get("entries", [])}
        required = ["task_003/city.zip", "task_003/filter.zip", "task_003/weather_hongkong.pptx"]
        evaluator_only = ["task_003/golden_rainy.png", "task_003/golden_snowy.png"]
    elif task_id == "013":
        required = ["task_013/prize-items_fig.pdf", "task_013/state.json"]
        evaluator_only = ["task_013/all_gts.json"]
        manifest_path = base / "task_013_014_051_061_asset_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Pinned Task013 asset manifest missing: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != ASSETS_REVISION:
            raise RuntimeError(f"Task013 asset revision mismatch: {manifest.get('revision')} != {ASSETS_REVISION}")
        file_hashes = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    elif task_id == "014":
        required = ["task_014/Gatsby_Beautiful_Days_Essay_update.docx"]
        evaluator_only = ["task_014/Gatsby_Beautiful_Days_Essay_update_gt.docx"]
        manifest_path = base / "task_013_014_051_061_asset_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != ASSETS_REVISION:
            raise RuntimeError(f"Task014 asset revision mismatch: {manifest.get('revision')} != {ASSETS_REVISION}")
        file_hashes = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    elif task_id == "061":
        required = ["task_061/task_photos.zip"]
        evaluator_only = ["task_061/IMG_7318_edited.jpg"]
        manifest_path = base / "task_013_014_051_061_asset_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != ASSETS_REVISION:
            raise RuntimeError(f"Task061 asset revision mismatch: {manifest.get('revision')} != {ASSETS_REVISION}")
        file_hashes = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    else:
        raise ValueError(f"No reviewed asset contract for task {task_id}")
    hashes: dict[str, str] = {}
    for rel in required:
        asset_path = base / rel
        if not asset_path.is_file():
            raise FileNotFoundError(f"Pinned OSWorld asset missing: {asset_path}")
        if task_id == "001":
            metadata = Path(str(base / ".cache/huggingface/download" / rel) + ".metadata")
            if not metadata.is_file():
                raise FileNotFoundError(f"Pinned asset provenance metadata missing: {metadata}")
            commit = metadata.read_text(encoding="utf-8").splitlines()[0].strip()
            if commit != ASSETS_REVISION:
                raise RuntimeError(f"Task001 asset revision mismatch for {rel}: {commit} != {ASSETS_REVISION}")
        if task_id in {"001", "003", "013", "014", "061"}:
            if rel not in file_hashes:
                raise RuntimeError(f"Asset missing from pinned manifest: {rel}")
            if _sha256_file(asset_path) != file_hashes[rel]:
                raise RuntimeError(f"Pinned OSWorld asset hash mismatch for {rel}")
        hashes[rel] = _sha256_file(asset_path)
    for rel in evaluator_only:
        asset_path = base / rel
        if not asset_path.is_file():
            raise FileNotFoundError(f"Required official evaluator asset missing: {asset_path}")
        if task_id in {"001", "003", "013", "014", "061"}:
            if rel not in file_hashes:
                raise RuntimeError(f"Evaluator asset missing from pinned manifest: {rel}")
            if _sha256_file(asset_path) != file_hashes[rel]:
                raise RuntimeError(f"Pinned evaluator asset hash mismatch: {rel}")
    os.environ["OSWORLD_FILE_BASE_URL"] = str(base)
    return str(base), hashes


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Merge a small local config overlay without mutating the parent."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    parent = cfg.pop("extends", None)
    if parent:
        base_path = (path.parent / parent).resolve()
        with base_path.open(encoding="utf-8") as f:
            base = yaml.safe_load(f) or {}
        # Nested inheritance is supported for reproducible experiment overlays.
        if base.get("extends"):
            base = _load_config(base_path)
        cfg = _deep_merge(base, cfg)
    return cfg


def _guest_read(controller, path: str) -> dict | None:
    script = "import pathlib,json,base64; p=pathlib.Path(" + repr(path) + "); " \
             "print(json.dumps({'path':str(p),'exists':p.exists(),'data':base64.b64encode(p.read_bytes()).decode() if p.is_file() else None}))"
    result = controller.run_python_script(script, timeout=30)
    if not result or result.get("status") == "error":
        return None
    output = result.get("output", "")
    for line in reversed(str(output).splitlines()):
        try:
            value = json.loads(line)
            if value.get("exists") and value.get("data"):
                return json.loads(base64.b64decode(value["data"]))
            if value.get("exists"):
                return value
        except Exception:
            pass
    return None


def _filesystem_probe(controller) -> dict[str, dict]:
    script = r'''import json,pathlib,os
import hashlib
home=pathlib.Path('/home/user')
roots=[home/'Desktop',home/'Documents',home/'Downloads',home/'.local/share']
out={}; skip={'.cache','.thunderbird','.mozilla','Trash','Code Cache','Cache'}
hash_suffixes={'.ics','.docx','.xlsx','.xls','.ods','.odt','.pptx','.pdf','.csv','.tsv','.png','.jpg','.jpeg','.xcf'}
for root in roots:
 if not root.exists(): continue
 for p in root.rglob('*'):
  if not p.is_file() or any(part in skip for part in p.parts): continue
  try:
   st=p.stat(); row={'size':st.st_size,'mtime_ns':st.st_mtime_ns}
   if p.suffix.lower() in hash_suffixes and st.st_size <= 67108864:
    h=hashlib.sha256()
    with p.open('rb') as f:
     for block in iter(lambda:f.read(1048576),b''): h.update(block)
    row['sha256']=h.hexdigest()
    if p.suffix.lower()=='.ics':
     data=p.read_text(errors='replace'); row['icalendar_vevent_count']=data.count('BEGIN:VEVENT')
     row['icalendar_structurally_closed']=(data.count('BEGIN:VCALENDAR')==data.count('END:VCALENDAR')==1 and data.count('BEGIN:VEVENT')==data.count('END:VEVENT'))
   out[str(p)]=row
  except OSError: pass
print(json.dumps(out,separators=(',',':')))
'''
    result = controller.run_python_script(script, timeout=45)
    if not result or result.get("status") == "error":
        return {}
    for line in reversed(str(result.get("output", "")).splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    return {}


def _filesystem_probe_if_relevant(controller, code: str) -> dict[str, dict] | None:
    """Probe only after code that may materialize or change a user artifact."""
    if not re.search(r"open\s*\(|write|save|export|rename|replace|copy|move|download|unlink|remove|\.ics|\.docx|\.xlsx|\.pdf|\.pptx|\.ods", code, re.I):
        return None
    return _filesystem_probe(controller)


def _record_interruption(journal: SessionJournal, manifest_path: Path,
                         run_manifest: dict, agent: AgentLoop | None,
                         official_score: float | None = None) -> dict:
    """Persist an honest terminal record when a live episode receives Ctrl-C."""
    finished = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    partial = {
        "model_turns": getattr(agent, "model_turns", None),
        "ipython_tool_calls": getattr(agent, "tool_calls", None),
        "input_tokens": getattr(agent, "input_tokens", None),
        "output_tokens": getattr(agent, "output_tokens", None),
        "gui_action_count": "NOT_DETERMINED_FROM_TOP_LEVEL_EVENTS",
        "instrumented_pyautogui_action_attempts": getattr(agent, "pyautogui_action_attempts", None),
        "instrumented_pyautogui_actions_executed": getattr(agent, "pyautogui_actions_executed", None),
    }
    event = journal.append(
        "run_interrupted", reason="KeyboardInterrupt", signal="SIGINT",
        official_evaluation="COMPLETED" if official_score is not None else "NOT_RUN",
        official_score=official_score, partial_counts=partial,
    )
    if official_score is None:
        result = {
            "status": "NOT_MEASURED", "task_id": run_manifest.get("task_id"),
            "reason": "Episode interrupted before the official evaluator returned a score.",
            "interruption_event_id": event["event_id"],
        }
        run_manifest.update({
            "status": "INTERRUPTED_USER_REQUEST", "finished_utc": finished,
            "official_evaluation": "NOT_RUN", "official_partial_score": None,
            "official_binary_success": None,
        })
    else:
        binary_success = math.isclose(official_score, 1.0, rel_tol=0.0, abs_tol=1e-12)
        result = {
            "status": "MEASURED", "task_id": run_manifest.get("task_id"),
            "benchmark": run_manifest.get("osworld_release_label"),
            "partial_score": official_score, "binary_success": binary_success,
            "interruption_event_id": event["event_id"],
            "note": "Episode was interrupted after the official evaluator returned.",
        }
        run_manifest.update({
            "status": "INTERRUPTED_AFTER_EVALUATION", "finished_utc": finished,
            "official_evaluation": "COMPLETED", "official_partial_score": official_score,
            "official_binary_success": binary_success,
        })
    run_manifest["partial_counts"] = partial
    run_manifest["interruption_event_id"] = event["event_id"]
    skill_runtime = getattr(agent, "skills", None)
    if skill_runtime:
        run_manifest["skills"] = skill_runtime.manifest()
    egc_runtime = getattr(agent, "egc", None)
    if egc_runtime and isinstance(run_manifest.get("egc"), dict):
        run_manifest["egc"]["skill_instruction_bindings"] = list(
            egc_runtime.skill_instruction_bindings)
    module_calls_path = manifest_path.parent / "module_calls.jsonl"
    if module_calls_path.is_file() and isinstance(run_manifest.get("egc"), dict):
        try:
            run_manifest["egc"]["actor_feedback_injected"] = any(
                json.loads(line).get("event_type") == "egc_actor_feedback_delivered"
                for line in module_calls_path.read_text(encoding="utf-8").splitlines()
                if line.strip())
        except Exception:
            run_manifest["egc"]["actor_feedback_injected"] = None
    (manifest_path.parent / "official_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
    return event


def run_task(config_path: Path, output: Path, task_id: str = "001", stage: str = "p0") -> dict:
    repo_root = Path.cwd().resolve()
    cfg = _load_config(config_path)
    stage = stage.lower()
    if stage not in {"p0", "p1"}:
        raise ValueError("stage must be p0 or p1")
    task_id = str(task_id).zfill(3)
    if task_id not in SUPPORTED_TASKS:
        raise ValueError(f"Unsupported task {task_id}; expected one of {sorted(SUPPORTED_TASKS)}")
    if task_id == "013":
        os.environ.setdefault("WEBSITE_HOST_SUFFIX", "site.hku.icu")
    asset_base, task_asset_hashes = _configure_assets(repo_root, task_id)
    model_cfg = cfg["model"]
    env_cfg = cfg["environment"]
    task_path = repo_root / f"evaluation_examples/task_class/task_{task_id}.py"
    task_sha = hashlib.sha256(task_path.read_bytes()).hexdigest()
    if task_sha != TASK_CLASS_SHA256[task_id]:
        raise RuntimeError(f"Pinned Task{task_id} class SHA mismatch: {task_sha}")
    task = load_task_config(None, task_id=task_id, base_dir=str(repo_root/"evaluation_examples"), eval_version="v2")
    prompt_source_path = (repo_root / cfg.get("system_prompt", "ModularCUA/prompts/osworld_ipython_system.md")).resolve()
    system = prompt_source_path.read_text(encoding="utf-8").rstrip()
    skill_cfg = cfg.get("skills", {})
    skill_runtime = None
    if bool(skill_cfg.get("enabled", False)):
        skill_roots = []
        for configured_path in skill_cfg.get("directories", ["ModularCUA/skills"]):
            root = (repo_root / str(configured_path)).resolve()
            if not root.is_relative_to(repo_root):
                raise ValueError(f"skill directory must be inside the OSWorld checkout: {configured_path}")
            skill_roots.append(root)
        skill_catalog = SkillCatalog(
            skill_roots,
            max_skill_chars=int(skill_cfg.get("max_skill_chars", 30000)),
            max_resource_chars=int(skill_cfg.get("max_resource_chars", 20000)),
        )
        actual_tool_names = {IPYTHON_TOOL["function"]["name"]}
        configured_tool_names = set(skill_cfg.get("available_tools", actual_tool_names))
        unknown_tools = configured_tool_names - actual_tool_names
        if unknown_tools:
            raise ValueError("skills config declares unavailable tools: " + ", ".join(sorted(unknown_tools)))
        skill_runtime = SkillRuntime(
            skill_catalog, max_active=int(skill_cfg.get("max_active", 4)),
            max_total_skill_chars=int(skill_cfg.get("max_total_skill_chars", 60000)),
            max_total_resource_chars=int(skill_cfg.get("max_total_resource_chars", 40000)),
            available_tools=actual_tool_names,
        )
        system += "\n\n" + SKILL_SYSTEM_ADDENDUM + "\n\n" + skill_catalog.catalog_text()
    instruction = str(task.instruction).rstrip()
    output.mkdir(parents=True, exist_ok=True)
    mode_label = "P0" if stage == "p0" else "P1"
    feedback_enabled = stage == "p1" and bool(cfg.get("egc", {}).get("actor_feedback_enabled", False))
    actor_skills_enabled = bool(cfg.get("skills", {}).get("enabled", False))
    egc_skill_md_enabled = stage == "p1" and bool(cfg.get("egc", {}).get("skill_md_enabled", False))
    egc_mode = ("BOUNDED_FEEDBACK_EXPERIMENTAL" if feedback_enabled else
                "OBSERVE_ONLY" if stage == "p1" else "OFF")
    condition_label = ("P0_CORE" if stage == "p0" else
                       "P1_EGC_BOUNDED_FEEDBACK_EXPERIMENTAL" if feedback_enabled else
                       "P1_EGC_OBSERVE_ONLY")
    if actor_skills_enabled:
        condition_label += "_ACTOR_SKILLS"
    if egc_skill_md_enabled:
        condition_label += "_EGC_SKILLMD"
    episode_id = f"{mode_label.lower()}-task{task_id}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    journal = SessionJournal(output, episode_id)
    if stage == "p1":
        journal.execution_mode = condition_label
        journal.raw_actor_path = journal.root / "raw_actor_events.jsonl"
    model = OpenAICompatibleModel(
        endpoint=model_cfg["endpoint"],
        api_key=os.environ.get(model_cfg.get("api_key_env", "OPENAI_API_KEY"), "EMPTY"),
        model=model_cfg["model"], timeout=model_cfg["request_timeout_seconds"],
        max_tokens=model_cfg["max_tokens"], temperature=model_cfg["temperature"],
        top_p=model_cfg["top_p"],
    )
    qcow2 = repo_root / env_cfg["qcow2"]
    def git_value(path: Path, *args: str) -> str | None:
        try:
            return subprocess.check_output(["git", "-C", str(path), *args], text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return None
    source_files = sorted((repo_root / "ModularCUA/src/modularcua").rglob("*.py"))
    source_digest = hashlib.sha256()
    for file in source_files:
        source_digest.update(file.relative_to(repo_root).as_posix().encode())
        source_digest.update(file.read_bytes())
    prompt_artifact_path = journal.root / "system_prompt.txt"
    instruction_path = journal.root / "task_instruction.txt"
    prompt_artifact_path.write_text(system, encoding="utf-8")
    instruction_path.write_text(instruction, encoding="utf-8")
    run_manifest = {
        "run_id": episode_id, "status": "RUNNING",
        "condition": condition_label,
        "configured_condition": cfg["name"],
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host_pid": os.getpid(), "model": model_cfg,
        "model_revision": model_cfg["revision"], "model_endpoint_is_private_config_only": True,
        "prime_reference_commit_studied_only": PRIME_COMMIT,
        "agent_s4_runtime_dependency": False,
        "osworld_release_label": "OSWorld-v2.1",
        "osworld_checkout_revision": git_value(repo_root, "rev-parse", "HEAD"),
        "task_id": task_id, "task_class_path": str(task_path), "task_class_sha256": task_sha,
        "assets_revision_from_archived_run": ASSETS_REVISION,
        "asset_source": asset_base, "task_asset_sha256s": task_asset_hashes,
        "website_host_suffix": os.environ.get("WEBSITE_HOST_SUFFIX") if task_id == "013" else None,
        "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "system_prompt_path": str(prompt_source_path),
        "prompt_artifact": str(prompt_artifact_path),
        "qcow2_path": str(qcow2), "qcow2_sha256": _sha256_file(qcow2),
        "model_generation": {k: model_cfg.get(k) for k in ("temperature", "top_p", "max_tokens", "context_window")},
        "action_instrumentation": {
            "scope": "PyAutoGUI public calls plus registered cua screenshot capability; nested library calls are coalesced; shell/API GUI changes may be unobserved",
            "event_type": "gui_action_executed",
            "correlation_fields": ["model_turn_id", "tool_call_id", "parent_event_id", "gui_action_event_id", "screenshot_event_id", "tool_result_event_id"],
            "status_semantics": {"backend_call_status": "RETURNED or RAISED; not proof of visible effect",
                                 "effect_status": "NOT_ASSESSED unless independently checked from GUI evidence"},
        },
        "agent_budget": cfg["agent"], "environment": {**env_cfg, "task_id": task_id},
        "stage": stage.upper(), "modules": cfg.get("modules", {}),
        "egc": {"enabled": stage == "p1",
                "execution_mode": egc_mode,
                "module_config": cfg.get("egc", {}) if stage == "p1" else {},
                "skill_md_enabled": egc_skill_md_enabled,
                "actor_interference_allowed": feedback_enabled,
                "actor_feedback_injected": False},
        "skills": (skill_runtime.manifest() if skill_runtime else {"enabled": False}),
        "modularcua_source_sha256": source_digest.hexdigest(),
        "instruction_artifact": str(instruction_path),
        "historical_trajectories_replayed": False,
        "credentials": "not recorded",
    }
    manifest_path = output / episode_id / "run_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
    (output / episode_id / "config.json").write_text(json.dumps({
        "resolved_config": cfg, "task_id": task_id,
        "execution_mode": condition_label,
        "task_class_sha256": task_sha,
        "system_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    from desktop_env.desktop_env import DesktopEnv
    start = time.monotonic()
    old_storage_dir = os.environ.get("OSWORLD_DOCKER_STORAGE_DIR")
    run_storage_dir = output / episode_id / "docker-storage"
    run_storage_dir.mkdir(parents=True, exist_ok=True)
    os.environ["OSWORLD_DOCKER_STORAGE_DIR"] = str(run_storage_dir.resolve())
    run_manifest["docker_guest_storage_dir"] = str(run_storage_dir.resolve())
    manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
    env = None
    egc = None
    if stage == "p1":
        from modularcua.egc.runtime import EGCRuntime
        egc_config = {**cfg.get("egc", {}), "model_revision": model_cfg.get("revision"),
                      "execution_mode": egc_mode}
        egc = EGCRuntime(output / episode_id, journal, model, egc_config)
        if egc.skill_catalog:
            run_manifest["egc"]["skill_catalog"] = {
                "discovered": [skill.public_record() for skill in egc.skill_catalog.skills.values()],
                "invalid": list(egc.skill_catalog.invalid),
            }
    egc_finalized = False
    kernel = None
    agent = None
    score = None
    status = "infrastructure_error"
    result: dict = {}
    try:
        env = DesktopEnv(
            provider_name=env_cfg["provider"], path_to_vm=str(repo_root / env_cfg["qcow2"]),
            action_space=env_cfg["action_space"], screen_size=tuple(env_cfg["screen_size"]),
            headless=env_cfg["headless"], os_type="Ubuntu", require_a11y_tree=False,
            cache_dir=str(output / "cache"), force_disable_recording=False,
        )
        env.reset(task_config=task)
        run_manifest["docker_container_id"] = getattr(getattr(env.provider, "container", None), "id", None)
        run_manifest["docker_host_ports"] = {
            "screenshot_api": getattr(env.provider, "server_port", None),
            "vnc": getattr(env.provider, "vnc_port", None),
            "chrome_debug": getattr(env.provider, "chromium_port", None),
            "stream": getattr(env.provider, "vlc_port", None),
        }
        run_manifest["actual_vm_start_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
        env.controller.start_recording()
        journal.append("environment_setup", source="official task class setup",
                       agent_s_pack_staged=False, status="completed")
        kernel = GuestIPythonKernel(env.controller.execute_python_command, lambda p: _guest_read(env.controller, p),
                                    timeout=cfg["agent"]["max_tool_seconds"])
        kernel_info = kernel.start()
        journal.append("kernel_started", **kernel_info)
        journal.append("capability_registry_loaded", status="completed",
                       capabilities=kernel_info.get("capabilities", []),
                       instrumented_pyautogui_methods=kernel_info.get("instrumented_pyautogui_methods", []),
                       action_count_scope="PyAutoGUI public calls; direct shell/API GUI mutations may be unobserved",
                       source="ModularCUA host/capabilities.py guest bootstrap")
        preflight = []
        preflight.append(kernel.execute("modularcua_kernel_probe = {'value': 73, 'marker': 'persistent'}"))
        persistence = kernel.execute("assert modularcua_kernel_probe['value'] == 73; print('persistent namespace OK')")
        if persistence.get("status") != "ok":
            raise RuntimeError(f"Persistent guest IPython preflight failed: {persistence}")
        preflight.append(persistence)
        io_result = kernel.execute("import sys; print('stdout probe'); print('stderr probe', file=sys.stderr)")
        preflight.append(io_result)
        exception_result = kernel.execute("raise RuntimeError('exception capture probe')")
        if exception_result.get("status") != "error":
            raise RuntimeError(f"Guest IPython did not capture an exception: {exception_result}")
        preflight.append(exception_result)
        subprocess_result = kernel.execute("import subprocess; p=subprocess.run(['bash','-lc','exit 7']); print('returncode='+str(p.returncode))")
        preflight.append(subprocess_result)
        image_probe = kernel.execute("from PIL import Image; Image.new('RGB',(64,48),(20,80,120)).save('/tmp/modularcua-preflight.png'); await attach_image('/tmp/modularcua-preflight.png')")
        preflight.append(image_probe)
        image_content, image_refs = __import__("modularcua.host.agent", fromlist=["_format_kernel_result"])._format_kernel_result(image_probe, journal)
        if not any(part.get("type") == "image_url" for part in image_content):
            raise RuntimeError(f"Guest IPython image attachment preflight failed: {image_probe}")
        journal.append("kernel_preflight", checks=["persistent namespace", "stdout/stderr", "exception",
                                                     "subprocess return code", "image attachment"],
                       status="passed", results=preflight, artifacts=image_refs)
        # Do not leak preflight state into the task's persistent namespace.
        kernel.execute("del modularcua_kernel_probe")
        screenshot = env.controller.get_screenshot()
        initial_screenshot_event = None
        if screenshot:
            ref = journal.artifact(screenshot, ".png", "image/png")
            initial_screenshot_event = journal.append("screenshot", phase="initial", evidence=ref, fed_to_model=True)
        bus = EventBus()
        if egc:
            egc.set_initial_screenshot(initial_screenshot_event, screenshot)
        def capture_after_tool(turn: int, tool_call_id: str) -> dict[str, Any] | None:
            shot = env.controller.get_screenshot()
            if shot:
                ref = journal.artifact(shot, ".png", "image/png")
                screenshot_event = journal.append("screenshot", model_turn_id=turn, tool_call_id=tool_call_id,
                                                  phase="after_ipython_cell", evidence=ref, fed_to_model=False)
                if egc:
                    egc.observed_screenshot(screenshot_event, shot, phase="after_ipython_cell",
                                            model_turn_id=turn, tool_call_id=tool_call_id)
                return screenshot_event
            return None

        agent = AgentLoop(
            model, kernel, journal,
            max_steps=cfg["agent"]["max_model_steps"],
            compact_after=cfg["agent"]["compact_after_messages"],
            keep_recent=cfg["agent"]["recent_messages_to_keep"], modules=bus,
            after_tool_observer=capture_after_tool,
            artifact_probe=(lambda code: _filesystem_probe_if_relevant(env.controller, code)) if stage == "p1" else None,
            egc=egc,
            skills=skill_runtime,
            max_wall_seconds=cfg["environment"]["timeout_seconds"],
            max_tool_output_chars=cfg["agent"]["max_tool_output_chars"],
        )
        result = agent.run(instruction, system, initial_screenshot=screenshot)
        final_shot = env.controller.get_screenshot()
        if final_shot:
            ref = journal.artifact(final_shot, ".png", "image/png")
            final_event = journal.append("screenshot", phase="final_before_evaluation", evidence=ref, fed_to_model=False)
            if egc:
                egc.observed_screenshot(final_event, final_shot, phase="final_before_evaluation",
                                        model_turn_id=result.get("turns"))
        evaluator_output = io.StringIO()
        evaluator_log_path = output / episode_id / "evaluator.log"
        try:
            with contextlib.redirect_stdout(evaluator_output), contextlib.redirect_stderr(evaluator_output):
                score = float(env.evaluate())
        except Exception as exc:
            evaluator_text = evaluator_output.getvalue()
            evaluator_log_path.write_text(evaluator_text, encoding="utf-8")
            if evaluator_text:
                sys.stdout.write(evaluator_text)
            journal.append("official_evaluation_error", error=repr(exc),
                           output_log=str(evaluator_log_path),
                           output_sha256=hashlib.sha256(evaluator_text.encode("utf-8")).hexdigest())
            raise
        evaluator_text = evaluator_output.getvalue()
        evaluator_log_path.write_text(evaluator_text, encoding="utf-8")
        evaluator_sha256 = hashlib.sha256(evaluator_text.encode("utf-8")).hexdigest()
        if evaluator_text:
            sys.stdout.write(evaluator_text)
        journal.append("official_evaluation_completed", score=score,
                       binary_success=math.isclose(score, 1.0, rel_tol=0.0, abs_tol=1e-12),
                       output_log=str(evaluator_log_path), output_sha256=evaluator_sha256,
                       output_characters=len(evaluator_text))
        status = "scored"
        summary = {
            "episode_id": episode_id, "status": status, "condition": condition_label,
            "configured_condition": cfg["name"],
            "task_id": task_id, "benchmark": "OSWorld-v2.1", "partial_score": score,
            "binary_success": bool(math.isclose(score, 1.0, rel_tol=0.0, abs_tol=1e-12)),
            "evaluator_log": str(evaluator_log_path), "evaluator_log_sha256": evaluator_sha256,
            "model_turns": result.get("turns"),
            "ipython_tool_calls": result.get("tool_calls"), "elapsed_seconds": time.monotonic()-start,
            "instrumented_pyautogui_action_attempts": result.get("pyautogui_action_attempts"),
            "instrumented_pyautogui_actions_executed": result.get("pyautogui_actions_executed"),
            "gui_action_count_scope": "PyAutoGUI public calls only; shell/API GUI mutations may be unobserved",
            "kernel": kernel_info, "task_instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
            "task_class_sha256": task_sha, "official_task_class": str(task_path),
            "official_evaluator": f"DesktopEnv.evaluate() -> pinned Task{task_id}.evaluate",
            "result_status": result.get("status"),
            "input_tokens": result.get("input_tokens"), "output_tokens": result.get("output_tokens"),
            "limitation": "The host loop and IPython namespace are independent of Prime. Request construction and prompt behavior are Prime-inspired, not byte-identical to Prime/pi-ai.",
        }
        (output / episode_id / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (output / episode_id / "official_result.json").write_text(json.dumps({
            "status": "MEASURED", "task_id": task_id, "benchmark": "OSWorld-v2.1",
            "partial_score": score, "binary_success": summary["binary_success"],
            "evaluator": summary["official_evaluator"], "task_class_sha256": task_sha,
            "evaluator_log": str(evaluator_log_path), "evaluator_log_sha256": evaluator_sha256,
        }, indent=2), encoding="utf-8")
        if egc:
            egc.finalize(summary)
            run_manifest["egc"]["skill_instruction_bindings"] = list(
                egc.skill_instruction_bindings)
            run_manifest["egc"]["actor_feedback_injected"] = (
                egc.metrics["actor_feedback_deliveries"] > 0)
            from modularcua.egc.audit import write_live_reports
            write_live_reports(output / episode_id, summary)
            egc_finalized = True
        run_manifest["skills"] = (skill_runtime.manifest() if skill_runtime
                                   else {"enabled": False})
        run_manifest.update({"status": "COMPLETED_SCORED", "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "official_partial_score": score, "official_binary_success": summary["binary_success"],
                             "evaluator_log": str(evaluator_log_path), "evaluator_log_sha256": evaluator_sha256,
                             "result_status": result.get("status"), "model_turns": result.get("turns"),
                             "ipython_tool_calls": result.get("tool_calls"),
                             "instrumented_pyautogui_action_attempts": result.get("pyautogui_action_attempts"),
                             "instrumented_pyautogui_actions_executed": result.get("pyautogui_actions_executed"),
                             "input_tokens": result.get("input_tokens"), "output_tokens": result.get("output_tokens"),
                             "elapsed_seconds": summary["elapsed_seconds"]})
        manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
        return summary
    except KeyboardInterrupt:
        _record_interruption(journal, manifest_path, run_manifest, agent, score)
        raise
    except Exception as exc:
        journal.append("runner_error", error=repr(exc))
        (output / episode_id / "infrastructure_error.json").write_text(json.dumps({"status": status, "error": repr(exc)}, indent=2))
        (output / episode_id / "official_result.json").write_text(json.dumps({
            "status": "NOT_MEASURED", "task_id": task_id,
            "reason": "Runner/evaluator did not produce a valid official result.",
            "error_type": type(exc).__name__, "error": repr(exc),
        }, indent=2), encoding="utf-8")
        run_manifest.update({"status": "INFRASTRUCTURE_ERROR", "error": repr(exc),
                             "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        run_manifest["skills"] = (skill_runtime.manifest() if skill_runtime
                                   else {"enabled": False})
        manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
        if egc and not egc_finalized:
            not_measured = {"status": "NOT_MEASURED", "task_id": task_id,
                            "partial_score": None, "binary_success": None,
                            "infrastructure_error": repr(exc)}
            try:
                egc.finalize(not_measured)
                from modularcua.egc.audit import write_live_reports
                write_live_reports(output / episode_id, not_measured)
                egc_finalized = True
            except Exception as audit_exc:
                journal.append("egc_module_error", module_name="runtime", module_call_id=None,
                               model_turn_id=None, tool_call_id=None, triggering_event_id=None,
                               as_of_event_seq=journal.event_seq, status="ERROR",
                               error="Failed writing failure-time EGC projections: " + repr(audit_exc))
            run_manifest["egc"]["actor_feedback_injected"] = (
                egc.metrics["actor_feedback_deliveries"] > 0)
            run_manifest["egc"]["skill_instruction_bindings"] = list(
                egc.skill_instruction_bindings)
            manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
        raise
    finally:
        if kernel:
            try: kernel.stop()
            except Exception: pass
        if env is not None:
            try:
                env.controller.end_recording(str(output / episode_id / "recording.mp4"))
            except Exception:
                pass
            try: env.close()
            except Exception: pass
        if old_storage_dir is None:
            os.environ.pop("OSWORLD_DOCKER_STORAGE_DIR", None)
        else:
            os.environ["OSWORLD_DOCKER_STORAGE_DIR"] = old_storage_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("ModularCUA/configs/core_v0.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", default=None, help="Task ID; defaults to config environment.task_id")
    parser.add_argument("--stage", choices=["p0", "p1"], default="p0")
    args = parser.parse_args()
    task_id = args.task_id
    if task_id is None:
        task_id = str(_load_config(args.config).get("environment", {}).get("task_id", "001"))
    summary = run_task(args.config, args.output, task_id=task_id, stage=args.stage)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
