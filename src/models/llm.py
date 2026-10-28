"""
LLM 模型接入层
支持 OpenAI API 和 Mock 模式
"""
import os
import json
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class Action:
    """Agent 动作"""
    tool_name: str
    params: Dict[str, Any]
    reasoning: str


class LLMModel:
    """LLM 模型接口"""

    def __init__(
        self,
        mode: str = "openai",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        """
        初始化模型

        Args:
            mode: "openai" 或 "mock"
            api_key: OpenAI-compatible API key
            base_url: Optional OpenAI-compatible endpoint
            model_name: Optional model override
        """
        self.mode = mode

        if mode == "openai":
            try:
                from openai import OpenAI
                key = api_key or os.getenv("OPENAI_API_KEY")
                if not key:
                    raise ValueError("OpenAI-compatible mode requires OPENAI_API_KEY")
                options = {"api_key": key}
                endpoint = base_url or os.getenv("OPENAI_BASE_URL")
                if endpoint:
                    options["base_url"] = endpoint
                self.client = OpenAI(**options)
                self.model_name = model_name or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            except ImportError:
                raise ImportError("请安装 openai: pip install openai")
        elif mode == "mock":
            self.client = None
            self.model_name = "mock"
        else:
            raise ValueError(f"不支持的模式: {mode}")

    def decide(
        self,
        state: Dict[str, Any],
        history: List[Dict],
        available_tools: List[str]
    ) -> Action:
        """
        决策下一步动作

        Args:
            state: 当前状态
            history: 历史动作
            available_tools: 可用工具列表

        Returns:
            Action 对象
        """
        if self.mode == "openai":
            return self._decide_with_openai(state, history, available_tools)
        else:
            return self._decide_with_mock(state, history, available_tools)

    def _decide_with_openai(
        self,
        state: Dict,
        history: List[Dict],
        available_tools: List[str]
    ) -> Action:
        """使用 OpenAI API 决策"""

        # 构建 system prompt
        system_prompt = self._build_system_prompt(available_tools)

        # 构建 user message
        user_message = self._build_user_message(state, history)

        # 调用 API
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        # 解析响应
        content = response.choices[0].message.content
        result = json.loads(content)
        raw_basis = result.get("reasoning", "根据当前状态和工具结果选择动作")
        basis_parts = [part.strip() for part in re.split(r"[。！？.!?\r\n]+", raw_basis) if part.strip()]
        decision_basis = basis_parts[0][:120] if basis_parts else "根据当前状态和工具结果选择动作"

        return Action(
            tool_name=result["tool_name"],
            params=result["params"],
            reasoning=decision_basis
        )

    def _decide_with_mock(
        self,
        state: Dict,
        history: List[Dict],
        available_tools: List[str]
    ) -> Action:
        """使用 Mock 规则决策（用于离线测试）"""

        step_count = len(history)

        # 规则1：第一步总是获取素材信息
        if step_count == 0:
            return Action(
                tool_name="get_material_info",
                params={"material_id": state["material_id"]},
                reasoning="首先获取素材信息以了解内容详情"
            )

        last_action = history[-1]["action"]
        last_result = history[-1]["result"]

        # 规则2：获取素材后检查审核规则
        if last_action["tool_name"] == "get_material_info":
            if not last_result.get("success"):
                return Action(
                    tool_name="FINISH",
                    params={"status": "failed", "reason": "素材不存在"},
                    reasoning="素材信息获取失败，无法继续"
                )

            return Action(
                tool_name="check_audit_rules",
                    params={
                        "material_info": last_result["data"],
                        "target_time": state["target_time"]
                    },
                reasoning="检查素材是否符合审核规则"
            )

        # 规则3：审核后检查重复草稿
        if last_action["tool_name"] == "check_audit_rules":
            if last_result.get("error"):
                return Action(
                    tool_name="FINISH",
                    params={"status": "failed", "reason": last_result["error"]},
                    reasoning="审核工具执行失败，停止排期"
                )
            if not last_result.get("passed"):
                return Action(
                    tool_name="FINISH",
                    params={
                        "status": "blocked",
                        "reason": "审核未通过",
                        "details": last_result["reasons"]
                    },
                    reasoning="素材存在审核风险，阻断流程"
                )

            return Action(
                tool_name="check_duplicate_draft",
                params={
                    "material_id": state["material_id"],
                    "time_slot": state["target_time"]
                },
                reasoning="检查是否已存在相同的排期草稿"
            )

        # 规则4：检查重复后查询时段
        if last_action["tool_name"] == "check_duplicate_draft":
            if last_result.get("error"):
                return Action(
                    tool_name="FINISH",
                    params={"status": "failed", "reason": last_result["error"]},
                    reasoning="重复检查失败，停止排期"
                )
            if last_result.get("exists"):
                return Action(
                    tool_name="FINISH",
                    params={
                        "status": "duplicate",
                        "existing_draft_id": last_result["draft_id"]
                    },
                    reasoning="草稿已存在，避免重复保存"
                )

            return Action(
                tool_name="query_time_slot",
                params={"time_slot": state["target_time"]},
                reasoning="检查目标时段是否可用"
            )

        # 规则5：时段查询后决定是否查找替代
        if last_action["tool_name"] == "query_time_slot":
            if last_result.get("error"):
                return Action(
                    tool_name="FINISH",
                    params={"status": "failed", "reason": last_result["error"]},
                    reasoning="目标时段查询失败，停止排期"
                )
            if last_result.get("available"):
                # 时段可用，直接保存
                force_failure = state.get("_mock_force_failure", False)
                return Action(
                    tool_name="save_schedule_draft",
                    params={
                        "material_id": state["material_id"],
                        "time_slot": state["target_time"],
                        "notes": state.get("user_notes", ""),
                        "force_failure": force_failure
                    },
                    reasoning="目标时段可用，保存排期草稿"
                )
            else:
                # 时段冲突，查找替代
                return Action(
                    tool_name="find_alternative_slots",
                    params={
                        "after_time": state["target_time"],
                        "count": 3,
                        "allowed_times": state.get("audit_result", {}).get("allowed_times")
                    },
                    reasoning="目标时段已占用，查找替代方案"
                )

        # 规则6：找到替代时段后保存
        if last_action["tool_name"] == "find_alternative_slots":
            if not last_result.get("success") or not last_result.get("slots"):
                return Action(
                    tool_name="FINISH",
                    params={
                        "status": "failed",
                        "reason": last_result.get("error", "无可用时段")
                    },
                    reasoning="未找到替代时段"
                )

            # An alternative changes the requested time, so return it for confirmation.
            return Action(
                tool_name="FINISH",
                params={
                    "status": "needs_confirmation",
                    "suggested_time": last_result["nearest_available"]
                },
                reasoning="替代时段会改变用户要求，先请求确认，不保存草稿"
            )

        # 规则7：保存后结束
        if last_action["tool_name"] == "save_schedule_draft":
            if last_result.get("success"):
                return Action(
                    tool_name="FINISH",
                    params={
                        "status": "success",
                        "draft_id": last_result["draft_id"]
                    },
                    reasoning="草稿保存成功"
                )
            else:
                return Action(
                    tool_name="FINISH",
                    params={
                        "status": "failed",
                        "reason": last_result.get("error", "保存失败")
                    },
                    reasoning="草稿保存失败"
                )

        # 默认：结束
        return Action(
            tool_name="FINISH",
            params={"status": "unknown"},
            reasoning="未知状态，停止流程"
        )

    def _build_system_prompt(self, available_tools: List[str]) -> str:
        """构建系统提示词"""
        return """你是一个素材审核与发布排期助手。你的任务是帮助用户安全地排期发布素材。

可用工具：
1. get_material_info(material_id): 获取素材信息
2. check_audit_rules(material_info, target_time): 检查完整性、审核规则和时段限制
3. query_time_slot(time_slot): 查询时段可用性
4. find_alternative_slots(after_time, count, allowed_times): 查找合规替代时段
5. check_duplicate_draft(material_id, time_slot): 检查重复草稿
6. save_schedule_draft(material_id, time_slot, notes): 保存排期草稿
7. FINISH: 结束流程

决策原则：
- 必须先获取素材信息，再检查审核规则
- 审核不通过时立即阻断，不继续排期
- 时段冲突时必须查找替代方案或请求用户确认
- 保存前必须查询目标时段是否可用
- 未经用户确认，不得保存更改后的发布时间
- 只保存草稿，不执行真实发布
- 素材信息不全或规则不通过时阻断排期
- 保存前检查是否重复
- 保存失败时如实报告，不虚报成功

请根据当前状态和历史记录，选择下一个动作。
reasoning 仅写一句简短的决策依据（不超过 40 字），不要输出详细思维过程。
返回 JSON 格式：
{
  "tool_name": "工具名称",
  "params": {参数字典},
  "reasoning": "选择此动作的理由"
}
"""

    def _build_user_message(self, state: Dict, history: List[Dict]) -> str:
        """构建用户消息"""
        msg = f"当前状态：\n{json.dumps(state, ensure_ascii=False, indent=2)}\n\n"

        if history:
            msg += "历史动作：\n"
            for i, step in enumerate(history):
                msg += f"步骤 {i+1}: {step['action']['tool_name']}\n"
                msg += f"  参数: {json.dumps(step['action']['params'], ensure_ascii=False)}\n"
                msg += f"  结果: {json.dumps(step['result'], ensure_ascii=False)}\n"
                msg += f"  推理: {step['action']['reasoning']}\n\n"

        msg += "请决定下一步动作。"
        return msg


def create_model(
    mode: str = "mock",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
) -> LLMModel:
    """模型工厂函数"""
    return LLMModel(mode=mode, api_key=api_key, base_url=base_url, model_name=model_name)
