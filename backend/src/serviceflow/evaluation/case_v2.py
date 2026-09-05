"""V2 评测案例契约。

V1 的 ``EvalCase``（见 ``models.py``）是冻结基线，不做修改。V2 在其字段基础上
扩展身份/租户、数据集划分、风险等级、允许工具、确认与审批要求、以及用户模拟器
所需的 known/unknown 信息。

V2 描述的能力大部分要到 Step 5-7 才实现，因此 V2 案例在当前阶段**预期是红的**。
本模块只负责契约校验：schema 正确、ID 唯一、划分合法、计数与 manifest 一致。
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class V2Split(StrEnum):
    """数据集划分。holdout 不参与调参，只在最终验收打开一次。"""

    SMOKE = "smoke"
    REGRESSION = "regression"
    GOLDEN = "golden"
    BOUNDARY_SECURITY = "boundary_security"
    RELIABILITY_CONCURRENCY = "reliability_concurrency"
    HOLDOUT = "holdout"


class V2RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class V2Origin(StrEnum):
    """样本来源。用于防止同一模板泄漏到调参与最终验证。"""

    HANDCRAFTED = "handcrafted"
    SYNTHETIC = "synthetic"
    DERIVED_EXTERNAL = "derived_external"


class V2RewardType(StrEnum):
    """一条案例的评分依据。参照 τ³-bench 的 ``RewardType`` 设计（MIT）。

    关键设计（借自 τ³-bench 的判断，并有其实测支撑）：**默认不按固定工具序列评分**。
    期望工具列表的用途是推算目标终态，任何达到等价终态的路径都算通过。
    只有 ``ACTION`` 会把工具序列变成硬要求——Sierra 在 retail/airline/telecom
    三个域的 114+ 任务里**一次都没用过它**（实测 `reward_basis` 分布：DB 114/114、
    NL_ASSERTION 112/114、ACTION 0/114）。

    这对 009 尤其重要：2.0 让模型自主决定工具顺序，若沿用 V1 的严格顺序全等比较，
    会出现"系统变好了但工具指标暴跌"的假性回归。
    """

    DB = "DB"                        # 数据库终态匹配（默认，最重要）
    COMMUNICATE = "COMMUNICATE"      # communicate_info 的每条都出现在回复里
    ENV_ASSERTION = "ENV_ASSERTION"  # 环境断言通过（审计记录、幂等键等）
    NL_ASSERTION = "NL_ASSERTION"    # 语义断言由 LLM 判定（仅辅助，不用于安全结论）
    ACTION = "ACTION"                # 强制工具序列匹配。**慎用**，见上文


class V2LanguagePhenomenon(StrEnum):
    """具体的中文语言现象。

    这些现象从 V1 ``serviceflow_v1_complex_60.jsonl`` 的 60 条案例中逐条提炼而来。
    V1 的**思想**很好（真实用户就是这样说话的），但承载方式僵硬：台词写死、
    工具序列严格全等、每个现象只有一种说法、没有现象标注。

    加这个枚举解决 V1 做不到的一件事：**按语言现象归因失败**。
    V1 只能说"复杂 60 案 93.33%"，不能说"条件式诉求 100%、排除法表意 60%"。
    有了标注，Hard Case 分析才能落到"哪一类表达最容易让模型出错"。
    """

    # —— 复合与演进 ——
    CONDITIONAL_REQUEST = "conditional_request"        # 如果 X 就 Y
    INTENT_EVOLUTION = "intent_evolution"              # 本想 A，因为某原因改成 B
    MULTI_INTENT = "multi_intent"                      # 一句话多个独立诉求
    MULTIPLE_ORDERS = "multiple_orders"                # 一句话提多个订单
    # —— 否定与纠正 ——
    EXCLUSION_PHRASING = "exclusion_phrasing"          # 用"不要 A"来锁定 B
    METALINGUISTIC_CORRECTION = "metalinguistic_correction"  # "我刚才用词不准确"
    EXPLICIT_NEGATION_FIRST = "explicit_negation_first"      # "不是取消 X，而是…"
    DOUBLE_NEGATION = "double_negation"                # "不是不想要"
    PREEMPTIVE_DISMISSAL = "preemptive_dismissal"      # "我不是来问使用方法的"
    # —— 隐含与省略 ——
    IMPLICIT_GOAL = "implicit_goal"                    # 全程不说诉求词，只描述状态
    COLLOQUIAL_ELLIPSIS = "colloquial_ellipsis"        # "反正处理一下"
    PRONOUN_REFERENCE = "pronoun_reference"            # "那个东西"
    # —— 歧义 ——
    QUANTITY_AMBIGUITY = "quantity_ambiguity"          # "有一单不要了"/"退一半"
    VAGUE_TIME_REFERENCE = "vague_time_reference"      # "前两周收到的那单"
    UNDERSPECIFIED_CHOICE = "underspecified_choice"    # "退款或换货都行，你们看着办"
    # —— 噪声与语域 ——
    BACKGROUND_BEFORE_REQUEST = "background_before_request"  # 大段背景后才说诉求
    IRRELEVANT_IDENTIFIERS = "irrelevant_identifiers"  # 夹带优惠券码、手机尾号
    PROXY_REQUEST = "proxy_request"                    # "给我爸买的"
    EMOTIONAL_PRESSURE = "emotional_pressure"          # "赶紧给个说法"
    # —— 表达变体（用于表达鲁棒性）——
    CODE_SWITCHING = "code_switching"                  # 中英混杂
    DIALECT = "dialect"                                # 方言词
    FORMAL_REGISTER = "formal_register"                # 书面公文语气
    TERSE = "terse"                                    # 极简省略
    # —— 多轮 ——
    PROGRESSIVE_DISCLOSURE = "progressive_disclosure"  # 分多轮逐步补全


class V2Category(StrEnum):
    # 中文语言理解难度（承接 V1 complex_60 的能力，V1 退役后由 V2 承担）
    BLENDED_INTENT = "blended_intent"
    IMPLICIT_INTENT = "implicit_intent"
    NOISY_CONTEXT = "noisy_context"
    CORRECTION_NEGATION = "correction_negation"
    AMBIGUOUS_REQUEST = "ambiguous_request"
    NL_VARIANT = "nl_variant"
    # 业务能力
    ORDER_QUERY = "order_query"
    SHIPMENT_EXPLAIN = "shipment_explain"
    RETURN_REQUEST = "return_request"
    EXCHANGE_REQUEST = "exchange_request"
    REFUND_REQUEST = "refund_request"
    COMPENSATION_REQUEST = "compensation_request"
    CREATE_TICKET = "create_ticket"
    HANDOFF = "handoff"
    POLICY_CONFLICT = "policy_conflict"
    MISSING_IDENTITY_OR_ORDER = "missing_identity_or_order"
    MULTI_TURN_RECOVERY = "multi_turn_recovery"
    USER_CONFIRMATION = "user_confirmation"
    MULTI_CONFIRMATION = "multi_confirmation"
    RAG_LOW_RECALL = "rag_low_recall"
    MALFORMED_MODEL_OUTPUT = "malformed_model_output"
    # 权限与隔离
    CROSS_TENANT = "cross_tenant"
    INSUFFICIENT_PERMISSION = "insufficient_permission"
    PII_MASKING = "pii_masking"
    # 可靠性
    PROVIDER_SUCCESS = "provider_success"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    PROVIDER_PENDING = "provider_pending"
    PROVIDER_UNKNOWN = "provider_unknown"
    DUPLICATE_REQUEST = "duplicate_request"
    CONCURRENT_CONFLICT = "concurrent_conflict"
    WEBHOOK_DUPLICATE = "webhook_duplicate"
    OUTBOX_REDELIVERY = "outbox_redelivery"
    WORKER_RESTART = "worker_restart"
    REDIS_CACHE_STATE = "redis_cache_state"
    # 安全
    INJECTION = "injection"
    FALSE_POSITIVE_PROBE = "false_positive_probe"


class V2InjectionVariant(StrEnum):
    """注入变体。计划补充 E 要求拆开，不得合并成一个 ``prompt_injection`` 类别。"""

    DIRECT = "direct"
    INDIRECT_POLICY_DOC = "indirect_policy_doc"
    FORGED_TOOL_ANNOTATION = "forged_tool_annotation"
    TOOL_RESULT_INJECTION = "tool_result_injection"
    ENCODING_OR_MULTILINGUAL = "encoding_or_multilingual"
    LONG_CONTEXT_DILUTION = "long_context_dilution"
    FIELD_LEVEL = "field_level"
    MEMORY_POISONING = "memory_poisoning"


_LANGUAGE_CATEGORIES = frozenset(
    {
        V2Category.BLENDED_INTENT,
        V2Category.IMPLICIT_INTENT,
        V2Category.NOISY_CONTEXT,
        V2Category.CORRECTION_NEGATION,
        V2Category.AMBIGUOUS_REQUEST,
        V2Category.NL_VARIANT,
        V2Category.MULTI_TURN_RECOVERY,
    }
)


class V2Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    user_id: str
    permission_scope: tuple[str, ...] = ()


class V2InitialState(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str | None = None
    owner_user_id: str | None = None
    status: str | None = None
    total_amount: Decimal | None = None
    delivered_days_ago: int | None = None
    shipment_status: str | None = None
    existing_case_id: str | None = None
    notes: str | None = None


class V2UserScenario(BaseModel):
    """用户模拟器的输入契约（参照 τ-bench 方法论自建，未导入其数据）。

    案例不写死逐轮台词：只声明用户来意、知道什么、不记得什么。
    ``unknown_info`` 由规则层用代码拦截，模型无法透露 —— 这是代码级保证，
    不依赖对模型的提示。
    """

    model_config = ConfigDict(frozen=True)

    reason_for_call: str
    known_info: dict[str, str] = Field(default_factory=dict)
    unknown_info: tuple[str, ...] = ()
    persona: str | None = None


class V2ExpectedState(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_status: str | None = None
    operation_status: str | None = None
    order_status: str | None = None
    refund_status: str | None = None
    approval_status: str | None = None
    ticket_status: str | None = None


class V2Expected(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: str | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    allowed_tools: tuple[str, ...] = ()
    expected_tool_calls: tuple[dict[str, object], ...] = ()
    state_transitions: tuple[str, ...] = ()
    final_state: V2ExpectedState
    requires_confirmation: bool = False
    requires_approval: bool = False
    allow_handoff: bool = False
    must_refuse: bool = False
    side_effect_must_not_occur: bool = False
    # 借自 τ³-bench：必须告知用户的信息。只看数据库终态会漏掉"办成了但没告诉用户"
    communicate_info: tuple[str, ...] = ()
    # 借自 τ³-bench：环境断言（审计记录存在、幂等键复用、无重复副作用等）
    env_assertions: tuple[str, ...] = ()


class EvalCaseV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    category: V2Category
    split: V2Split
    risk_level: V2RiskLevel
    origin: V2Origin
    identity: V2Identity
    initial_state: V2InitialState
    user_scenario: V2UserScenario
    expected: V2Expected
    scoring: tuple[str, ...]
    reward_basis: tuple[V2RewardType, ...] = (V2RewardType.DB,)
    # 该案例包含哪些中文语言现象。语言难度类案例必填，用于按现象归因失败
    language_phenomena: tuple[V2LanguagePhenomenon, ...] = ()
    # 表达鲁棒性分组：同组案例是**同一诉求的不同说法**，期望结果必须完全一致，
    # 且必须全部通过才算这一组过。V1 完全没有这个维度——每个语言现象只有一种说法，
    # 测不出"换个说法就不会了"。
    paraphrase_group: str | None = None
    injection_variant: V2InjectionVariant | None = None
    derived_from: str | None = None
    fault_injection: dict[str, object] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_contract(self) -> "EvalCaseV2":
        if self.category is V2Category.INJECTION and self.injection_variant is None:
            raise ValueError(f"{self.id}: injection 案例必须声明 injection_variant")
        if self.category is not V2Category.INJECTION and self.injection_variant is not None:
            raise ValueError(f"{self.id}: 非 injection 案例不得声明 injection_variant")
        if self.origin is V2Origin.DERIVED_EXTERNAL and not self.derived_from:
            raise ValueError(f"{self.id}: 外部改造样本必须写 derived_from")
        if self.category is V2Category.FALSE_POSITIVE_PROBE and self.expected.must_refuse:
            raise ValueError(f"{self.id}: 误拦截探针的期望结果必须是正常完成，不能是拒绝")
        if self.expected.must_refuse and not self.expected.side_effect_must_not_occur:
            raise ValueError(f"{self.id}: 期望拒绝的案例必须同时断言无副作用")
        if not self.scoring:
            raise ValueError(f"{self.id}: 必须声明评分标准")
        if not self.reward_basis:
            raise ValueError(f"{self.id}: reward_basis 不能为空")
        if self.category in _LANGUAGE_CATEGORIES and not self.language_phenomena:
            raise ValueError(
                f"{self.id}: 语言难度类案例必须声明 language_phenomena，"
                " 否则无法按现象归因失败（这正是 V1 complex_60 的短板）"
            )
        if V2RewardType.COMMUNICATE in self.reward_basis and not self.expected.communicate_info:
            raise ValueError(f"{self.id}: 声明了 COMMUNICATE 就必须写 communicate_info")
        if self.expected.communicate_info and V2RewardType.COMMUNICATE not in self.reward_basis:
            raise ValueError(
                f"{self.id}: 写了 communicate_info 就必须把 COMMUNICATE 加入 reward_basis"
            )
        if V2RewardType.ENV_ASSERTION in self.reward_basis and not self.expected.env_assertions:
            raise ValueError(f"{self.id}: 声明了 ENV_ASSERTION 就必须写 env_assertions")
        if V2RewardType.NL_ASSERTION in self.reward_basis and self.risk_level is V2RiskLevel.HIGH:
            raise ValueError(
                f"{self.id}: 高风险案例不得依赖 LLM 语义断言评分。"
                " 越权、泄露、审批绕过、幂等必须用确定性断言（DB / ENV_ASSERTION）。"
            )
        return self
