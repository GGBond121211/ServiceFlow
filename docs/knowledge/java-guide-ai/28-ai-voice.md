# 28｜AI 语音技术

来源：[JavaGuide 原文](https://javaguide.cn/ai/system-design/ai-voice.html)

## 语音链路

实时语音 Agent 不是简单的 ASR → LLM → TTS 三段调用，而是音频采集/前处理 → VAD → 流式 ASR → 上下文/LLM/工具 → 流式 TTS → 播放队列 → 状态回写的实时协作系统。它同时受到首段延迟、端点检测、增量文本、打断、噪声、回声、网络和会话状态约束。

ASR 可选云 API、开源通用模型或领域模型；实时产品要看首字延迟、增量结果稳定性、端点准确率、噪声和热词，不只看离线 WER。TTS 要看音质、首包、数字/英文/代码读法、情绪控制和流式能力。VAD 只检测语音活动，不知道声音来自用户、旁人、音乐还是回声；AEC/NS/AGC、播放参考、说话人分离和目标说话人检测可能需要配合。

## 状态与实现

浏览器可以用 `getUserMedia` 采集、AEC/NS/AGC 预处理，AudioWorklet 分块转 PCM，WebSocket 上传；这不是 WebRTC 的 RTP/SRTP 传输。播放端可直接使用 Audio 元素，也可自己管理 AudioContext 的音频队列、顺序、取消和 `audio_complete`。浏览器 AudioContext 常需用户交互后 resume。

会话要区分 listening、thinking、speaking、paused、completed 等状态，控制消息要独立表示 submit/cancel/pause。ASR 的 `isFinal` 只表示转写事件稳定，不等于业务提交。服务端连接需等待真实 ready 事件再开放音频上行；TTS 句子级并行时要限制单会话并发、超时、顺序和整轮结束。

## 打断与实时性

Barge-in 需要同时完成播放层清空、LLM/TTS 取消、上下文记录已播放/未播放和新一轮理解。AI 说话时“静默丢弃”麦克风可避免自回声，但也会丢掉用户插话；更精细方案是继续采音、在 AEC 后做 VAD、判断真实插话，再取消后端生成。工具调用中的打断还要区分可取消查询和已有副作用的幂等/补偿/人工状态。

端到端延迟要拆音频帧/网络块、VAD 静音等待、ASR、LLM、TTS 和播放缓冲，重点观察 P95/P99。优化包括较小上行分块、稳定 ASR 前缀预判、短确认语、按句子边界 TTS、控制上下文和全链路成本/取消/打断观测。帧长与网络分块不是同一个参数。

## 级联与 Realtime

级联 ASR+LLM+TTS 中间过程透明、文本可审计、组件可替换，适合合规和已有 Agent 框架；代价是每层延迟、ASR 错误传导和跨组件取消。原生 Speech-to-Speech/Realtime 可能更低延迟、更自然，连接还可支持 WebRTC/WebSocket/SIP，但中间过程更黑盒、成本和审计方式需单独设计。选型依据是实时性、自然度、私有化、数据边界、供应商依赖、成本和可观测。

## 对 009 的落点

当前 ServiceFlow 没有语音需求。语音内容属于 2.0 之外的独立候选，不应因为截图包含此文就扩展范围。若未来明确要做语音售后，优先复用已有业务策略和工具安全边界，先做级联小闭环，再依据真实延迟/打断数据评估 Realtime；不要把文章里的模型名、阈值或前端代码当作当前项目实现。

## 关键词

ASR、TTS、VAD、AEC/NS/AGC、AudioWorklet、WebSocket/WebRTC、Barge-in、播放队列、取消、Realtime、级联、端云协同。
