# AI 使用记录

项目初版使用 Claude 辅助生成目录、文档框架、CLI 文件读写、工具与 Agent 骨架。开发者记录的个人工作包括需求拆解、状态与确认边界设计、六个验收输入、代码修改和结果核验。

本次提交整理使用 OpenAI Codex 对照试卷核查交付物，删除重复的提交清单和文件清单，精简文档并修正文档与 Trace 顺序不一致的问题；同时收紧 `.gitignore` 对环境变量文件的忽略规则。本轮未修改 Agent 核心代码或测试逻辑。

重点人工修改包括：补齐工具失败和终态校验；限制替代时段必须符合审核规则，未经用户确认不得保存改时草稿；为测试使用隔离数据库，并断言结果、动作顺序、重复保存和步数上限。在线模型调用由开发者执行，记录保存在 `examples/case1_normal/deepseek_trace.json` 和 `examples/case2_conflict/deepseek_trace.json`。

验证命令：

```bash
python tests/run_all_tests.py
```
