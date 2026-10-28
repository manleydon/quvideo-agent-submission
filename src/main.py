"""
主程序入口
"""
import sys
import json
import argparse
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools.schedule_tools import create_tools
from src.models.llm import create_model
from src.agent.react_agent import create_agent


def main():
    parser = argparse.ArgumentParser(description="素材审核与发布排期 Agent")
    parser.add_argument("--input", type=str, required=True, help="输入 JSON 文件路径")
    parser.add_argument("--output", type=str, help="输出 JSON 文件路径（可选）")
    parser.add_argument("--trace", type=str, help="Trace 输出路径（可选）")
    parser.add_argument("--mode", type=str, default="mock", choices=["openai", "mock"],
                        help="模型模式：openai 或 mock（默认）")
    parser.add_argument("--data", type=str, default="data/mock_database.json",
                        help="数据库文件路径")

    args = parser.parse_args()

    # 读取输入
    with open(args.input, 'r', encoding='utf-8') as f:
        user_request = json.load(f)

    print(f"\n{'='*60}")
    print(f"素材审核与发布排期 Agent")
    print(f"{'='*60}")
    print(f"输入: {args.input}")
    print(f"模式: {args.mode}")
    print(f"素材ID: {user_request.get('material_id')}")
    print(f"目标时间: {user_request.get('target_time')}")
    print(f"{'='*60}\n")

    # 初始化工具和模型
    tools = create_tools(data_file=args.data)
    model = create_model(mode=args.mode)

    # 创建 Agent
    agent = create_agent(tools=tools, model=model)

    # 运行
    print("开始执行...\n")
    result = agent.run(user_request)

    # 打印结果
    print(f"\n{'='*60}")
    print(f"执行结果")
    print(f"{'='*60}")
    print(f"状态: {result['status']}")
    print(f"\n最终输出:")
    print(json.dumps(result['result'], ensure_ascii=False, indent=2))

    print(f"\n{'='*60}")
    print(f"执行轨迹 ({len(result['trace'])} 步)")
    print(f"{'='*60}")
    for step_info in result['trace']:
        step = step_info['step']
        action = step_info['action']
        result_data = step_info['result']

        print(f"\n步骤 {step}: {action['tool_name']}")
        print(f"  推理: {action['reasoning']}")
        print(f"  参数: {json.dumps(action['params'], ensure_ascii=False)}")
        print(f"  结果: {json.dumps(result_data, ensure_ascii=False)}")

    # 保存输出
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result['result'], f, ensure_ascii=False, indent=2)
        print(f"\n输出已保存到: {args.output}")

    # 保存 Trace
    if args.trace:
        trace_path = Path(args.trace)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with open(trace_path, 'w', encoding='utf-8') as f:
            json.dump(result['trace'], f, ensure_ascii=False, indent=2)
        print(f"Trace 已保存到: {args.trace}")

    print(f"\n{'='*60}\n")

    # 返回状态码
    return 1 if result['status'] == 'incomplete' else 0


if __name__ == "__main__":
    sys.exit(main())
