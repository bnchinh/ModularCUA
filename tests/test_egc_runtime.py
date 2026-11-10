import json
from pathlib import Path

from modularcua.egc.runtime import EGCRuntime
from modularcua.host.agent import AgentLoop
from modularcua.host.journal import SessionJournal
from modularcua.host.modules import EventBus


class FakeKernel:
    def execute(self, code, timeout=None):
        return {"status": "ok", "outputs": [{"type": "text", "text": "executed"}]}


class FakeAuxModel:
    model = "qwen38-27b-test-double"
    max_tokens = 200

    def __init__(self, on_call=None):
        self.requests = []
        self.on_call = on_call

    def complete_aux(self, messages, *, max_tokens):
        self.requests.append(messages)
        if self.on_call:
            value = self.on_call(messages)
        else:
            value = response_for(messages)
        return {"content": json.dumps(value), "_provider": {
            "request_id": f"aux-{len(self.requests)}",
            "usage": {"prompt_tokens": 17, "completion_tokens": 11},
            "latency_seconds": 0.01, "finish_reason": "stop",
        }}

    def complete(self, messages, tools):
        self.actor_request = messages
        return {"content": "done", "tool_calls": None,
                "_provider": {"usage": {}, "latency_seconds": 0.01,
                              "request_id": "actor-1", "finish_reason": "stop"}}


def request_payload(messages):
    content = messages[1]["content"]
    text = next(x["text"] for x in content if x.get("type") == "text")
    return json.loads(text)


def response_for(messages):
    prompt = messages[0]["content"]
    user = request_payload(messages)
    refs = user.get("evidence_refs", [])
    ids = [r["event_id"] for r in refs]
    if "Requirement Contract Builder" in prompt:
        return {"requirements": [{"requirement_id": "R1", "description": "Complete the requested task.",
                                   "source_quote": user["task_instruction"], "source_event_ids": ids[:1],
                                   "constraint_type": "EXPLICIT", "required_evidence": ["current state"],
                                   "verification_method": "visual or deterministic evidence", "status": "UNKNOWN"}],
                "source_event_ids": ids[:1], "unresolved_requirements": ["R1"],
                "missing_sources": [], "ambiguities": []}
    if "Visual State Interpreter" in prompt:
        return {"snapshot_event_id": user["snapshot_event_id"],
                "state_updates": [{"fact_id": "window", "entity": "window", "property": "visible",
                                   "value": True, "source_type": "TRANSIENT_GUI", "confidence": 0.9,
                                   "evidence_ids": ids[-1:], "environment_version": user["environment_version"],
                                   "freshness": "CURRENT"}],
                "potentially_stale_facts": [], "contradictions": [], "missing_evidence": []}
    if "independent evidence-grounded postcondition verifier" in prompt:
        reqs = user["requirements"].get("requirements", [])
        return {"snapshot_event_id": user["snapshot_event_id"],
                "verdicts": [{"requirement_id": r["requirement_id"], "verdict": "UNKNOWN",
                              "confidence": 0.0, "evidence_ids": [], "observed_property": "",
                              "expected_property": r["description"], "reason": "insufficient evidence",
                              "missing_evidence": ["independent readback"], "suggested_check": None}
                             for r in reqs]}
    if "update versioned task requirement contracts" in prompt:
        return {"unchanged_requirement_ids": ["R1"], "newly_discovered_constraints": [],
                "revised_requirement_definitions": [], "source_evidence_refs": ids,
                "unresolved_ambiguities": [], "contradictions": []}
    if "causal recovery planning module" in prompt:
        return {"decision": "NO_REPAIR", "failure_type": "UNKNOWN", "requirement_id": None,
                "supporting_event_ids": [], "suspected_cause": None, "cause_confidence": 0.0,
                "repair_instruction": None, "preserve_requirements": [], "verification_plan": [],
                "reason": "No supported failure."}
    if "summarize only execution history" in prompt:
        return {"summary": {"original_constraints": [], "observed_actions": [], "verified_progress": [],
                             "unverified_claims": [], "unresolved_requirements": [], "failed_attempts": [],
                             "current_state": [], "artifacts": [], "next_pending_objective": ""},
                "source_event_ids": ids}
    if "Task instruction" in prompt:
        return {"requirements": [], "source_event_ids": ids, "unresolved_requirements": [],
                "missing_sources": [], "ambiguities": []}
    raise AssertionError(f"Unexpected module prompt: {prompt[:80]}")


def first_model_output(tmp_path):
    for path in (tmp_path / "episode/module_outputs").glob("*.json"):
        doc = json.loads(path.read_text())
        if "raw_text" in doc:
            return doc
    raise AssertionError("No model response artifact recorded")


def make_runtime(tmp_path, model=None, **config):
    journal = SessionJournal(tmp_path, "episode")
    runtime = EGCRuntime(tmp_path / "episode", journal, model or FakeAuxModel(), config)
    return journal, runtime


def test_task_start_input_excludes_future_evidence_and_records_exact_request(tmp_path):
    journal, runtime = make_runtime(tmp_path)
    event = journal.append("task_start", instruction="Inspect a source document later.")
    runtime.task_start(event, "Inspect a source document later.")
    module_input = json.loads(next((tmp_path / "episode/module_inputs").glob("*.snapshot.json")).read_text())
    visible = json.dumps(module_input["model_visible_messages"])
    assert "FUTURE_VALUE_987" not in visible
    journal_events = [json.loads(x) for x in journal.path.read_text().splitlines()]
    first_module_trigger = next(e for e in journal_events if e["event_type"] == "egc_module_triggered"
                                and e["module_name"] == "requirement_contracts")
    assert module_input["evidence_cutoff_sequence"] == first_module_trigger["as_of_event_seq"]
    assert "data:image" not in visible  # task-start extractor received no fabricated screenshot
    events = [json.loads(x) for x in journal.path.read_text().splitlines()]
    assert any(e["event_type"] == "egc_module_response" for e in events)
    assert len({e["event_seq"] for e in events}) == len(events)


def test_deterministic_module_call_persists_exact_input_and_output(tmp_path):
    journal, runtime = make_runtime(tmp_path)
    trigger = journal.append("tool_result", tool_call_id="tc-2", output="saved file")
    payload = {"artifact_path": "/home/user/Documents/result.ics",
               "sha256": "abc123", "evidence_refs": [{"event_id": trigger["event_id"]}]}
    result = runtime.deterministic("provenance_tracker", trigger, "artifact_snapshot", payload)
    event = json.loads(journal.path.read_text().splitlines()[-1])
    input_path = Path(event["input_snapshot_ref"])
    output_path = Path(event["output_ref"])
    assert json.loads(input_path.read_text()) == payload
    assert json.loads(output_path.read_text())["result"]["result"] == payload
    assert event["input_payload_sha256"]
    assert event["result"] == result["result"]


def test_invalid_future_citation_is_rejected_and_raw_output_preserved(tmp_path):
    journal = SessionJournal(tmp_path, "episode")
    future_id = "future-event-not-in-snapshot"

    def malicious(messages):
        if "Requirement Contract Builder" in messages[0]["content"]:
            return {"requirements": [{"requirement_id": "R1", "description": "x", "source_quote": "x",
                                      "source_event_ids": [future_id], "constraint_type": "EXPLICIT",
                                      "required_evidence": [], "verification_method": "x", "status": "UNKNOWN"}],
                    "source_event_ids": [future_id], "unresolved_requirements": [],
                    "missing_sources": [], "ambiguities": []}
        return response_for(messages)

    runtime = EGCRuntime(tmp_path / "episode", journal, FakeAuxModel(malicious), {})
    event = journal.append("task_start", instruction="Do one thing.")
    runtime.task_start(event, "Do one thing.")
    assert runtime.contract_versions == []
    output = first_model_output(tmp_path)
    assert output["raw_text"] and output["accepted"] is False
    assert future_id in output["unknown_citations"]


def test_delayed_response_cannot_cite_event_after_frozen_cutoff(tmp_path):
    journal = SessionJournal(tmp_path, "episode")
    future = {}

    def late_response(messages):
        future_event = journal.append("future_tool_result", content="future only")
        future["event"] = future_event
        return {"requirements": [{"requirement_id": "R1", "description": "x", "source_quote": "x",
                                  "source_event_ids": [future_event["event_id"]], "constraint_type": "EXPLICIT",
                                  "required_evidence": [], "verification_method": "x", "status": "UNKNOWN"}],
                "source_event_ids": [future_event["event_id"]], "unresolved_requirements": [],
                "missing_sources": [], "ambiguities": []}

    runtime = EGCRuntime(tmp_path / "episode", journal, FakeAuxModel(late_response), {})
    event = journal.append("task_start", instruction="Task")
    runtime.task_start(event, "Task")
    output = first_model_output(tmp_path)
    assert future["event"]["event_seq"] > output["as_of_event_seq"]
    assert output["accepted"] is False
    assert future["event"]["event_id"] in output["unknown_citations"]


def test_malformed_json_is_not_repaired(tmp_path):
    def malformed(messages):
        return {"raw": "not-json"}

    class MalformedModel(FakeAuxModel):
        def complete_aux(self, messages, *, max_tokens):
            return {"content": "<think>not available as structured output", "_provider": {
                "request_id": "bad", "usage": {"prompt_tokens": 1, "completion_tokens": 2},
                "latency_seconds": 0.01, "finish_reason": "stop"}}

    journal, runtime = make_runtime(tmp_path, MalformedModel())
    event = journal.append("task_start", instruction="Task")
    runtime.task_start(event, "Task")
    output = first_model_output(tmp_path)
    assert output["raw_text"] == "<think>not available as structured output"
    assert output["accepted"] is False and output["parsed_output"] is None
    assert not runtime.contract_versions


def test_unsupported_pass_is_rejected(tmp_path):
    journal, runtime = make_runtime(tmp_path)
    start = journal.append("task_start", instruction="Do one thing.")
    runtime.task_start(start, "Do one thing.")
    finish = journal.append("agent_finish", response="I did it.")
    payload_ref = runtime._record_evidence(finish, text="I did it.", source_type="ACTOR_FINISH_CLAIM")

    class PassModel(FakeAuxModel):
        def complete_aux(self, messages, *, max_tokens):
            user = request_payload(messages)
            req = user["requirements"]["requirements"][0]
            return {"content": json.dumps({"snapshot_event_id": user["snapshot_event_id"], "verdicts": [{
                "requirement_id": req["requirement_id"], "verdict": "PASS", "confidence": 1,
                "evidence_ids": [], "observed_property": "done", "expected_property": "done",
                "reason": "unsupported", "missing_evidence": [], "suggested_check": None}]}),
                "_provider": {"request_id": "pass", "usage": {}, "latency_seconds": 0.01}}

    runtime.model = __import__("modularcua.egc.runtime", fromlist=["EGCModelAdapter"]).EGCModelAdapter(PassModel())
    result = runtime.infer("self_verifier", finish, {
        "trigger_reason": "controlled_test", "snapshot_event_id": finish["event_id"],
        "task_instruction": "Do one thing.", "requirements": runtime.contract_versions[-1],
        "evidence_refs": [payload_ref],
    })
    assert result["accepted"] is False
    assert not runtime.verdicts


def test_stale_transient_state_is_invalidated_by_new_screenshot(tmp_path):
    journal, runtime = make_runtime(tmp_path, visual_state_every_n_screenshots=99)
    task = journal.append("task_start", instruction="Task")
    runtime.task_start(task, "Task")
    first = journal.append("screenshot", phase="fixture-1")
    runtime.state["old-win"] = {"source_type": "TRANSIENT_GUI", "evidence_ids": [first["event_id"]],
                            "freshness": "CURRENT"}
    second = journal.append("screenshot", phase="fixture-2")
    runtime.observed_screenshot(second, b"authentic-test-image-bytes", phase="fixture-2")
    assert runtime.state["old-win"]["freshness"] == "STALE"


def test_actor_prompt_and_tool_schema_are_unchanged_in_observe_only(tmp_path):
    actor1 = FakeAuxModel()
    baseline = AgentLoop(actor1, FakeKernel(), SessionJournal(tmp_path / "base", "base")).run("Task", "System")
    actor2 = FakeAuxModel()
    journal = SessionJournal(tmp_path / "egc", "egc")
    runtime = EGCRuntime(tmp_path / "egc" / "egc", journal, FakeAuxModel(), {})
    observed = AgentLoop(actor2, FakeKernel(), journal, modules=EventBus(), egc=runtime).run("Task", "System")
    assert actor1.actor_request == actor2.actor_request
    assert baseline["status"] == observed["status"] == "finished"
    assert runtime.actor_request_hashes[0]["payload_sha256"] == runtime._sha(
        json.dumps(actor2.actor_request, ensure_ascii=False, separators=(",", ":"), default=str).encode())


def test_termination_is_live_advisory_and_not_injected(tmp_path):
    actor = FakeAuxModel()
    journal = SessionJournal(tmp_path, "episode")
    runtime = EGCRuntime(tmp_path / "episode", journal, FakeAuxModel(), {})
    result = AgentLoop(actor, FakeKernel(), journal, egc=runtime).run("Task", "System")
    events = [json.loads(x) for x in journal.path.read_text().splitlines()]
    term = [e for e in events if e["event_type"] == "egc_termination_decision"]
    assert result["status"] == "finished"
    assert len(term) == 1 and term[0]["intervention_delivered"] is False


def test_tool_success_is_not_task_verification(tmp_path):
    journal, runtime = make_runtime(tmp_path)
    task = journal.append("task_start", instruction="Make a change.")
    runtime.task_start(task, "Make a change.")
    call = journal.append("tool_call", tool_call_id="tc1", arguments={"code": "print('ok')"})
    result = journal.append("tool_result", tool_call_id="tc1", is_error=False,
                           content="ok", artifacts=[])
    runtime.tool_result(call, result, "print('ok')", "ok", [], is_error=False,
                        model_turn_id=1, tool_call_id="tc1")
    assert runtime.verdicts == []
    assert runtime.requirement_status == {}
    assert runtime.provenance["edges"][0]["type"] == "EXECUTED_AS"


def test_history_summarizer_runs_only_at_real_compaction_boundary(tmp_path):
    from modularcua.host.prompt import IPYTHON_TOOL

    class SequenceActor(FakeAuxModel):
        def __init__(self):
            super().__init__()
            self.requests = []
            self.n = 0

        def complete(self, messages, tools):
            self.requests.append(json.loads(json.dumps(messages)))
            self.n += 1
            if self.n == 1:
                return {"content": None, "tool_calls": [{"id": "c1", "type": "function",
                    "function": {"name": "ipython", "arguments": json.dumps({"code": "print('state')"})}}],
                    "_provider": {"usage": {}, "latency_seconds": 0.01, "finish_reason": "tool_calls"}}
            return {"content": "done", "tool_calls": None,
                    "_provider": {"usage": {}, "latency_seconds": 0.01, "finish_reason": "stop"}}

    actor = SequenceActor()
    journal = SessionJournal(tmp_path, "episode")
    runtime = EGCRuntime(tmp_path / "episode", journal, FakeAuxModel(), {})
    result = AgentLoop(actor, FakeKernel(), journal, egc=runtime, compact_after=1).run("Task", "System")
    assert result["status"] == "finished"
    events = [json.loads(x) for x in journal.path.read_text().splitlines()]
    assert sum(e.get("module_name") == "history_summarizer" for e in events
               if e["event_type"] == "egc_module_triggered") == 1
    assert (tmp_path / "episode/history_summaries.jsonl").is_file()
