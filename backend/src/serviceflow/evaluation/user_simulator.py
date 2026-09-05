"""多轮评测用的用户模拟器（三层设计 + 录制/回放）。

为什么不手写多轮台词：手写对话僵硬、覆盖窄，而且"用户会怎么补充信息"由出题人
预设，测不出真实的追问能力。参照 τ-bench 的方法论自建（未导入其数据）。

三层结构：

1. **规则层（本模块，确定性）** —— 这一轮能不能透露某条信息，由 ``known_info`` /
   ``unknown_info`` **用代码判定**，不交给模型。因此"不泄漏 unknown_info"是
   **代码级保证**，不是对模型的祈祷。这与本项目"模型不决定业务、代码决定"
   的核心主张同构。
2. **措辞层（模型，仅 record 模式调用）** —— 把规则层允许的内容说成符合 persona
   语气的自然中文。
3. **录制-回放层** —— 措辞结果存成轨迹文件，之后默认回放。

为什么不靠"固定 seed"保证可复现：托管 API 即使 ``temperature=0`` 也不保证逐次
一致（批处理浮点非确定性、供应商换硬件、模型别名指向的版本变更、MoE 路由差异）。
可复现性由 replay 提供，不由 seed 提供。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class SimulatorMode(StrEnum):
    REPLAY = "replay"
    RECORD = "record"


class UnknownInfoLeak(RuntimeError):
    """措辞层试图输出 unknown_info 中的内容。属于严重缺陷，不得降级处理。"""


class TrajectoryMiss(RuntimeError):
    """回放时 Agent 问出了录制中没有的问题。

    这是**预期会发生**的：Agent 行为在各 Step 之间会变。正确处理是重新录制，
    而不是静默编一个回答 —— 那会让评测悄悄失真。
    """


@dataclass(frozen=True)
class UserScenario:
    """来自 V2 案例的 ``user_scenario`` 字段。"""

    case_id: str
    reason_for_call: str
    known_info: dict[str, str] = field(default_factory=dict)
    unknown_info: tuple[str, ...] = ()
    persona: str | None = None


@dataclass(frozen=True)
class SimulatorTurn:
    turn_index: int
    agent_question: str
    question_fingerprint: str
    disclosed_fields: tuple[str, ...]
    withheld_fields: tuple[str, ...]
    user_reply: str


class PhrasingModel(Protocol):
    """措辞层接口。只在 record 模式被调用。"""

    def phrase(self, *, allowed: dict[str, str], withheld: tuple[str, ...],
               agent_question: str, persona: str | None) -> str: ...


def fingerprint_question(text: str) -> str:
    """把 Agent 的提问归一化后取指纹，作为轨迹索引键。

    归一化掉空白与标点，避免措辞的细微差别导致大量 miss；但**不做语义归一**，
    因为语义相近而实际不同的提问必须被区分开。
    """
    normalized = re.sub(r"[\s，。？！,.\?\!、：:；;]+", "", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class DisclosurePolicy:
    """规则层：决定这一轮可以透露什么。**这一层没有模型参与。**"""

    def __init__(self, scenario: UserScenario) -> None:
        self._scenario = scenario
        overlap = set(scenario.known_info) & set(scenario.unknown_info)
        if overlap:
            raise ValueError(f"{scenario.case_id}: 字段同时在 known 与 unknown 中: {overlap}")

    def resolve(self, agent_question: str) -> tuple[dict[str, str], tuple[str, ...]]:
        """返回 (可透露的字段, 被拒绝的字段)。"""
        asked = [f for f in self._all_fields() if self._mentions(agent_question, f)]
        allowed = {f: self._scenario.known_info[f] for f in asked if f in self._scenario.known_info}
        withheld = tuple(f for f in asked if f in self._scenario.unknown_info)
        return allowed, withheld

    def assert_no_leak(self, reply: str) -> None:
        """措辞层输出的最后一道闸：出现 unknown_info 的值就是缺陷。"""
        for field_name in self._scenario.unknown_info:
            value = self._scenario.known_info.get(field_name)
            if value and value in reply:
                raise UnknownInfoLeak(
                    f"{self._scenario.case_id}: 回复中出现了 unknown_info 字段 {field_name}"
                )

    def _all_fields(self) -> tuple[str, ...]:
        return tuple(self._scenario.known_info) + tuple(self._scenario.unknown_info)

    @staticmethod
    def _mentions(question: str, field_name: str) -> bool:
        aliases = {
            "order_id": ("订单号", "订单编号", "单号", "order"),
            "phone": ("手机", "电话", "联系方式"),
            "address": ("地址", "收货"),
            "friend_order_id": ("朋友", "另一个订单"),
        }
        keys = aliases.get(field_name, ())
        lowered = question.lower()
        return field_name in lowered or any(k.lower() in lowered for k in keys)


class UserSimulator:
    """对外入口。默认 replay，record 需显式开启。"""

    def __init__(
        self,
        scenario: UserScenario,
        *,
        trace_dir: pathlib.Path,
        mode: SimulatorMode = SimulatorMode.REPLAY,
        model: PhrasingModel | None = None,
        allow_live_fallback: bool = False,
    ) -> None:
        if mode is SimulatorMode.RECORD and model is None:
            raise ValueError("record 模式必须提供措辞层模型")
        self._scenario = scenario
        self._policy = DisclosurePolicy(scenario)
        self._mode = mode
        self._model = model
        self._allow_live_fallback = allow_live_fallback
        self._path = trace_dir / f"{scenario.case_id}.json"
        self._turns: list[SimulatorTurn] = []
        self._recorded: dict[str, str] = {}
        if mode is SimulatorMode.REPLAY:
            self._recorded = self._load()
        self.model_calls = 0  # replay 下必须始终为 0

    def reply(self, agent_question: str, turn_index: int) -> str:
        allowed, withheld = self._policy.resolve(agent_question)
        key = fingerprint_question(agent_question)

        if self._mode is SimulatorMode.REPLAY:
            if key in self._recorded:
                text = self._recorded[key]
            elif self._allow_live_fallback and self._model is not None:
                text = self._phrase(allowed, withheld, agent_question)
            else:
                raise TrajectoryMiss(
                    f"{self._scenario.case_id} 轮次 {turn_index}: 轨迹中没有该提问。"
                    " Agent 行为已变化，需要重新录制（record 模式），"
                    " 不要静默降级 —— 那会让评测失真。"
                )
        else:
            text = self._phrase(allowed, withheld, agent_question)
            self._recorded[key] = text

        self._policy.assert_no_leak(text)
        self._turns.append(
            SimulatorTurn(
                turn_index=turn_index,
                agent_question=agent_question,
                question_fingerprint=key,
                disclosed_fields=tuple(allowed),
                withheld_fields=withheld,
                user_reply=text,
            )
        )
        return text

    def opening_message(self) -> str:
        return self._scenario.reason_for_call

    def save(self, *, simulator_model: str, dataset_version: str) -> pathlib.Path:
        """只在 record 模式调用。轨迹带模型名与案例集版本，便于追溯。"""
        if self._mode is not SimulatorMode.RECORD:
            raise RuntimeError("replay 模式不得写轨迹")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "case_id": self._scenario.case_id,
            "simulator_model": simulator_model,
            "dataset_version": dataset_version,
            "replies": self._recorded,
            "turns": [
                {
                    "turn_index": t.turn_index,
                    "agent_question": t.agent_question,
                    "question_fingerprint": t.question_fingerprint,
                    "disclosed_fields": list(t.disclosed_fields),
                    "withheld_fields": list(t.withheld_fields),
                    "user_reply": t.user_reply,
                }
                for t in self._turns
            ],
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
        return self._path

    @property
    def turns(self) -> tuple[SimulatorTurn, ...]:
        return tuple(self._turns)

    def _phrase(
        self, allowed: dict[str, str], withheld: tuple[str, ...], agent_question: str
    ) -> str:
        assert self._model is not None
        self.model_calls += 1
        return self._model.phrase(
            allowed=allowed,
            withheld=withheld,
            agent_question=agent_question,
            persona=self._scenario.persona,
        )

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return dict(data.get("replies", {}))
