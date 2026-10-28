"""
业务工具实现
提供素材审核与排期相关的工具函数
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any


class MaterialScheduleTools:
    """素材排期工具集"""

    def __init__(self, data_file: str = "data/mock_database.json"):
        self.data_file = Path(data_file)
        self.db = self._load_database()

    def _load_database(self) -> Dict:
        """加载模拟数据库"""
        if not self.data_file.exists():
            return {
                "materials": {},
                "audit_rules": {},
                "existing_schedules": {},
                "drafts": {}
            }
        with open(self.data_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_database(self):
        """保存数据库"""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.db, f, ensure_ascii=False, indent=2)

    def get_material_info(self, material_id: str) -> Dict[str, Any]:
        """
        获取素材信息

        Args:
            material_id: 素材ID

        Returns:
            {
                "success": bool,
                "data": {...} or None,
                "error": str or None
            }
        """
        if material_id not in self.db["materials"]:
            return {
                "success": False,
                "data": None,
                "error": f"素材 {material_id} 不存在"
            }

        return {
            "success": True,
            "data": self.db["materials"][material_id],
            "error": None
        }

    def check_audit_rules(
        self,
        material_info: Dict,
        target_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        检查审核规则

        Args:
            material_info: 素材信息

        Returns:
            {
                "passed": bool,
                "risk_level": "low" | "medium" | "high",
                "reasons": List[str]
            }
        """
        reasons = []
        risk_level = "low"
        required_fields = ("id", "title", "type", "content_preview")
        missing_fields = [field for field in required_fields if not material_info.get(field)]
        if missing_fields:
            reasons.append(f"素材信息缺失: {', '.join(missing_fields)}")
            risk_level = "medium"

        # 检查敏感词
        content = material_info.get("content_preview", "")
        sensitive_keywords = self.db["audit_rules"].get("sensitive_keywords", [])

        found_keywords = [kw for kw in sensitive_keywords if kw in content]
        if found_keywords:
            reasons.append(f"包含敏感词: {', '.join(found_keywords)}")
            risk_level = "high"

        # 检查类型限制
        material_type = material_info.get("type", "")
        type_restrictions = self.db["audit_rules"].get("type_restrictions", {})

        if material_type in type_restrictions:
            restrictions = type_restrictions[material_type]
            allowed_times = restrictions.get("allowed_times")
            if allowed_times and target_time:
                try:
                    target_clock = datetime.fromisoformat(
                        target_time.replace('Z', '+00:00')
                    ).strftime("%H:%M")
                    if target_clock not in allowed_times:
                        reasons.append(f"{material_type} 素材不允许在 {target_clock} 发布")
                        risk_level = "high"
                except ValueError:
                    reasons.append("发布时间格式错误")
                    risk_level = "high"
            if "max_duration_minutes" in restrictions:
                duration = material_info.get("duration_minutes")
                if duration is None:
                    reasons.append("素材信息缺失: duration_minutes")
                    if risk_level == "low":
                        risk_level = "medium"
                elif duration > restrictions["max_duration_minutes"]:
                    reasons.append(
                        f"素材时长 {duration} 分钟超过限制 "
                        f"{restrictions['max_duration_minutes']} 分钟"
                    )
                    risk_level = "high"

        passed = not reasons

        return {
            "passed": passed,
            "risk_level": risk_level,
            "reasons": reasons,
            "allowed_times": type_restrictions.get(material_type, {}).get("allowed_times")
        }

    def query_time_slot(self, time_slot: str) -> Dict[str, Any]:
        """
        查询时段是否可用

        Args:
            time_slot: ISO格式时间或 HH:MM 格式

        Returns:
            {
                "available": bool,
                "occupied_by": str or None,
                "time": str
            }
        """
        # 解析时间
        try:
            dt = datetime.fromisoformat(time_slot.replace('Z', '+00:00'))
            date_key = dt.strftime("%Y-%m-%d")
            time_key = dt.strftime("%H:%M")
        except ValueError:
            return {
                "available": False,
                "occupied_by": None,
                "error": "时间格式错误"
            }

        # 检查是否已占用
        schedules = self.db["existing_schedules"].get(date_key, {})
        if time_key in schedules:
            return {
                "available": False,
                "occupied_by": schedules[time_key]["material_id"],
                "time": time_slot
            }

        return {
            "available": True,
            "occupied_by": None,
            "time": time_slot
        }

    def find_alternative_slots(
        self,
        after_time: str,
        count: int = 3,
        allowed_times: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        查找替代时段

        Args:
            after_time: 起始时间
            count: 返回数量

        Returns:
            {
                "success": bool,
                "slots": List[str],
                "nearest_available": str or None
            }
        """
        try:
            dt = datetime.fromisoformat(after_time.replace('Z', '+00:00'))
            date_key = dt.strftime("%Y-%m-%d")
        except ValueError:
            return {
                "success": False,
                "slots": [],
                "error": "时间格式错误"
            }

        common_slots = (
            allowed_times
            if allowed_times is not None
            else ["19:00", "20:00", "21:00", "22:00", "23:00"]
        )
        occupied = set(self.db["existing_schedules"].get(date_key, {}).keys())
        after_clock = dt.strftime("%H:%M")
        available = sorted({
            slot for slot in common_slots
            if slot > after_clock and slot not in occupied
        })[:count]

        if not available:
            return {
                "success": False,
                "slots": [],
                "error": "无可用时段"
            }

        # 转换为完整ISO时间
        full_slots = [f"{date_key}T{slot}:00" for slot in available]

        return {
            "success": True,
            "slots": full_slots,
            "nearest_available": full_slots[0] if full_slots else None
        }

    def check_duplicate_draft(self, material_id: str, time_slot: str) -> Dict[str, Any]:
        """
        检查是否已存在草稿

        Args:
            material_id: 素材ID
            time_slot: 时间段

        Returns:
            {
                "exists": bool,
                "draft_id": str or None
            }
        """
        draft_key = f"{material_id}_{time_slot}"

        if draft_key in self.db["drafts"]:
            return {
                "exists": True,
                "draft_id": self.db["drafts"][draft_key]["draft_id"]
            }

        return {
            "exists": False,
            "draft_id": None
        }

    def save_schedule_draft(
        self,
        material_id: str,
        time_slot: str,
        notes: str = "",
        force_failure: bool = False
    ) -> Dict[str, Any]:
        """
        保存排期草稿

        Args:
            material_id: 素材ID
            time_slot: 时间段
            notes: 备注信息
            force_failure: 强制失败（测试用）

        Returns:
            {
                "success": bool,
                "draft_id": str or None,
                "error": str or None
            }
        """
        if force_failure:
            return {
                "success": False,
                "draft_id": None,
                "error": "保存服务暂时不可用"
            }

        # 生成草稿ID
        draft_id = f"draft_{len(self.db['drafts']) + 1:03d}"
        draft_key = f"{material_id}_{time_slot}"

        # 保存草稿
        self.db["drafts"][draft_key] = {
            "draft_id": draft_id,
            "material_id": material_id,
            "time_slot": time_slot,
            "notes": notes,
            "created_at": datetime.now().isoformat()
        }

        self._save_database()

        return {
            "success": True,
            "draft_id": draft_id,
            "error": None
        }


def create_tools(data_file: str = "data/mock_database.json") -> MaterialScheduleTools:
    """工具工厂函数"""
    return MaterialScheduleTools(data_file)
