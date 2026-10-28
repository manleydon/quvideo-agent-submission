# 测试与评估

## 验证命令

```bash
python tests/run_all_tests.py
```

测试在临时数据库上执行，逐项断言最终状态和关键动作；六个案例的 `output.json` 与 `trace.json` 是本次 Mock 运行生成的记录。

## 验收结果

| 场景 | 实际结果 | 证据 |
|---|---|---|
| 正常排期 | 保存一份草稿，状态 `success` | [输入](../examples/case1_normal/input.json) · [输出](../examples/case1_normal/output.json) · [Trace](../examples/case1_normal/trace.json) |
| 时段冲突 | 18:00 被占用；20:00 已占用；建议合规的 22:00，状态 `needs_confirmation`，未保存改时草稿 | [输入](../examples/case2_conflict/input.json) · [输出](../examples/case2_conflict/output.json) · [Trace](../examples/case2_conflict/trace.json) |
| 规则风险 | 敏感词命中，状态 `blocked`，未保存 | [输入](../examples/case3_audit_risk/input.json) · [输出](../examples/case3_audit_risk/output.json) · [Trace](../examples/case3_audit_risk/trace.json) |
| 素材缺失 | M999 不存在，状态 `failed` | [输入](../examples/case4_missing_info/input.json) · [输出](../examples/case4_missing_info/output.json) · [Trace](../examples/case4_missing_info/trace.json) |
| 重复提交 | 返回已有 `draft_001`，没有再次保存 | [输入](../examples/case5_duplicate/input.json) · [输出](../examples/case5_duplicate/output.json) · [Trace](../examples/case5_duplicate/trace.json) |
| 保存失败 | 如实返回失败，`draft_saved=false` | [输入](../examples/case6_save_failure/input.json) · [输出](../examples/case6_save_failure/output.json) · [Trace](../examples/case6_save_failure/trace.json) |

每个链接所在目录还包含对应输入和实际输出。冲突用例的 Trace 展示了工具返回占用结果后，Agent 继续查询合规时段并以待确认结束；保存用例的 Trace 包含保存结果后的模型动作。

## DeepSeek 在线运行

2026-10-28 使用 DeepSeek 在线运行。摘要见 [deepseek_online_run.json](../examples/deepseek_online_run.json)，每个场景的输入、真实输出和 Trace 分别保存在对应案例目录。

模型动作由真实 API 返回；素材读取、规则检查、时段查询和草稿保存仍使用本地合成数据与工具，测试数据库为临时文件。没有调用线上发布服务。

| 路径 | 实际结果 | Trace |
|---|---|---|
| 正常排期 | `success`，保存一份草稿 | [DeepSeek Trace](../examples/case1_normal/deepseek_trace.json) |
| 时段冲突 | `needs_confirmation`，建议 22:00，未保存 | [DeepSeek Trace](../examples/case2_conflict/deepseek_trace.json) |

Trace 中的 `reasoning` 是单句决策依据摘要，不记录详细思维过程。Mock 与 DeepSeek 的运行记录分开保存。

## 其他检查

批量测试另验证必需元数据、视频允许时段、视频时长上限、两步上限时返回 `incomplete`，以及所有场景结束后数据库仅有一份草稿。重复执行测试不会修改 `data/mock_database.json`。

## 限制

Mock 使用固定规则，只能验证离线工具流程。DeepSeek 在线运行覆盖正常保存和冲突后等待确认两条不同路径；真实模型在工具失败、重试和异常输出场景上的评估尚未覆盖。
