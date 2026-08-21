# ServiceFlow 学习可视化

这是一个独立、只读、可整体删除的教学辅助页面，把 ServiceFlow 的 3 天后端学习计划和真实函数调用链放在同一张可操作地图里。

## 学习计划来源

权威计划文件：

```text
C:\Users\Alex\Desktop\workspace\Project-0009-ServiceFlow\.hermes\plans\2026-08-19_145615-serviceflow-backend-interview-learning.md
```

页面顶部把计划整理为 3 天、6 个单元：

1. HTTP 契约和 API 输入输出；
2. API 组装和 Agent 图骨架；
3. 业务词汇和确定性政策；
4. 业务执行和数据库持久化；
5. Prompt、结构化意图和 AgentState；
6. LangGraph 节点、审批恢复和故障排查。

点击单元会跳到对应图和真实函数节点。

## 三张函数图

### 1. 一次请求主链

从浏览器 `sendMessage()` 开始，经 `request()`、FastAPI `send_conversation_message()`、LangGraph 节点、最终状态读取和 `_conversation_response()`，最后回到前端 `renderResponse()`。

### 2. 确定性业务写入

放大 `evaluate_policy()` 到 `CaseService.request_refund()`、Repository、`await AsyncSession.commit()` 和重新读取数据库终态的路径。旁支同时显示取消、审批和工单入口。

当前实验分支的教学图按异步运行时展示：图调用使用 `ainvoke()` / `aget_state()`，数据库使用 `AsyncSession`；纯政策判断仍是同步函数。

### 3. 高金额审批中断 / 恢复

展示 `create_approval()`、`interrupt()`、前端审批、`Command(resume=...)`、`wait_for_approval()` 恢复、`decide_approval()` 和再次读取终态的完整时序。

## 交互

- 点击节点查看函数完整绝对路径、内部调用、输入、输出和失败分支；
- “上一步 / 当前 / 下一步”区域可以直接在相邻函数间跳转；
- 支持重新开始、上一步、下一步、播放和暂停；
- 当前节点、已经过节点、连线、进度和教学数据包同步更新；
- 教学数据包是根据真实代码构造的最小示例，不是真实运行日志。

## 运行

可以直接打开 `index.html`，也可以启动本地静态服务器：

```powershell
cd C:\Users\Alex\Desktop\workspace\Project-0009-ServiceFlow\learning_visualizer
python -m http.server 4173 --bind 127.0.0.1
```

浏览器打开：

```text
http://127.0.0.1:4173/
```

## 边界

- 不调用 ServiceFlow API；
- 不调用模型或数据库；
- 不修改或导入 `backend/`、`frontend/` 业务源码；
- 不保存 API Key、真实客户数据或模型隐藏推理；
- 只使用 HTML、CSS、Vanilla JavaScript、DOM 和 SVG；
- 学习结束后可以整体删除 `learning_visualizer` 目录。
