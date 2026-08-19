import json
from pathlib import Path

from serviceflow.evaluation.runner import EvaluationRun


def write_evaluation_outputs(
    run: EvaluationRun,
    output_dir: Path,
    *,
    stem: str = "serviceflow-v1",
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}-results.json"
    markdown_path = output_dir / f"{stem}-report.md"
    json_path.write_text(
        json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(run), encoding="utf-8")
    return json_path, markdown_path


def _markdown_report(run: EvaluationRun) -> str:
    summary = run.summary
    models = ", ".join(run.models)
    if not models:
        models = "未知"
    prompt_versions = ", ".join(run.prompt_versions)
    if not prompt_versions:
        prompt_versions = "未知"
    lines = [
        "# ServiceFlow V1 评测报告",
        "",
        f"- 运行时间：`{run.run_at}`",
        f"- 提交版本：`{run.commit}`",
        f"- 使用模型：`{models}`",
        f"- Prompt 版本：`{prompt_versions}`",
        f"- 已完成案例：{summary.completed_cases}/{summary.total_cases}",
        "",
        "## 评测指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 任务结果准确率 | {_percent(summary.outcome_accuracy)} |",
        f"| 最终业务状态准确率 | {_percent(summary.final_state_accuracy)} |",
        f"| 政策匹配准确率 | {_percent(summary.policy_accuracy)} |",
        f"| 工具调用准确率 | {_percent(summary.tool_accuracy)} |",
        f"| 澄清完成率 | {_percent(summary.clarification_completion_rate)} |",
        f"| 总耗时 | {summary.total_latency_ms:.2f} ms |",
        f"| 平均耗时 | {summary.average_latency_ms:.2f} ms |",
        f"| 输入 Token | {summary.total_input_tokens} |",
        f"| 输出 Token | {summary.total_output_tokens} |",
        "",
    ]
    if run.group_summaries:
        lines.extend(_group_metrics(run))
    lines.append("## 失败案例")
    lines.append("")
    if not summary.failed_case_ids:
        lines.append("无。")
    else:
        for case in run.cases:
            if case.case_id not in summary.failed_case_ids:
                continue
            reasons = []
            if not case.outcome_correct:
                reasons.append("任务结果")
            if not case.final_state_correct:
                reasons.append("最终状态")
            if not case.policy_correct:
                reasons.append("政策")
            if not case.tools_correct:
                reasons.append("工具")
            if case.clarification_correct is False:
                reasons.append("澄清")
            if case.error:
                reasons.append(case.error)
            expected = {
                "intent": case.expected_intent,
                "decision": case.expected_decision,
                "policy": case.expected_policy_id,
                "tools": case.expected_tools,
                "final_state": case.expected_final_state,
            }
            actual = {
                "intent": case.actual_intent,
                "decision": case.actual_decision,
                "policy": case.actual_policy_id,
                "tools": case.actual_tools,
                "final_state": case.actual_final_state,
            }
            lines.extend(
                [
                    f"### `{case.case_id}`",
                    "",
                    f"- 失败检查：{', '.join(reasons)}",
                    f"- 期望结果：`{json.dumps(expected, ensure_ascii=False)}`",
                    f"- 实际结果：`{json.dumps(actual, ensure_ascii=False)}`",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## 已知限制",
            "",
            "- 订单、政策、用户和审批决定全部是模拟数据。",
            "- 指标只评估确定性的业务结果，不评估对话表达风格。",
            "- 失败案例会原样保留，不会为了提高成绩修改期望结果。",
            "",
        ]
    )
    return "\n".join(lines)


def _group_metrics(run: EvaluationRun) -> list[str]:
    labels = {"core_40": "核心40案", "complex_60": "复杂中文60案"}
    lines = [
        "## 按难度分区统计",
        "",
        "| 分区 | 案例数 | 任务结果 | 最终状态 | 政策 | 工具 | 澄清 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, summary in run.group_summaries.items():
        lines.append(
            "| "
            f"{labels.get(key, key)} | {summary.total_cases} | "
            f"{_percent(summary.outcome_accuracy)} | "
            f"{_percent(summary.final_state_accuracy)} | "
            f"{_percent(summary.policy_accuracy)} | "
            f"{_percent(summary.tool_accuracy)} | "
            f"{_percent(summary.clarification_completion_rate)} |"
        )
    lines.append("")
    return lines


def _percent(value: float) -> str:
    return f"{value:.2%}"
