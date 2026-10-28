# 素材审核与发布排期 Agent

校招考核项目1。CLI 工具仅保存排期草稿，不执行真实发布。

## 环境与运行

- Python 3.10+
- 原生 Python Agent；排期工具为本地函数
- Mock 模式离线运行；OpenAI 兼容模式在线测试使用 DeepSeek `deepseek-flash`
- OpenAI 兼容模式需设置 `OPENAI_API_KEY`，可用 `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 指定兼容服务

```bash
python -m pip install -r requirements.txt
python src/main.py --input examples/case2_conflict/input.json --mode mock
```

在线运行需在本地设置 DeepSeek API Key；

```bash
# PowerShell
$env:OPENAI_API_KEY = "<your DeepSeek key>"
$env:OPENAI_BASE_URL = "https://api.deepseek.com"
$env:OPENAI_MODEL = "deepseek-flash"
python src/main.py --input examples/case1_normal/input.json --mode openai --output examples/case1_normal/deepseek_output.json --trace examples/case1_normal/deepseek_trace.json
python src/main.py --input examples/case2_conflict/input.json --mode openai --output examples/case2_conflict/deepseek_output.json --trace examples/case2_conflict/deepseek_trace.json
```

单次 CLI 运行会将草稿写入 `data/mock_database.json`。验收测试使用隔离数据库，并重新生成各案例的 `output.json` 和 `trace.json`：

```bash
python tests/run_all_tests.py
```

## 行为边界

- 先读素材并检查元数据、审核规则和发布时间限制；之后由模型决定查重与查询时段的顺序，保存前两项检查都必须通过。
- 冲突时只建议满足素材规则的替代时段，并返回 `needs_confirmation`；用户确认后用确认时段重新提交。
- 可用原时段保存草稿；审核、工具或保存失败均如实返回。
- 达到步数上限返回 `incomplete`。
- Mock Trace 仅验证工具流程；DeepSeek 在线 Trace 单独保存，运行摘要见 [deepseek_online_run.json](examples/deepseek_online_run.json)。

## 项目结构

```text
src/       Agent、模型接入和业务工具
tests/     六个验收场景、规则检查与步数上限检查
examples/  每个场景的 input.json、实际 output.json 和 trace.json
data/      合成素材、审核规则和已有排期
docs/      需求、方案、评估、AI 使用记录和复盘
```

## 评审入口

- 设计与决策边界：[docs/02-solution.md](docs/02-solution.md)
- 需求与验收点：[docs/01-requirements.md](docs/01-requirements.md)
- 测试结果与限制：[docs/03-evaluation.md](docs/03-evaluation.md)
- AI 使用记录：[docs/04-ai-usage.md](docs/04-ai-usage.md)
- 开发复盘：[docs/05-retrospective.md](docs/05-retrospective.md)
