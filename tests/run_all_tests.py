"""Run acceptance cases against an isolated mock database."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent.react_agent import create_agent
from src.models.llm import Action, create_model
from src.tools.schedule_tools import create_tools

TEST_CASES = [
    ("正常排期", "examples/case1_normal/input.json", "success"),
    ("时段冲突", "examples/case2_conflict/input.json", "needs_confirmation"),
    ("审核风险", "examples/case3_audit_risk/input.json", "blocked"),
    ("素材缺失", "examples/case4_missing_info/input.json", "failed"),
    ("保存失败", "examples/case6_save_failure/input.json", "failed"),
    ("重复提交", "examples/case5_duplicate/input.json", "duplicate"),
]


def validate_case(case_name, output, trace, expected_status):
    assert output["status"] == expected_status, output
    assert trace and len(trace) <= 10, trace

    actions = [step["action"]["tool_name"] for step in trace]
    if case_name == "时段冲突":
        assert "find_alternative_slots" in actions, actions
        assert "save_schedule_draft" not in actions, actions
        assert output["suggested_time"] == "2026-10-28T22:00:00", output
        assert output["needs_confirmation"] is True, output
        assert output["draft_saved"] is False, output
    elif case_name == "重复提交":
        assert "check_duplicate_draft" in actions, actions
        assert "save_schedule_draft" not in actions, actions
        assert output["existing_draft_id"] == "draft_001", output
    elif case_name == "保存失败":
        assert actions[-2:] == ["save_schedule_draft", "FINISH"], actions
        assert output["draft_saved"] is False, output
        assert any("不可用" in error for error in output.get("errors", [])), output
    elif case_name == "审核风险":
        assert actions[-1] == "FINISH", actions
        assert output["audit_status"] == "blocked", output
        assert output["draft_saved"] is False, output
    elif case_name == "素材缺失":
        assert actions == ["get_material_info", "FINISH"], actions
        assert output["audit_status"] == "not_checked", output
    elif case_name == "正常排期":
        assert output["draft_saved"] is True, output
        assert output["draft_id"] == "draft_001", output


def run_test_case(case_name, input_file, expected_status, data_file):
    case_dir = Path(input_file).parent
    output_file = case_dir / "output.json"
    trace_file = case_dir / "trace.json"
    cmd = [
        sys.executable, "src/main.py",
        "--input", input_file,
        "--output", str(output_file),
        "--trace", str(trace_file),
        "--data", str(data_file),
        "--mode", "mock",
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, env=env
    )
    if result.returncode != 0:
        raise AssertionError(f"CLI exit={result.returncode}\n{result.stdout}\n{result.stderr}")

    output = json.loads(output_file.read_text(encoding="utf-8"))
    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    validate_case(case_name, output, trace, expected_status)
    print(f"[PASS] {case_name}: status={output['status']}, trace={len(trace)} steps")


def run_rule_checks(data_file):
    tools = create_tools(str(data_file))
    material = tools.get_material_info("M02")["data"]
    assert tools.check_audit_rules(material, "2026-10-28T18:00:00")["passed"]
    disallowed = tools.check_audit_rules(material, "2026-10-28T19:00:00")
    assert not disallowed["passed"] and any("不允许" in r for r in disallowed["reasons"])
    incomplete = tools.check_audit_rules({"id": "M05"})
    assert not incomplete["passed"] and any("缺失" in r for r in incomplete["reasons"])
    long_video = dict(material, duration_minutes=11)
    too_long = tools.check_audit_rules(long_video, "2026-10-28T18:00:00")
    assert not too_long["passed"] and any("超过限制" in r for r in too_long["reasons"])
    no_allowed_slots = tools.find_alternative_slots(
        "2026-10-28T18:00:00", allowed_times=[]
    )
    assert not no_allowed_slots["success"]
    history = [{
        "action": {"tool_name": "get_material_info", "params": {}, "reasoning": "read"},
        "result": {"success": True},
    }]
    prompt = create_model(mode="mock")._build_user_message({}, history)
    assert "get_material_info" in prompt
    agent = create_agent(tools, create_model(mode="mock"))
    target_state = agent._initialize_state({
        "material_id": "M02", "target_time": "2026-10-28T18:00:00"
    })
    target_state["material_info"] = material
    target_state["audit_result"] = tools.check_audit_rules(material, target_state["target_time"])
    short_time = agent._execute_action(
        Action("query_time_slot", {"time_slot": "18:00"}, "query requested time"),
        target_state
    )
    assert short_time["occupied_by"] == "M99", short_time
    target_state["suggested_time"] = "2026-10-28T22:00:00"
    suggested_time = agent._execute_action(
        Action("query_time_slot", {"time_slot": "2026-10-28T22:00:00"}, "check alternative"),
        target_state
    )
    assert suggested_time["available"] is True, suggested_time
    unrelated_time = agent._execute_action(
        Action("query_time_slot", {"time_slot": "2026-10-28T21:00:00"}, "query unrelated time"),
        target_state
    )
    assert unrelated_time.get("error"), unrelated_time
    normal_state = agent._initialize_state({
        "material_id": "M01", "target_time": "2026-10-28T19:00:00"
    })
    normal_state["draft_saved"] = True
    normal_state["draft_id"] = "draft_test"
    agent._update_state(
        normal_state,
        Action("FINISH", {"final_status": "completed"}, "model completion"),
        {"final_status": "completed"}
    )
    assert normal_state["final_status"] == "success", normal_state
    conflict_state = agent._initialize_state({
        "material_id": "M02", "target_time": "2026-10-28T18:00:00"
    })
    conflict_state["needs_confirmation"] = True
    conflict_state["suggested_time"] = "2026-10-28T22:00:00"
    agent._update_state(
        conflict_state,
        Action("FINISH", {"status": "waiting_for_user_confirmation"}, "wait"),
        {"status": "waiting_for_user_confirmation"}
    )
    assert conflict_state["final_status"] == "needs_confirmation", conflict_state
    guarded_state = {
        "material_id": "M02",
        "target_time": "2026-10-28T18:00:00",
        "audit_result": {"passed": True},
        "duplicate_check": {"time_slot": "2026-10-28T22:00:00", "exists": False},
        "time_slot_checks": {"2026-10-28T22:00:00": {"available": True}},
    }
    rejected = agent._execute_action(
        Action("save_schedule_draft", {
            "material_id": "M02", "time_slot": "2026-10-28T22:00:00"
        }, "try an unconfirmed alternative"),
        guarded_state
    )
    assert rejected["success"] is False and "尚未获得用户确认" in rejected["error"]
    skipped_checks = agent._execute_action(
        Action("save_schedule_draft", {
            "material_id": "M02", "time_slot": "2026-10-28T18:00:00"
        }, "skip required checks"),
        {"material_id": "M02", "target_time": "2026-10-28T18:00:00"}
    )
    assert skipped_checks["success"] is False and "尚未通过审核" in skipped_checks["error"]

    class PrematureSuccessModel:
        def decide(self, state, history, available_tools):
            return Action("FINISH", {"status": "success"}, "claim success without saving")

    result = create_agent(tools, PrematureSuccessModel()).run({
        "material_id": "M01", "target_time": "2026-10-28T19:00:00"
    })
    assert result["status"] == "failed" and not result["result"]["draft_saved"], result
    class SkipReadModel:
        def decide(self, state, history, available_tools):
            if not history:
                return Action("check_audit_rules", {
                    "material_info": {"id": "M01", "title": "untrusted"}
                }, "try auditing unverified data")
            return Action("FINISH", {"status": "failed"}, "stop after rejected action")

    result = create_agent(tools, SkipReadModel()).run({
        "material_id": "M01", "target_time": "2026-10-28T19:00:00"
    })
    assert result["status"] == "failed", result
    assert result["result"]["audit_status"] == "not_checked", result
    print("[PASS] audit rules: metadata, allowed time, and duration")


def run_step_limit_check(data_file):
    class RepeatingModel:
        def decide(self, state, history, available_tools):
            return Action("unknown_tool", {}, "exercise the step limit")

    agent = create_agent(create_tools(str(data_file)), RepeatingModel())
    agent.MAX_STEPS = 2
    result = agent.run({"material_id": "M01", "target_time": "2026-10-28T19:00:00"})
    assert result["status"] == "incomplete", result
    assert result["result"]["status"] == "incomplete", result
    assert len(result["trace"]) == 2, result
    print("[PASS] maximum-step limit: explicit incomplete status")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    results = []
    with tempfile.TemporaryDirectory(prefix="schedule-agent-") as temp_dir:
        data_file = Path(temp_dir) / "mock_database.json"
        shutil.copy2(ROOT / "data/mock_database.json", data_file)
        try:
            run_rule_checks(data_file)
            run_step_limit_check(data_file)
            for case_name, input_file, expected_status in TEST_CASES:
                run_test_case(case_name, input_file, expected_status, data_file)
                results.append(case_name)

            saved = json.loads(data_file.read_text(encoding="utf-8"))["drafts"]
            assert len(saved) == 1, f"expected one saved draft, got {len(saved)}"
            print("[PASS] duplicate submission: one draft remains")
        except Exception as exc:
            print(f"[FAIL] {exc}")
            return 1

    print(f"[PASS] {len(results) + 3} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
