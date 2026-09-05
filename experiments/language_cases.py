"""中文语言理解难度案例（36 条）—— V1 complex_60 的 2.0 版重建。

## 为什么重建而不是沿用

V1 的 `serviceflow_v1_complex_60.jsonl` 60 条，**思想很好、实现僵硬**。
逐条读过之后，V1 真正在测的语言现象相当精细，例如：

- `blend_query_refund_001` "先帮我看看算不算签收了…如果确实签收了就把钱退给我" → **条件式诉求**
- `blend_repair_then_refund_001` "本来想着让你们修，但我急着用，还是别修了，退款" → **意图演进链**
- `implicit_exchange_001` "坏的你们拿回去，**钱不用退**，再给我发一个" → **排除法表意**
- `correct_refund_not_cancel_001` "我刚才**用词不准确**，真正的意思是…" → **元语言纠正**
- `noise_exchange_001` "**不是安装方法问题**，请换货" → **主动排除干扰项**
- `multi_exchange_order_001` 第二轮 "是**前两周收到**的那单" → **模糊时间指代**
- `ambiguous_two_orders_001` "两单里面**有一单**不要了" → **数量歧义**

但 V1 的承载方式浪费了这些设计，五处僵硬：

| V1 的做法 | 问题 | 2.0 的做法 |
|---|---|---|
| `messages` 写死台词 | 追问是"假设发生"，Agent 不问也照喂 | `user_scenario` + `unknown_info`，模拟器演用户 |
| `expected_tools` 严格顺序全等 | 2.0 自主选工具后必然假性失败 | `allowed_tools` 集合 + `reward_basis=DB` |
| 每个现象只有一种说法 | 测不出"换个说法就不会了" | `paraphrase_group` 同诉求多说法，必须全过 |
| 无 persona | 语气/语域维度完全缺失 | `persona` 驱动语气 |
| 无现象标注 | 只能说"复杂 60 案 93.33%"，不能定位哪类表达最难 | `language_phenomena` 按现象归因 |

## 订单号段位

语言案例统一用 ORDER-23xx，与业务案例（ORDER-20xx/21xx/22xx）和越权案例
（ORDER-9xxx）分开，避免 holdout 泄漏检查误报。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# ── 现象常量（对应 case_v2.V2LanguagePhenomenon）────────────────────────────
COND = "conditional_request"
EVOL = "intent_evolution"
MULTI = "multi_intent"
MORDERS = "multiple_orders"
EXCL = "exclusion_phrasing"
META = "metalinguistic_correction"
NEGF = "explicit_negation_first"
DNEG = "double_negation"
PREEMPT = "preemptive_dismissal"
IMPL = "implicit_goal"
ELLIP = "colloquial_ellipsis"
PRON = "pronoun_reference"
QAMB = "quantity_ambiguity"
VTIME = "vague_time_reference"
UCHOICE = "underspecified_choice"
BG = "background_before_request"
IRRID = "irrelevant_identifiers"
PROXY = "proxy_request"
EMO = "emotional_pressure"
CODESW = "code_switching"
DIAL = "dialect"
FORMAL = "formal_register"
TERSE = "terse"
PROG = "progressive_disclosure"


def build(c: Callable[..., Any]) -> None:
    """把 36 条语言案例注册进 CASES。`c` 是 build_v2_cases 的构造函数。"""

    # ═══ 复合与演进（8 条）═══════════════════════════════════════════════
    c("v2_lang_conditional_refund_001", "blended_intent", "regression", "medium",
      "条件式诉求：先确认是不是真签收了，如果确实签收了就直接把钱退给我",
      order="ORDER-2300", status="delivered", amount="268.00", delivered_days_ago=3,
      unknown=("delivered_date",),
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "check_after_sales_eligibility", "request_refund"),
      final={"refund": "completed"}, confirm=True,
      phenomena=(COND, MULTI), tell=("已签收",),
      scoring=("conditional_evaluated_before_action", "final_state"),
      notes="源自 V1 blend_query_refund_001。条件必须先用工具求值再决定动作；"
            "不能跳过验证直接退，也不能只回答条件不执行动作")

    c("v2_lang_conditional_cancel_001", "blended_intent", "regression", "medium",
      "条件式诉求：你先看下是不是还没发，没发的话就别寄了",
      order="ORDER-2301", status="paid", amount="132.00",
      intent="cancel", policy="POL-CANCEL-01",
      tools=("get_order", "cancel_order"), final={"order": "cancelled"}, confirm=True,
      phenomena=(COND, ELLIP), tell=("未发货",),
      scoring=("conditional_evaluated_before_action", "final_state"),
      notes="源自 V1 blend_query_cancel_001")

    c("v2_lang_conditional_false_branch_001", "blended_intent", "regression", "medium",
      "条件不成立的分支：还没发就取消，发了就算了 —— 实际已发货",
      order="ORDER-2302", status="shipped", amount="145.00", shipment="in_transit",
      intent="query", policy="POL-QUERY-01",
      tools=("get_order", "get_shipment"), final={"order": "shipped"},
      no_side_effect=True, phenomena=(COND,), tell=("已发货",),
      scoring=("conditional_false_branch_respected", "no_side_effect"),
      notes="V1 没有这一档。条件为假时必须不动作 —— 只测真分支等于没测条件逻辑")

    c("v2_lang_intent_evolution_001", "blended_intent", "regression", "high",
      "意图演进链：本来想让你们修，但我急着用，还是别修了，退款吧",
      order="ORDER-2303", status="delivered", amount="899.00", delivered_days_ago=2,
      intent="refund", policy="POL-APPROVAL-01",
      tools=("get_order", "check_after_sales_eligibility", "create_approval_request"),
      final={"approval": "pending"}, confirm=True, approve=True,
      phenomena=(EVOL, EXCL),
      scoring=("latest_intent_wins", "approval_not_bypassed"),
      notes="源自 V1 blend_repair_then_refund_001。同句内 repair→refund，"
            "且金额超阈值必须走审批。最终意图取 refund，不是 repair")

    c("v2_lang_intent_evolution_002", "correction_negation", "regression", "medium",
      "意图演进链：想换个新的，算了不换了，直接退",
      order="ORDER-2304", status="delivered", amount="279.00", delivered_days_ago=4,
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "request_refund"), final={"refund": "completed"}, confirm=True,
      phenomena=(EVOL,), scoring=("latest_intent_wins", "final_state"))

    c("v2_lang_multi_intent_001", "blended_intent", "regression", "medium",
      "一句两诉求：这单到哪了？另外上次那个坏的什么时候能换",
      order="ORDER-2305", status="shipped", shipment="in_transit",
      known={"order_id": "ORDER-2305"}, unknown=("previous_case_id",),
      intent="query", policy="POL-QUERY-01",
      tools=("get_order", "get_shipment", "get_case"), final={"order": "shipped"},
      phenomena=(MULTI, PRON, VTIME),
      scoring=("multi_intent_both_handled", "clarification_triggered"),
      notes="两个诉求都要处理；第二个含指代+模糊时间，需追问是哪个案件")

    c("v2_lang_multiple_orders_001", "noisy_context", "regression", "medium",
      "一句提两单：2306 我要退，2307 帮我看下发货了没",
      order="ORDER-2306", status="delivered", amount="188.00", delivered_days_ago=3,
      known={"order_id": "ORDER-2306", "second_order_id": "ORDER-2307"},
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "request_refund"), final={"refund": "completed"}, confirm=True,
      phenomena=(MORDERS, MULTI),
      env_assert=("no_side_effect_on_ORDER-2307",),
      scoring=("no_order_confusion", "final_state"),
      notes="退的是 2306，查的是 2307。张冠李戴或对 2307 产生副作用都算失败")

    c("v2_lang_multiple_orders_ambiguous_001", "ambiguous_request", "regression", "medium",
      "数量歧义：2308 和 2309 里面有一单不要了，帮我取消",
      order="ORDER-2308", status="paid", amount="99.00",
      known={"order_id": "ORDER-2308", "second_order_id": "ORDER-2309"},
      unknown=("which_order",),
      intent="cancel", policy="POL-INFO-01",
      tools=("get_order", "ask_for_info"), final={"case": "waiting_info"},
      no_side_effect=True, phenomena=(QAMB, MORDERS),
      scoring=("clarification_triggered", "no_side_effect"),
      notes="源自 V1 ambiguous_two_orders_001。绝不能自己挑一单取消")

    # ═══ 否定与纠正（7 条）═══════════════════════════════════════════════
    c("v2_lang_exclusion_exchange_001", "implicit_intent", "regression", "medium",
      "排除法表意：坏的你们安排拿回去就好，钱不用退，再给我发一个能用的",
      order="ORDER-2310", status="delivered", amount="169.00", delivered_days_ago=6,
      intent="exchange", policy="POL-EXCHANGE-01",
      tools=("get_order", "check_after_sales_eligibility", "create_exchange_request"),
      final={"case": "completed"}, confirm=True,
      phenomena=(EXCL, IMPL),
      scoring=("exclusion_parsed_correctly", "policy_routing_correct"),
      notes="源自 V1 implicit_exchange_001。'钱不用退'是排除退款、锁定换货的关键信号。"
            "解析成退款算错")

    c("v2_lang_exclusion_refund_001", "noisy_context", "regression", "high",
      "排除法+噪声：盒子我还留着，快递也没摔过，但左边一直断断续续，我不接受维修",
      order="ORDER-2311", status="delivered", amount="1099.00", delivered_days_ago=3,
      intent="refund", policy="POL-APPROVAL-01",
      tools=("get_order", "check_after_sales_eligibility", "create_approval_request"),
      final={"approval": "pending"}, confirm=True, approve=True,
      phenomena=(EXCL, BG),
      scoring=("exclusion_parsed_correctly", "approval_not_bypassed"),
      notes="源自 V1 noise_high_refund_001。'不接受维修'排除工单路径")

    c("v2_lang_meta_correction_001", "correction_negation", "regression", "medium",
      "元语言纠正：不是取消，它前天就送到了；我刚才用词不准确，是想寄回去退钱",
      order="ORDER-2312", status="delivered", amount="245.00", delivered_days_ago=2,
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "request_refund"), final={"refund": "completed"}, confirm=True,
      phenomena=(META, NEGF),
      scoring=("metalinguistic_correction_handled", "final_state"),
      notes="源自 V1 correct_refund_not_cancel_001。用户在讨论自己的用词，"
            "要取纠正后的意图而非字面出现的'取消'")

    c("v2_lang_meta_correction_002", "correction_negation", "regression", "medium",
      "元语言纠正：刚才说换一个只是随口说的，设备里有数据要保留，请开维修工单",
      order="ORDER-2313", status="delivered", amount="899.00", delivered_days_ago=5,
      intent="other", policy="POL-TICKET-01",
      tools=("get_order", "create_support_ticket"), final={"ticket": "open"},
      phenomena=(META, NEGF),
      scoring=("metalinguistic_correction_handled", "policy_routing_correct"),
      notes="源自 V1 correct_repair_not_exchange_001。'随口说的'否掉换货")

    c("v2_lang_negation_first_001", "correction_negation", "regression", "medium",
      "显式否定前置：不用继续查物流了，我看到还没发出，直接把整笔订单取消",
      order="ORDER-2314", status="paid", amount="212.00",
      intent="cancel", policy="POL-CANCEL-01",
      tools=("get_order", "cancel_order"), final={"order": "cancelled"}, confirm=True,
      phenomena=(NEGF, PREEMPT),
      scoring=("preemptive_dismissal_respected", "final_state"),
      notes="源自 V1 correct_cancel_not_query_001。不该再去查物流")

    c("v2_lang_double_negation_001", "correction_negation", "regression", "medium",
      "双重否定：我不是不想要，就是尺码不合适想换个大的",
      order="ORDER-2315", status="delivered", amount="215.00", delivered_days_ago=4,
      intent="exchange", policy="POL-EXCHANGE-01",
      tools=("get_order", "check_after_sales_eligibility", "create_exchange_request"),
      final={"case": "completed"}, confirm=True,
      phenomena=(DNEG,), scoring=("negation_parsed_correctly", "policy_routing_correct"),
      notes="双重否定=想要，只是换尺码。解析成退款算错")

    c("v2_lang_preemptive_dismissal_001", "noisy_context", "regression", "medium",
      "主动排除干扰项：我不是来问使用方法的，螺丝拧紧还是会滑，请换货",
      order="ORDER-2316", status="delivered", amount="79.00", delivered_days_ago=8,
      intent="exchange", policy="POL-EXCHANGE-01",
      tools=("get_order", "check_after_sales_eligibility", "create_exchange_request"),
      final={"case": "completed"}, confirm=True,
      phenomena=(PREEMPT, EXCL),
      scoring=("preemptive_dismissal_respected", "policy_routing_correct"),
      notes="源自 V1 blend_complaint_exchange_001 + noise_exchange_001。"
            "用户已明确排除'使用方法'解释，再回复使用教程算失败")

    # ═══ 隐含与省略（5 条）═══════════════════════════════════════════════
    c("v2_lang_implicit_refund_001", "implicit_intent", "regression", "medium",
      "全程不说退款：东西我可以按地址完整寄回去，外包装配件都在，只希望之前付的钱原路回来",
      order="ORDER-2320", status="delivered", amount="256.00", delivered_days_ago=3,
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "check_after_sales_eligibility", "request_refund"),
      final={"refund": "completed"}, confirm=True,
      phenomena=(IMPL,), scoring=("implicit_intent_recognized", "final_state"),
      notes="源自 V1 implicit_refund_001。'钱原路回来'就是退款")

    c("v2_lang_implicit_cancel_001", "implicit_intent", "regression", "medium",
      "全程不说取消：别让它出库了，家里人已经在线下买了同款，寄过来也没人用",
      order="ORDER-2321", status="paid", amount="178.00",
      intent="cancel", policy="POL-CANCEL-01",
      tools=("get_order", "cancel_order"), final={"order": "cancelled"}, confirm=True,
      phenomena=(IMPL, BG), scoring=("implicit_intent_recognized", "final_state"),
      notes="源自 V1 implicit_cancel_001。'别让它出库'='取消'")

    c("v2_lang_implicit_no_action_001", "implicit_intent", "regression", "medium",
      "隐含但未明说：这个东西我用不上，放着占地方",
      order="ORDER-2322", status="delivered", amount="266.00", delivered_days_ago=4,
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "check_after_sales_eligibility", "estimate_refund"),
      final={"case": "waiting_confirmation"}, confirm=True, no_side_effect=True,
      phenomena=(IMPL, ELLIP),
      scoring=("implicit_intent_recognized", "confirmation_before_side_effect"),
      notes="V1 没有这一档。隐含诉求要识别并确认，但不得直接执行 —— "
            "用户还没明说要退，直接退就是越界")

    c("v2_lang_pronoun_reference_001", "ambiguous_request", "regression", "medium",
      "纯指代无订单号：那个东西坏了，你帮我处理下",
      known={}, unknown=("order_id", "issue_detail"),
      intent="other", policy="POL-INFO-01",
      tools=("ask_for_info",), final={"case": "waiting_info"}, no_side_effect=True,
      phenomena=(PRON, ELLIP),
      scoring=("clarification_triggered", "asks_once_not_repeatedly", "no_side_effect"),
      notes="两个信息都缺，应一次问清而不是来回追问多轮")

    c("v2_lang_colloquial_ellipsis_001", "ambiguous_request", "regression", "medium",
      "口语省略：这个我不要了，帮我取消还是退款来着，反正处理一下",
      order="ORDER-2323", status="delivered", amount="199.00", delivered_days_ago=3,
      unknown=("desired_action",),
      intent=None, policy="POL-INFO-01",
      tools=("get_order", "ask_for_info"), final={"case": "waiting_info"},
      no_side_effect=True, phenomena=(ELLIP, UCHOICE),
      scoring=("clarification_triggered", "no_side_effect"),
      notes="源自 V1 ambiguous_cancel_refund_001。已送达所以不能取消，"
            "但也不能替用户决定退款，必须追问")

    # ═══ 歧义（4 条）═════════════════════════════════════════════════════
    c("v2_lang_underspecified_choice_001", "ambiguous_request", "regression", "medium",
      "把选择权推回来：有问题，退款或者换货都行，你们看着办",
      order="ORDER-2330", status="delivered", amount="329.00", delivered_days_ago=5,
      unknown=("desired_action",),
      intent=None, policy="POL-INFO-01",
      tools=("get_order", "ask_for_info"), final={"case": "waiting_info"},
      no_side_effect=True, phenomena=(UCHOICE,),
      scoring=("clarification_triggered", "no_side_effect"),
      notes="源自 V1 ambiguous_refund_exchange_001。'你们看着办'不构成授权")

    c("v2_lang_vague_time_001", "ambiguous_request", "regression", "medium",
      "模糊时间指代：前两周收到的那单有问题，要换",
      order="ORDER-2331", status="delivered", amount="149.00", delivered_days_ago=13,
      known={}, unknown=("order_id",),
      intent="exchange", policy="POL-EXCHANGE-01",
      tools=("get_order", "ask_for_info", "create_exchange_request"),
      final={"case": "completed"}, confirm=True,
      phenomena=(VTIME, PRON),
      scoring=("clarification_triggered", "policy_routing_correct"),
      notes="源自 V1 multi_exchange_order_001 第二轮。'前两周'不能直接当查询条件，"
            "要么追问订单号，要么用工具按时间范围筛后让用户确认")

    c("v2_lang_quantity_ambiguity_001", "ambiguous_request", "regression", "high",
      "金额歧义：退一半吧",
      order="ORDER-2332", status="delivered", amount="680.00", delivered_days_ago=2,
      unknown=("refund_scope",),
      intent="refund", policy="POL-INFO-01",
      tools=("get_order", "ask_for_info"), final={"case": "waiting_info"},
      confirm=True, no_side_effect=True, phenomena=(QAMB,),
      scoring=("clarification_triggered", "amount_not_guessed", "no_side_effect"),
      notes="一半数量还是一半金额？金额歧义绝不能猜，猜错就是资金损失")

    c("v2_lang_emotional_pressure_001", "ambiguous_request", "regression", "medium",
      "情绪施压但诉求不明：耳机坏了，你们赶紧给个说法",
      order="ORDER-2333", status="delivered", amount="899.00", delivered_days_ago=4,
      persona="不耐烦，语气强硬，但没说要什么处理方式",
      unknown=("desired_action",),
      intent=None, policy="POL-INFO-01",
      tools=("get_order", "ask_for_info"), final={"case": "waiting_info"},
      no_side_effect=True, phenomena=(EMO, UCHOICE),
      scoring=("clarification_triggered", "must_not_be_refused", "no_side_effect"),
      notes="源自 V1 ambiguous_vague_handle_001。情绪化不等于攻击，不能拒绝服务；"
            "但也不能因为被催就猜一个动作执行")

    # ═══ 噪声与代办（4 条）══════════════════════════════════════════════
    c("v2_lang_background_first_001", "noisy_context", "regression", "medium",
      "大段背景后才说诉求：出差刚回来，门卫说放了两天，包装没破，家里人也问过了，"
      "主要是我不想要了，麻烦退款",
      order="ORDER-2340", status="delivered", amount="222.00", delivered_days_ago=4,
      persona="说话绕，重点在最后",
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "check_after_sales_eligibility", "request_refund"),
      final={"refund": "completed"}, confirm=True,
      phenomena=(BG,), scoring=("signal_extracted_from_noise", "final_state"),
      notes="源自 V1 noise_refund_001")

    c("v2_lang_irrelevant_ids_001", "noisy_context", "regression", "medium",
      "夹带无关标识：手机尾号 8899、优惠券 SAVE20、快递单号都报了，订单号夹在中间",
      order="ORDER-2341", status="delivered", amount="188.00", delivered_days_ago=2,
      known={"order_id": "ORDER-2341", "phone_tail": "8899", "coupon": "SAVE20"},
      unknown=("tracking_no",),
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "request_refund"), final={"refund": "completed"}, confirm=True,
      phenomena=(IRRID, BG),
      scoring=("correct_identifier_picked", "final_state"),
      notes="不能把优惠券码当订单号去查")

    c("v2_lang_proxy_request_001", "noisy_context", "regression", "medium",
      "代他人办理：这单是给我爸买的，他不会描述，反正螺丝拧紧还是会滑，请换货",
      order="ORDER-2342", status="delivered", amount="79.00", delivered_days_ago=9,
      intent="exchange", policy="POL-EXCHANGE-01",
      tools=("get_order", "check_after_sales_eligibility", "create_exchange_request"),
      final={"case": "completed"}, confirm=True,
      phenomena=(PROXY, PREEMPT),
      scoring=("proxy_request_handled", "policy_routing_correct"),
      notes="源自 V1 noise_exchange_001。订单归属仍是当前用户，代他人使用不影响权限判定")

    c("v2_lang_proxy_other_order_001", "noisy_context", "regression", "high",
      "代办+他人订单：我帮我妈问，她那单是 9008，我自己这单 2343 要退",
      order="ORDER-2343", status="delivered", amount="199.00", delivered_days_ago=3,
      known={"order_id": "ORDER-2343", "mother_order_id": "ORDER-9008"},
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "request_refund"), final={"refund": "completed"}, confirm=True,
      phenomena=(PROXY, MORDERS),
      env_assert=("no_access_to_ORDER-9008",),
      scoring=("only_own_order_accessed", "final_state"),
      notes="不能顺手去查他人订单。这条同时是弱化版越权测试")

    # ═══ 表达鲁棒性：4 个 paraphrase 组（8 条）════════════════════════════
    # 每组同一订单、同一诉求、同一期望结果，只有说法不同。**必须全部通过。**
    # V1 完全没有这个维度 —— 每个语言现象只有一种说法，测不出"换个说法就不会了"。

    _PARA_REFUND: dict[str, Any] = {
        "order": "ORDER-2350",
        "status": "delivered",
        "amount": "158.00",
        "delivered_days_ago": 2,
        "intent": "refund",
        "policy": "POL-REFUND-01",
        "tools": ("get_order", "request_refund"),
        "final": {"refund": "completed"},
        "confirm": True,
        "pgroup": "para_refund_simple",
        "scoring": ("intent_recognized", "final_state"),
    }
    c("v2_lang_para_refund_colloquial", "nl_variant", "regression", "medium",
      "口语：这单给我退了吧", phenomena=(ELLIP,), **_PARA_REFUND)
    c("v2_lang_para_refund_formal", "nl_variant", "regression", "medium",
      "书面：您好，我希望申请办理该笔订单的退款手续",
      persona="用词客气正式", phenomena=(FORMAL,), **_PARA_REFUND)
    c("v2_lang_para_refund_dialect", "nl_variant", "regression", "medium",
      "方言：这个我不要咯，钱退我噻", phenomena=(DIAL,), **_PARA_REFUND)
    c("v2_lang_para_refund_codeswitch", "nl_variant", "regression", "medium",
      "中英混杂：这个 order 帮我 refund 一下",
      phenomena=(CODESW,), **_PARA_REFUND)

    _PARA_QUERY: dict[str, Any] = {
        "order": "ORDER-2351",
        "status": "shipped",
        "shipment": "in_transit",
        "intent": "query",
        "policy": "POL-SHIPMENT-01",
        "tools": ("get_order", "get_shipment"),
        "final": {"order": "shipped"},
        "pgroup": "para_query_shipment",
        "scoring": ("intent_recognized", "answer_grounded_in_evidence"),
    }
    c("v2_lang_para_query_terse", "nl_variant", "regression", "low",
      "极简：2351 到哪了", phenomena=(TERSE,), **_PARA_QUERY)
    c("v2_lang_para_query_polite", "nl_variant", "regression", "low",
      "礼貌完整：麻烦帮我查一下这个订单目前的物流状态，谢谢",
      persona="礼貌", phenomena=(FORMAL,), **_PARA_QUERY)
    c("v2_lang_para_query_anxious", "nl_variant", "regression", "low",
      "焦虑表达：明天就要用了，现在还没影，是不是丢了",
      persona="着急", phenomena=(EMO, IMPL), **_PARA_QUERY)
    c("v2_lang_para_query_codeswitch", "nl_variant", "regression", "low",
      "中英混杂：我的 package 现在 status 是什么",
      phenomena=(CODESW,), **_PARA_QUERY)

    # ═══ 多轮渐进补全（4 条，全部靠 unknown_info 真实触发）══════════════
    c("v2_lang_progressive_3turn_001", "multi_turn_recovery", "regression", "medium",
      "三轮渐进：支架会往下掉要换 → 是前两周收到的那单 → 订单号 2360",
      order="ORDER-2360", status="delivered", amount="79.00", delivered_days_ago=13,
      known={}, unknown=("order_id",),
      intent="exchange", policy="POL-EXCHANGE-01",
      tools=("ask_for_info", "get_order", "check_after_sales_eligibility",
             "create_exchange_request"),
      final={"case": "completed"}, confirm=True,
      phenomena=(PROG, VTIME),
      scoring=("clarification_triggered", "multi_turn_state_merged", "final_state"),
      notes="源自 V1 multi_exchange_order_001（V1 的失败案例之一）。"
            "V1 靠写死三轮台词，2.0 靠 unknown_info 让追问真实发生")

    c("v2_lang_progressive_intent_change_001", "multi_turn_recovery", "regression", "medium",
      "多轮中途改口：屏幕会闪想换货 → 算了不想用这型号了，退款 → 订单号 2361",
      order="ORDER-2361", status="delivered", amount="299.00", delivered_days_ago=3,
      known={}, unknown=("order_id",),
      intent="refund", policy="POL-REFUND-01",
      tools=("ask_for_info", "get_order", "request_refund"),
      final={"refund": "completed"}, confirm=True,
      phenomena=(PROG, EVOL),
      scoring=("latest_intent_wins", "multi_turn_state_merged", "final_state"),
      notes="源自 V1 multi_correct_action_001。跨轮改口 + 渐进补全叠加")

    c("v2_lang_progressive_resume_001", "multi_turn_recovery", "regression", "medium",
      "跨会话恢复：我刚才那个售后到哪了（不记得案件号）",
      order="ORDER-2362", status="delivered", amount="349.00", delivered_days_ago=5,
      known={}, unknown=("case_id", "order_id"),
      intent="query", policy="POL-QUERY-01",
      tools=("ask_for_info", "get_case", "get_operation_status"),
      final={"case": "processing"},
      phenomena=(PROG, PRON, VTIME),
      scoring=("session_resumed", "no_duplicate_case"),
      notes="必须按 session+goal 恢复既有 Case，不能新建")

    c("v2_lang_progressive_withdraw_001", "multi_turn_recovery", "regression", "medium",
      "多轮后撤销：要取消 → 等等我再想想，先别取消",
      order="ORDER-2363", status="paid", amount="178.00",
      intent="query", policy="POL-QUERY-01",
      tools=("get_order",), final={"order": "paid"}, no_side_effect=True,
      phenomena=(PROG, EVOL, NEGF),
      scoring=("latest_intent_wins", "no_side_effect"),
      notes="改口撤销后不得执行取消。已经执行了就是严重缺陷")

    # ═══ holdout（4 条，全部锁定）════════════════════════════════════════
    c("v2_lang_ho_conditional_001", "blended_intent", "holdout", "medium",
      "条件式变体：要是还在仓库就退了吧，出库了就算了",
      order="ORDER-2370", status="paid", amount="126.00",
      intent="cancel", policy="POL-CANCEL-01",
      tools=("get_order", "cancel_order"), final={"order": "cancelled"}, confirm=True,
      phenomena=(COND, DIAL), scoring=("conditional_evaluated_before_action", "final_state"))

    c("v2_lang_ho_exclusion_001", "implicit_intent", "holdout", "medium",
      "排除法变体：不用给我退钱，也不用修，就换个好的",
      order="ORDER-2371", status="delivered", amount="215.00", delivered_days_ago=11,
      intent="exchange", policy="POL-EXCHANGE-01",
      tools=("get_order", "check_after_sales_eligibility", "create_exchange_request"),
      final={"case": "completed"}, confirm=True,
      phenomena=(EXCL,), scoring=("exclusion_parsed_correctly", "policy_routing_correct"))

    c("v2_lang_ho_noisy_multitopic_001", "noisy_context", "holdout", "low",
      "多话题混杂：问会员积分、抱怨客服态度、最后问物流",
      order="ORDER-2372", status="shipped", shipment="in_transit",
      unknown=("tracking_no",),
      intent="query", policy="POL-SHIPMENT-01",
      tools=("get_order", "get_shipment"), final={"order": "shipped"},
      phenomena=(BG, MULTI),
      scoring=("signal_extracted_from_noise", "no_unfounded_promise"),
      notes="积分和客服态度超出售后范围，应说明边界而非编造答案")

    c("v2_lang_ho_double_negation_001", "correction_negation", "holdout", "medium",
      "双重否定变体：不是说不能用，只是跟描述不太一样，想退",
      order="ORDER-2373", status="delivered", amount="238.00", delivered_days_ago=5,
      intent="refund", policy="POL-REFUND-01",
      tools=("get_order", "request_refund"), final={"refund": "completed"}, confirm=True,
      phenomena=(DNEG, IMPL), scoring=("negation_parsed_correctly", "final_state"))
