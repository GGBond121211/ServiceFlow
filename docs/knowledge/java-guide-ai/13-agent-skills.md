# 13｜Agent Skills

来源：[JavaGuide 原文](https://javaguide.cn/ai/agent/skills.html)

## Skill 是什么

Skill 是可发现、按需加载的任务流程和知识，不是工具本身。Prompt 负责表达任务，Function Calling 负责提出动作，MCP 负责连接外部能力，Skill 负责把反复使用的 SOP、约束、检查和失败处理固化下来。一个 Skill 可以调用工具，也可以只提供分析流程。

典型 Skill 目录以 `SKILL.md` 为入口：元数据描述名称和触发场景，正文说明流程、限制、输入输出、失败和验证，scripts/references/assets 作为按需资源。名称应短、稳定、可发现；description 同时写用途、触发条件和关键词；详细资料不要全部塞入常驻上下文。

## 渐进式披露与风险

文章强调三层披露：metadata → SKILL.md 正文 → scripts/references/assets。引用资源应按需要加载，避免深层引用、重复说明和不一致术语。风险越高，执行自由度越低：分析任务可以开放，模板化修改需要固定检查，迁移、发布、删除和数据写操作要有白名单和人工确认。

Skill 的工作流应写成可验收的“执行 → 验证 → 修复 → 再验证”，而非“注意质量”。TDD 示例的价值在于先用真实失败证明测试红，再做最小实现变绿，最后重构；验证清单必须有可观察命令或状态。确定性文件转换应由脚本承担，缺少输入要明确报错，不能静默生成空文件。

Skill 路由大致可看成召回、重排、最终决策；示例和参考文档可以另建索引。并非所有运行环境支持相同的 frontmatter、自动发现或加载规则，落地前要核对宿主能力。

## 对 009 的落点

当前项目已有治理文档和学习状态文件，但它们不是自动 Agent Skill。若 2.0 后出现重复的“评测回放”“售后状态排查”或“知识库更新”流程，再把经过验证的步骤整理成局部 Skill；本目录的外部文章笔记是知识资料，不应被当作可执行指令自动运行。

## 关键词

Skill、SKILL.md、metadata、Progressive Disclosure、SOP、TDD、Verification、脚本、路由、权限。
