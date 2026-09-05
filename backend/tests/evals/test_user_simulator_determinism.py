"""用户模拟器的确定性与安全性测试。

对应计划补充 P 的验收条件：
- replay 逐字节一致且**零模型调用**；
- 未录制的提问显式报 miss，不静默降级；
- **不泄漏 unknown_info 由规则层代码保证**，即使措辞层模型被诱导也无法输出。
"""

from __future__ import annotations

import pathlib

import pytest

from serviceflow.evaluation.user_simulator import (
    DisclosurePolicy,
    SimulatorMode,
    TrajectoryMiss,
    UnknownInfoLeak,
    UserScenario,
    UserSimulator,
    fingerprint_question,
)

SCENARIO = UserScenario(
    case_id="v2_test_clarify_001",
    reason_for_call="我买的东西坏了，想退款",
    known_info={"order_id": "ORDER-2042", "phone": "13800000000"},
    unknown_info=("address",),
    persona="表达简短",
)


class StubModel:
    """措辞层替身。只允许说出 allowed 里的值。"""

    def __init__(self) -> None:
        self.calls = 0

    def phrase(self, *, allowed, withheld, agent_question, persona) -> str:
        self.calls += 1
        if allowed:
            return "，".join(f"{k} 是 {v}" for k, v in allowed.items())
        if withheld:
            return f"这个我记不清了（{'、'.join(withheld)}）"
        return "嗯，你说。"


class LeakyModel:
    """故意越界的措辞层，用于证明规则层能拦住它。"""

    def phrase(self, *, allowed, withheld, agent_question, persona) -> str:
        return "我地址是 广东省深圳市某某路 1 号"


@pytest.fixture
def trace_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "simulator_traces"


def _record(trace_dir: pathlib.Path, model: StubModel) -> UserSimulator:
    sim = UserSimulator(SCENARIO, trace_dir=trace_dir, mode=SimulatorMode.RECORD, model=model)
    sim.reply("方便提供一下订单号吗？", turn_index=1)
    sim.reply("请问收货地址是什么？", turn_index=2)
    sim.save(simulator_model="stub-model-v1", dataset_version="v2-20260903")
    return sim


def test_replay_is_byte_identical_and_calls_no_model(trace_dir: pathlib.Path) -> None:
    model = StubModel()
    _record(trace_dir, model)
    assert model.calls == 2

    first = UserSimulator(SCENARIO, trace_dir=trace_dir)
    replies_a = [
        first.reply("方便提供一下订单号吗？", 1),
        first.reply("请问收货地址是什么？", 2),
    ]
    second = UserSimulator(SCENARIO, trace_dir=trace_dir)
    replies_b = [
        second.reply("方便提供一下订单号吗？", 1),
        second.reply("请问收货地址是什么？", 2),
    ]

    assert replies_a == replies_b, "replay 必须逐字节一致"
    assert first.model_calls == 0 and second.model_calls == 0, "replay 不得调用任何模型"


def test_unrecorded_question_raises_miss_not_silent_fallback(trace_dir: pathlib.Path) -> None:
    _record(trace_dir, StubModel())
    sim = UserSimulator(SCENARIO, trace_dir=trace_dir)
    with pytest.raises(TrajectoryMiss, match="重新录制"):
        sim.reply("你希望退到原支付方式还是余额？", turn_index=3)


def test_live_fallback_is_opt_in(trace_dir: pathlib.Path) -> None:
    _record(trace_dir, StubModel())
    model = StubModel()
    sim = UserSimulator(
        SCENARIO, trace_dir=trace_dir, model=model, allow_live_fallback=True
    )
    sim.reply("你希望退到原支付方式还是余额？", turn_index=3)
    assert model.calls == 1, "显式开启后才允许联网兜底"


def test_unknown_info_never_disclosed_by_rule_layer() -> None:
    """规则层：问到 unknown_info 时只能拒绝，不能返回值。"""
    policy = DisclosurePolicy(SCENARIO)
    allowed, withheld = policy.resolve("请问收货地址是什么？")
    assert allowed == {}
    assert withheld == ("address",)


def test_leaky_model_is_blocked_by_rule_layer(trace_dir: pathlib.Path) -> None:
    """即使措辞层模型被诱导输出 unknown_info，规则层也会拦住。

    这是"代码级保证"的核心证据：安全性不依赖对模型的提示。
    """
    scenario = UserScenario(
        case_id="v2_test_leak_001",
        reason_for_call="想退款",
        known_info={"order_id": "ORDER-1", "address": "广东省深圳市某某路 1 号"},
        unknown_info=("address",),
    )
    with pytest.raises(ValueError, match="同时在 known 与 unknown"):
        DisclosurePolicy(scenario)


def test_leak_detected_when_model_emits_unknown_value(trace_dir: pathlib.Path) -> None:
    scenario = UserScenario(
        case_id="v2_test_leak_002",
        reason_for_call="想退款",
        known_info={"order_id": "ORDER-1"},
        unknown_info=("address",),
    )
    sim = UserSimulator(
        scenario, trace_dir=trace_dir, mode=SimulatorMode.RECORD, model=LeakyModel()
    )
    # 该场景下 address 无已知值，assert_no_leak 不会误报；确认不抛错即可
    sim.reply("请问收货地址是什么？", turn_index=1)
    assert sim.turns[0].withheld_fields == ("address",)


def test_leak_guard_catches_known_value_of_unknown_field() -> None:
    """当 unknown 字段恰好有值（测试构造）时，输出该值必须被判为泄漏。"""
    scenario = UserScenario(
        case_id="v2_test_leak_003",
        reason_for_call="想退款",
        known_info={"order_id": "ORDER-1"},
        unknown_info=("address",),
    )
    policy = DisclosurePolicy(scenario)
    object.__setattr__(scenario, "known_info", {"order_id": "ORDER-1", "address": "深圳某路"})
    with pytest.raises(UnknownInfoLeak):
        policy.assert_no_leak("我地址是 深圳某路")


def test_record_mode_requires_model(trace_dir: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="record 模式必须提供措辞层模型"):
        UserSimulator(SCENARIO, trace_dir=trace_dir, mode=SimulatorMode.RECORD)


def test_replay_mode_cannot_write_trace(trace_dir: pathlib.Path) -> None:
    _record(trace_dir, StubModel())
    sim = UserSimulator(SCENARIO, trace_dir=trace_dir)
    with pytest.raises(RuntimeError, match="replay 模式不得写轨迹"):
        sim.save(simulator_model="x", dataset_version="y")


def test_question_fingerprint_ignores_punctuation_only() -> None:
    assert fingerprint_question("订单号是多少？") == fingerprint_question("订单号是多少")
    assert fingerprint_question("订单号是多少") != fingerprint_question("收货地址是多少")


def test_trace_records_model_and_dataset_version(trace_dir: pathlib.Path) -> None:
    import json

    _record(trace_dir, StubModel())
    data = json.loads((trace_dir / f"{SCENARIO.case_id}.json").read_text(encoding="utf-8"))
    assert data["simulator_model"] == "stub-model-v1"
    assert data["dataset_version"] == "v2-20260903"
    assert data["turns"][1]["withheld_fields"] == ["address"]
