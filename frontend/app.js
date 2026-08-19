const API_BASE = "http://127.0.0.1:8009/api/v1";

const state = {
  threadId: null,
  approvalId: null,
  messages: [],
};

function $(id) {
  return document.getElementById(id);
}

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
  };
  if (options.headers) {
    Object.assign(headers, options.headers);
  }

  const requestOptions = Object.assign({}, options);
  requestOptions.headers = headers;

  const response = await fetch(`${API_BASE}${path}`, requestOptions);
  if (!response.ok) {
    const detail = await response.text();
    let message = detail;
    if (!message) {
      message = "请求失败";
    }
    throw new Error(`${response.status}: ${message}`);
  }
  return response.json();
}

async function startConversation() {
  setError("");
  const userId = $("user-select").value;
  const conversation = await request("/conversations", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
  state.threadId = conversation.thread_id;
  state.approvalId = null;
  state.messages = [];
  $("thread-id").textContent = state.threadId;
  $("connection-status").textContent = "API 已连接";
  renderConversation();
  renderResponse({
    decision: null,
    policy_id: null,
    tool_events: [],
    final_business_state: {},
    approval: null,
  });
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("message-input");
  const message = input.value.trim();
  if (!message) {
    return;
  }
  if (!state.threadId) {
    return;
  }

  input.value = "";
  state.messages.push({ role: "user", text: message });
  renderConversation();
  setBusy(true);
  try {
    const response = await request(`/conversations/${state.threadId}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    renderResponse(response);
  } catch (error) {
    setError(error.message);
  } finally {
    setBusy(false);
  }
}

async function decideApproval(approved) {
  if (!state.threadId) {
    return;
  }
  if (!state.approvalId) {
    return;
  }

  setBusy(true);
  try {
    const response = await request(
      `/conversations/${state.threadId}/approvals/${state.approvalId}`,
      {
        method: "POST",
        body: JSON.stringify({ approved }),
      },
    );
    renderResponse(response);
  } catch (error) {
    setError(error.message);
  } finally {
    setBusy(false);
  }
}

function renderResponse(response) {
  if (response.assistant_message) {
    state.messages.push({ role: "assistant", text: response.assistant_message });
    renderConversation();
  }

  let finalState = response.final_business_state;
  if (!finalState) {
    finalState = {};
  }

  let caseStatus = finalState.refund_status;
  if (!caseStatus) {
    caseStatus = finalState.ticket_status;
  }

  $("decision-value").textContent = formatValue(response.decision);
  $("policy-value").textContent = formatValue(response.policy_id);
  $("order-status-value").textContent = formatValue(finalState.order_status);
  $("case-status-value").textContent = formatValue(caseStatus);
  $("approval-status-value").textContent = formatValue(finalState.approval_status);

  state.approvalId = null;
  if (response.approval && response.approval.id) {
    state.approvalId = response.approval.id;
  }

  let pending = false;
  if (response.approval && response.approval.status === "pending") {
    pending = true;
  }
  $("approval-actions").hidden = !pending;
  $("approve-button").disabled = !pending;
  $("reject-button").disabled = !pending;
  let toolEvents = response.tool_events;
  if (!toolEvents) {
    toolEvents = [];
  }
  renderTimeline(toolEvents);
}

function renderConversation() {
  const container = $("conversation");
  if (state.messages.length === 0) {
    container.innerHTML =
      '<div class="empty-state"><span class="empty-mark">SF</span><p>选择一个案例，或直接描述你的售后问题。</p></div>';
    return;
  }

  const renderedMessages = [];
  for (const message of state.messages) {
    let label = "ServiceFlow";
    if (message.role === "user") {
      label = "用户";
    }
    renderedMessages.push(`
    <div class="message ${message.role}">
      <span class="message-label">${label}</span>
      <p>${escapeHtml(message.text)}</p>
    </div>`);
  }
  container.innerHTML = renderedMessages.join("");
  container.scrollTop = container.scrollHeight;
}

function renderTimeline(events) {
  const timeline = $("tool-timeline");
  if (events.length === 0) {
    timeline.innerHTML = '<p class="muted">尚无工具事件</p>';
    return;
  }

  const renderedEvents = [];
  let index = 0;
  for (const event of events) {
    index += 1;
    let statusClass = "failed";
    if (event.ok) {
      statusClass = "ok";
    }
    let code = event.code;
    if (!code) {
      code = "完成";
    }
    renderedEvents.push(`
    <div class="timeline-event">
      <span class="timeline-line ${statusClass}"></span>
      <div><strong>${index}. ${escapeHtml(event.tool)}</strong><small>${escapeHtml(code)}</small></div>
    </div>`);
  }
  timeline.innerHTML = renderedEvents.join("");
}

function setBusy(busy) {
  $("send-button").disabled = busy;
  $("approve-button").disabled = busy;
  $("reject-button").disabled = busy;
  $("message-input").disabled = busy;
}

function setError(message) {
  const element = $("error-message");
  element.textContent = message;
  element.hidden = !message;
  if (message) {
    $("connection-status").textContent = "API 未连接";
  }
}

function formatValue(value) {
  if (value === undefined || value === null || value === "") {
    return "—";
  }
  return String(value).replaceAll("_", " ");
}

function escapeHtml(value) {
  const replacements = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  };

  function replaceCharacter(character) {
    return replacements[character];
  }

  return String(value).replace(/[&<>"']/g, replaceCharacter);
}

function handleRequestError(error) {
  setError(error.message);
}

function handleNewConversation() {
  startConversation().catch(handleRequestError);
}

function handleUserChange() {
  startConversation().catch(handleRequestError);
}

function approveRefund() {
  decideApproval(true);
}

function rejectRefund() {
  decideApproval(false);
}

function fillExample(event) {
  const button = event.currentTarget;
  let orderId = button.dataset.order;
  if (!orderId) {
    orderId = "";
  }
  let message = button.dataset.message;
  if (!message) {
    message = "";
  }
  $("order-select").value = orderId;
  $("message-input").value = message;
  $("message-input").focus();
}

function initializePage() {
  $("message-form").addEventListener("submit", sendMessage);
  $("new-conversation").addEventListener("click", handleNewConversation);
  $("user-select").addEventListener("change", handleUserChange);
  $("approve-button").addEventListener("click", approveRefund);
  $("reject-button").addEventListener("click", rejectRefund);

  const exampleButtons = document.querySelectorAll(".example-button");
  for (const button of exampleButtons) {
    button.addEventListener("click", fillExample);
  }

  startConversation().catch(handleRequestError);
}

document.addEventListener("DOMContentLoaded", initializePage);
