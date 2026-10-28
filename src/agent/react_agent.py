"""
ReAct Agent 实现
观察-决策-执行循环
"""
from typing import Dict, List, Any

from src.tools.schedule_tools import MaterialScheduleTools
from src.models.llm import LLMModel, Action


class ScheduleAgent:
    """素材排期 Agent"""

    MAX_STEPS = 10  # 最大步数限制

    def __init__(
        self,
        tools: MaterialScheduleTools,
        model: LLMModel
    ):
        self.tools = tools
        self.model = model

    def run(self, user_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行 Agent

        Args:
            user_request: {
                "material_id": str,
                "target_time": str,
                "user_notes": str,
                ...
            }

        Returns:
            {
                "status": "success" | "failed" | "blocked" | "incomplete",
                "result": {...},
                "trace": [...]
            }
        """
        # 初始化状态
        state = self._initialize_state(user_request)
        history = []

        # ReAct 循环
        for step in range(self.MAX_STEPS):
            # 决策：模型选择下一步动作
            action = self.model.decide(
                state=state,
                history=history,
                available_tools=self._get_available_tools()
            )

            # 执行：调用工具
            result = self._execute_action(action, state)

            # 记录
            history.append({
                "step": step + 1,
                "action": {
                    "tool_name": action.tool_name,
                    "params": action.params,
                    "reasoning": action.reasoning
                },
                "result": result
            })

            # 更新状态
            state = self._update_state(state, action, result)

            # 判断是否结束
            if action.tool_name == "FINISH" or self._should_stop(state, result):
                break

        # 检查是否达到最大步数
        if step == self.MAX_STEPS - 1 and not self._is_finished(state):
            output = self._format_output(state)
            output["status"] = "incomplete"
            return {
                "status": "incomplete",
                "reason": f"达到最大步数限制 ({self.MAX_STEPS})",
                "result": output,
                "trace": history
            }

        # 返回最终结果
        return {
            "status": state.get("final_status", "unknown"),
            "result": self._format_output(state),
            "trace": history
        }

    def _initialize_state(self, user_request: Dict) -> Dict[str, Any]:
        """初始化状态"""
        return {
            "material_id": user_request.get("material_id"),
            "target_time": user_request.get("target_time"),
            "user_notes": user_request.get("user_notes", ""),
            "material_info": None,
            "audit_result": None,
            "duplicate_check": None,
            "time_slot_checks": {},
            "suggested_time": None,
            "needs_confirmation": False,
            "confirmation_reasons": [],
            "draft_saved": False,
            "draft_id": None,
            "errors": [],
            "final_status": None,
            "_mock_force_failure": user_request.get("_mock_config", {}).get("force_save_failure", False)
        }

    def _get_available_tools(self) -> List[str]:
        """获取可用工具列表"""
        return [
            "get_material_info",
            "check_audit_rules",
            "query_time_slot",
            "find_alternative_slots",
            "check_duplicate_draft",
            "save_schedule_draft",
            "FINISH"
        ]

    def _execute_action(self, action: Action, state: Dict) -> Dict[str, Any]:
        """
        执行动作

        Args:
            action: 动作对象
            state: 当前状态

        Returns:
            工具返回结果
        """
        tool_name = action.tool_name
        params = action.params

        # 特殊处理 FINISH
        if tool_name == "FINISH":
            return params

        # 调用对应工具
        try:
            if tool_name == "get_material_info":
                if params.get("material_id") != state["material_id"]:
                    return {"success": False, "error": "只能读取本次请求指定的素材"}
                return self.tools.get_material_info(state["material_id"])

            elif tool_name == "check_audit_rules":
                if not state.get("material_info"):
                    return {"success": False, "error": "审核前必须读取素材"}
                return self.tools.check_audit_rules(
                    state["material_info"],
                    state["target_time"]
                )

            elif tool_name == "query_time_slot":
                requested_time = params.get("time_slot")
                target_time = state["target_time"]
                target_clock = target_time[11:16] if len(target_time) >= 16 else None
                suggested_time = state.get("suggested_time")
                suggested_clock = suggested_time[11:16] if suggested_time and len(suggested_time) >= 16 else None
                if requested_time not in {target_time, target_clock, suggested_time, suggested_clock}:
                    return {"available": False, "error": "只能查询本次请求指定的时段"}
                query_time = target_time if requested_time in {target_time, target_clock} else suggested_time
                return self.tools.query_time_slot(query_time)

            elif tool_name == "find_alternative_slots":
                audit_result = state.get("audit_result") or {}
                if not audit_result.get("passed"):
                    return {"success": False, "slots": [], "error": "替代查询前必须通过审核"}
                if params.get("after_time") != state["target_time"]:
                    return {"success": False, "slots": [], "error": "替代查询必须基于原定时段"}
                return self.tools.find_alternative_slots(
                    state["target_time"],
                    params.get("count", 3),
                    audit_result.get("allowed_times")
                )

            elif tool_name == "check_duplicate_draft":
                if params.get("material_id") != state["material_id"]:
                    return {"exists": False, "error": "只能检查本次请求的素材"}
                if params.get("time_slot") != state["target_time"]:
                    return {"exists": False, "error": "只能检查本次请求指定的时段"}
                return self.tools.check_duplicate_draft(
                    state["material_id"],
                    state["target_time"]
                )

            elif tool_name == "save_schedule_draft":
                time_slot = params.get("time_slot")
                if params.get("material_id") != state["material_id"]:
                    return {"success": False, "draft_id": None, "error": "只能保存本次请求的素材"}
                if not (state.get("audit_result") or {}).get("passed"):
                    return {"success": False, "draft_id": None, "error": "素材尚未通过审核"}
                duplicate_check = state.get("duplicate_check") or {}
                if duplicate_check.get("time_slot") != time_slot:
                    return {"success": False, "draft_id": None, "error": "保存前必须检查重复草稿"}
                if duplicate_check.get("exists"):
                    return {"success": False, "draft_id": None, "error": "草稿已存在"}
                slot_check = state.get("time_slot_checks", {}).get(time_slot, {})
                if slot_check.get("available") is not True:
                    return {"success": False, "draft_id": None, "error": "保存前必须确认时段可用"}
                if time_slot != state["target_time"]:
                    return {
                        "success": False,
                        "draft_id": None,
                        "error": "更改后的发布时间尚未获得用户确认"
                    }
                return self.tools.save_schedule_draft(
                    material_id=params["material_id"],
                    time_slot=params["time_slot"],
                    notes=params.get("notes", ""),
                    force_failure=params.get("force_failure", False)
                )

            else:
                return {
                    "success": False,
                    "error": f"未知工具: {tool_name}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"工具执行异常: {str(e)}"
            }

    def _append_error(self, state: Dict, message: str):
        """记录错误信息，避免同一原因重复出现"""
        if message and message not in state["errors"]:
            state["errors"].append(message)

    def _normalize_status(self, status: str) -> str:
        """统一模型可能使用的结束状态写法"""
        mapping = {
            "completed": "success",
            "complete": "success",
            "waiting_for_user_confirmation": "needs_confirmation",
            "pending_user_confirmation": "needs_confirmation",
            "pending_confirmation": "needs_confirmation",
            "awaiting_confirmation": "needs_confirmation",
        }
        return mapping.get(status, status)

    def _update_state(
        self,
        state: Dict,
        action: Action,
        result: Dict
    ) -> Dict:
        """更新状态"""

        # 获取素材信息
        if action.tool_name == "get_material_info":
            if result.get("success"):
                state["material_info"] = result["data"]
            else:
                self._append_error(state, result.get("error", "未知错误"))

        # 审核结果
        elif action.tool_name == "check_audit_rules":
            state["audit_result"] = result
            if not result.get("passed"):
                for reason in result.get("reasons", []):
                    self._append_error(state, reason)

        # 时段查询
        elif action.tool_name == "query_time_slot":
            time_slot = action.params.get("time_slot", state["target_time"])
            state["time_slot_checks"][time_slot] = result
            if result.get("error"):
                state["errors"].append(result["error"])
            elif not result.get("available"):
                state["needs_confirmation"] = True
                subject = "原定时段" if time_slot == state["target_time"] else "候选替代时段"
                state["confirmation_reasons"].append(
                    f"{subject} {time_slot} 已被 {result.get('occupied_by')} 占用"
                )

        elif action.tool_name == "check_duplicate_draft":
            state["duplicate_check"] = {
                "time_slot": action.params.get("time_slot"),
                **result,
            }

        # 替代时段
        elif action.tool_name == "find_alternative_slots":
            if result.get("success") and result.get("slots"):
                state["suggested_time"] = result["nearest_available"]
                state["needs_confirmation"] = True

        # 保存草稿
        elif action.tool_name == "save_schedule_draft":
            if result.get("success"):
                state["draft_saved"] = True
                state["draft_id"] = result["draft_id"]
            else:
                self._append_error(state, result.get("error", "保存失败"))

        # 结束
        elif action.tool_name == "FINISH":
            # 模型可能使用 status 或 final_status 声明结束状态，两者都接受。
            status = result.get("status") or result.get("final_status") or "unknown"
            status = self._normalize_status(status)
            audit_result = state.get("audit_result") or {}
            duplicate_check = state.get("duplicate_check") or {}
            if state["draft_saved"]:
                status = "success"
                state["errors"] = []
            elif duplicate_check.get("exists"):
                status = "duplicate"
                state["existing_draft_id"] = duplicate_check.get("draft_id")
            elif audit_result.get("passed") is False:
                status = "blocked"
            elif state["needs_confirmation"] and state.get("suggested_time"):
                status = "needs_confirmation"
                state["errors"] = []
            elif status in {"success", "completed", "complete"}:
                status = "failed"
                state["errors"].append("未观察到草稿保存成功，不能报告成功")
            elif status == "duplicate":
                status = "failed"
                state["errors"].append("未观察到重复草稿，不能报告重复")
            elif status == "blocked":
                status = "failed"
                state["errors"].append("未观察到审核阻断，不能报告阻断")
            elif status in {"needs_confirmation", "waiting_for_user_confirmation"}:
                status = "failed"
                state["errors"].append("未观察到待确认的替代时段")
            elif status not in {"failed"}:
                status = "failed"
                state["errors"].append("模型返回了无效的结束状态")
            state["final_status"] = status
            if result.get("existing_draft_id"):
                state["existing_draft_id"] = result["existing_draft_id"]
            if result.get("reason"):
                self._append_error(state, result["reason"])
            for detail in result.get("details", []):
                self._append_error(state, detail)

        return state

    def _should_stop(self, state: Dict, result: Dict) -> bool:
        """判断是否应该停止"""
        # 已经设置了最终状态
        if state.get("final_status"):
            return True

        # 工具返回了明确的失败
        if result.get("success") is False and result.get("error"):
            return False  # 让模型决定是否继续

        return False

    def _is_finished(self, state: Dict) -> bool:
        """判断是否已完成"""
        return state.get("final_status") is not None

    def _format_output(self, state: Dict) -> Dict[str, Any]:
        """格式化输出"""
        output = {
            "material_id": state["material_id"],
            "target_time": state["target_time"],
            "status": state.get("final_status", "unknown"),
        }

        # 审核状态
        audit_result = state.get("audit_result") or {}
        if "passed" in audit_result:
            output["audit_status"] = "passed" if audit_result["passed"] else "blocked"
            output["risk_level"] = audit_result.get("risk_level", "unknown")
            output["risk_reasons"] = audit_result.get("reasons", [])
        else:
            output["audit_status"] = "not_checked"
            if audit_result.get("error"):
                output["risk_reasons"] = [audit_result["error"]]

        # 排期结果
        output["suggested_time"] = state.get("suggested_time") or state["target_time"]
        output["needs_confirmation"] = state.get("needs_confirmation", False)
        output["confirmation_reasons"] = state.get("confirmation_reasons", [])

        # 保存状态
        output["draft_saved"] = state.get("draft_saved", False)
        output["draft_id"] = state.get("draft_id")
        if state.get("existing_draft_id"):
            output["existing_draft_id"] = state["existing_draft_id"]

        # 错误信息
        if state.get("errors"):
            output["errors"] = state["errors"]

        return output


def create_agent(
    tools: MaterialScheduleTools,
    model: LLMModel
) -> ScheduleAgent:
    """Agent 工厂函数"""
    return ScheduleAgent(tools=tools, model=model)
