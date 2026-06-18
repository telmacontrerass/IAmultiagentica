const state = {
  models: [],
  installed: [],
  currentSession: null,
  chatMessages: [],
  uploadedFiles: [],
  activeView: "homeView",
  pullTasks: {},
  pullPolls: {},
  deleteTasks: {},
  deletePolls: {},
  tokenUsage: null,
  agentsMode: false,
};

const STORAGE_KEY = "ci2lab.ui.state.v1";

const MODEL_SEARCH_SYNONYMS = {
  coding: ["code", "coder", "program", "programming", "python", "javascript", "development", "software", "debug", "debugging"],
  reasoning: ["reason", "reasoning", "math", "mathematics", "logic", "problems", "think", "analysis", "analyze"],
  general: ["general", "chat", "conversation", "questions", "text", "summary", "summarize", "documents", "pdf", "study", "help"],
  edge: ["fast", "lightweight", "small", "low ram", "local", "laptop", "portable", "edge"],
  workstation: ["powerful", "work", "workstation", "quality", "medium"],
  enterprise: ["large", "maximum", "company", "enterprise", "server"],
};

const els = {
  views: document.querySelectorAll(".view"),
  navButtons: document.querySelectorAll(".nav-button"),
  ollamaStatus: document.querySelector("#ollamaStatus"),
  workspaceLabel: document.querySelector("#workspaceLabel"),
  modelSelect: document.querySelector("#modelSelect"),
  modelSearch: document.querySelector("#modelSearch"),
  modelsList: document.querySelector("#modelsList"),
  sessionsList: document.querySelector("#sessionsList"),
  messages: document.querySelector("#messages"),
  fileInput: document.querySelector("#fileInput"),
  attachmentsList: document.querySelector("#attachmentsList"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  commandPreview: document.querySelector("#commandPreview"),
  chatTools: document.querySelector(".chat-tools"),
  agentsMode: document.querySelector("#agentsMode"),
  agentsModeLabel: document.querySelector("#agentsModeLabel"),
  toolsSummary: document.querySelector("#toolsSummary"),
  quickActions: document.querySelector("#quickActions"),
  toolsList: document.querySelector("#toolsList"),
  refreshButton: document.querySelector("#refreshButton"),
  chatRefreshButton: document.querySelector("#chatRefreshButton"),
  tokenCounter: document.querySelector("#tokenCounter"),
  tokenTurnValue: document.querySelector("#tokenTurnValue"),
  tokenSessionValue: document.querySelector("#tokenSessionValue"),
  tokenInfoTitle: document.querySelector("#tokenInfoTitle"),
  tokenInfoInput: document.querySelector("#tokenInfoInput"),
  tokenInfoOutput: document.querySelector("#tokenInfoOutput"),
  tokenInfoTurn: document.querySelector("#tokenInfoTurn"),
  tokenInfoSession: document.querySelector("#tokenInfoSession"),
  tokenInfoFormula: document.querySelector("#tokenInfoFormula"),
  tokenInfoModel: document.querySelector("#tokenInfoModel"),
  tokenInfoFamily: document.querySelector("#tokenInfoFamily"),
  tokenInfoContext: document.querySelector("#tokenInfoContext"),
  tokenInfoToolMode: document.querySelector("#tokenInfoToolMode"),
  backToChatFromTokens: document.querySelector("#backToChatFromTokens"),
  openChat: document.querySelector("#openChat"),
  newChat: document.querySelector("#newChat"),
  systemSummary: document.querySelector("#systemSummary"),
  ramValue: document.querySelector("#ramValue"),
  ramBar: document.querySelector("#ramBar"),
  ramMeta: document.querySelector("#ramMeta"),
  diskValue: document.querySelector("#diskValue"),
  diskBar: document.querySelector("#diskBar"),
  diskMeta: document.querySelector("#diskMeta"),
  budgetValue: document.querySelector("#budgetValue"),
  budgetBar: document.querySelector("#budgetBar"),
  budgetMeta: document.querySelector("#budgetMeta"),
  modeValue: document.querySelector("#modeValue"),
  modeMeta: document.querySelector("#modeMeta"),
  recommendationsStrip: document.querySelector("#recommendationsStrip"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return response.json();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(value) {
  if (!value || value === "?") return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 19);
  return new Intl.DateTimeFormat("en", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatGb(value) {
  const number = Number(value || 0);
  return `${number.toFixed(number >= 10 ? 0 : 1)} GB`;
}

function formatBytes(value) {
  const number = Number(value || 0);
  if (number <= 0) return "0 MB";
  const gb = number / 1024 / 1024 / 1024;
  if (gb >= 1) return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`;
  return `${(number / 1024 / 1024).toFixed(0)} MB`;
}

function emptyTokenUsage() {
  return {
    last_call: null,
    last_turn: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      model: "",
      available: false,
    },
    session_total: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      model: "",
      available: false,
    },
    calls: [],
  };
}

function normalizeTokenUsage(usage) {
  const base = emptyTokenUsage();
  if (!usage || typeof usage !== "object") return base;
  const normalize = (part) => ({
    ...base.last_turn,
    ...(part && typeof part === "object" ? part : {}),
    prompt_tokens: Number(part?.prompt_tokens || 0),
    completion_tokens: Number(part?.completion_tokens || 0),
    total_tokens: Number(part?.total_tokens || 0),
    available: Boolean(part?.available) || Number(part?.total_tokens || 0) > 0,
  });
  return {
    last_call: usage.last_call ? normalize(usage.last_call) : null,
    last_turn: normalize(usage.last_turn),
    session_total: normalize(usage.session_total),
    calls: Array.isArray(usage.calls) ? usage.calls.map(normalize) : [],
  };
}

function formatTokenCompact(value) {
  const number = Number(value || 0);
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(number);
}

function formatTokenExact(value) {
  return new Intl.NumberFormat("en").format(Number(value || 0));
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value || 0)));
}

function setMeter(node, percent) {
  node.style.width = `${clampPercent(percent)}%`;
}

function persistUiState() {
  const payload = {
    currentSession: state.currentSession,
    chatMessages: state.chatMessages,
    uploadedFiles: state.uploadedFiles,
    activeView: state.activeView,
    tokenUsage: state.tokenUsage,
    agentsMode: Boolean(els.agentsMode?.checked),
    selectedModel: els.modelSelect?.value || "",
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function restoreUiState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const payload = JSON.parse(raw);
    state.currentSession = payload.currentSession || null;
    state.chatMessages = Array.isArray(payload.chatMessages) ? payload.chatMessages : [];
    state.uploadedFiles = Array.isArray(payload.uploadedFiles) ? payload.uploadedFiles : [];
    state.tokenUsage = normalizeTokenUsage(payload.tokenUsage);
    state.agentsMode = Boolean(payload.agentsMode);
    state.activeView = "homeView";
    if (payload.selectedModel) {
      els.modelSelect.dataset.pendingValue = payload.selectedModel;
    }
  } catch {
    state.currentSession = null;
    state.chatMessages = [];
    state.uploadedFiles = [];
    state.tokenUsage = emptyTokenUsage();
    state.agentsMode = false;
    state.activeView = "homeView";
  }
}

function switchView(viewId, scrollTarget = null) {
  state.activeView = viewId;
  document.body.classList.toggle("chat-view-active", viewId === "chatView");
  document.body.classList.toggle("token-info-view-active", viewId === "tokenInfoView");
  els.views.forEach((view) => {
    const active = view.id === viewId;
    view.hidden = !active;
    view.classList.toggle("active-view", active);
  });

  els.navButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId && !button.dataset.scroll);
  });

  if (scrollTarget) {
    persistUiState();
    window.setTimeout(() => {
      document.getElementById(scrollTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 40);
    return;
  }
  persistUiState();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function currentModelInfo() {
  const selected = els.modelSelect?.value || "";
  return state.models.find((model) => (
    model.id === selected || model.ollama_tag === selected
  )) || null;
}

function applyTokenUsage(usage) {
  state.tokenUsage = normalizeTokenUsage(usage);
  updateTokenDisplay();
  renderTokenInfo();
  persistUiState();
}

function updateTokenDisplay() {
  const usage = normalizeTokenUsage(state.tokenUsage);
  state.tokenUsage = usage;
  const turn = usage.last_turn;
  const session = usage.session_total;
  if (els.tokenTurnValue) {
    setRollingText(els.tokenTurnValue, `Turn ${formatTokenCompact(turn.total_tokens)}`);
  }
  if (els.tokenSessionValue) {
    setRollingText(els.tokenSessionValue, `Conversation ${formatTokenCompact(session.total_tokens)}`);
  }
}

function setRollingText(node, value) {
  if (!node || node.textContent === value) return;
  node.textContent = value;
  node.classList.remove("token-roll");
  void node.offsetWidth;
  node.classList.add("token-roll");
}

function renderTokenInfo() {
  if (!els.tokenInfoTitle) return;
  const usage = normalizeTokenUsage(state.tokenUsage);
  const turn = usage.last_turn;
  const session = usage.session_total;
  const model = currentModelInfo();
  const modelName = model?.display_name || usage.session_total.model || els.modelSelect?.value || "Local model";
  els.tokenInfoTitle.textContent = `Tokens for ${modelName}`;
  els.tokenInfoInput.textContent = formatTokenExact(turn.prompt_tokens);
  els.tokenInfoOutput.textContent = formatTokenExact(turn.completion_tokens);
  els.tokenInfoTurn.textContent = formatTokenExact(turn.total_tokens);
  els.tokenInfoSession.textContent = formatTokenExact(session.total_tokens);
  els.tokenInfoFormula.textContent = turn.available
    ? `Last turn total = ${formatTokenExact(turn.prompt_tokens)} input + ${formatTokenExact(turn.completion_tokens)} output = ${formatTokenExact(turn.total_tokens)} tokens.`
    : "No token data for this turn yet. It will appear after the model's next response if Ollama returns it.";
  els.tokenInfoModel.textContent = model
    ? `${model.display_name} (${model.ollama_tag})`
    : (usage.session_total.model || els.modelSelect?.value || "--");
  els.tokenInfoFamily.textContent = model?.family || "--";
  els.tokenInfoContext.textContent = model?.context_length
    ? `${formatTokenExact(model.context_length)} tokens`
    : "--";
  els.tokenInfoToolMode.textContent = model?.tool_mode || "--";
}

function renderChatMessages() {
  els.messages.innerHTML = "";
  if (!state.chatMessages.length) {
    setEmptyChat();
    return;
  }
  state.chatMessages.forEach((message) => {
    appendMessageNode(
      message.role,
      message.text,
      message.extraClass || "",
      { duration_ms: message.duration_ms },
    );
  });
}

function appendMessageNode(role, text, extraClass = "", meta = {}) {
  const empty = els.messages.querySelector(".empty-state");
  if (empty) empty.remove();
  const node = document.createElement("div");
  node.className = `message ${role} ${extraClass}`.trim();
  const body = document.createElement("div");
  body.textContent = text;
  node.appendChild(body);
  if (meta.duration_ms) {
    const detail = document.createElement("small");
    detail.className = "message-meta";
    detail.textContent = `Answered in ${formatElapsed(meta.duration_ms)}`;
    node.appendChild(detail);
  }
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
  return node;
}

function addMessage(role, text, extraClass = "", meta = {}) {
  state.chatMessages.push({ role, text, extraClass, ...meta });
  appendMessageNode(role, text, extraClass, meta);
  persistUiState();
}

function buildProgressMessages(prompt = "", files = []) {
  const text = `${prompt} ${files.map((file) => file.name || file.path || "").join(" ")}`.toLowerCase();
  const messages = ["Deciding the next step..."];
  if (files.length) {
    messages.push("Reading the attached files...");
  }
  if (/\bpdf\b|\.pdf\b/.test(text)) {
    messages.push("Extracting information from the PDF...");
  } else if (/\bdocx?\b|\.docx?\b|document|file/.test(text)) {
    messages.push("Reading the document...");
  }
  if (/\b(code|test|bug|fix|implement|generate|generating|create|write)\b/.test(text)) {
    messages.push("Planning the code change...");
    messages.push("Generating code changes...");
  }
  if (/web|internet|latest|current|today|online/.test(text)) {
    messages.push("Looking up current information...");
  }
  messages.push("Checking the result...");
  messages.push("Preparing the answer...");
  return [...new Set(messages)];
}

function addThinkingMessage(prompt = "", files = []) {
  const empty = els.messages.querySelector(".empty-state");
  if (empty) empty.remove();
  const node = document.createElement("div");
  node.className = "message assistant thinking";
  const startedAt = Date.now();
  const progressMessages = buildProgressMessages(prompt, files);
  node.innerHTML = `
    <span class="thinking-loader" aria-hidden="true"></span>
    <span class="thinking-copy">
      <span class="thinking-status">${escapeHtml(progressMessages[0])}</span>
      <small class="thinking-time">0.0s</small>
    </span>
  `;
  const status = node.querySelector(".thinking-status");
  const timer = node.querySelector(".thinking-time");
  node._startedAt = startedAt;
  node._progressIndex = 0;
  node._timerId = window.setInterval(() => {
    if (timer) timer.textContent = formatElapsed(Date.now() - startedAt);
  }, 100);
  node._progressTimerId = window.setInterval(() => {
    if (!status || progressMessages.length <= 1) return;
    node._progressIndex = Math.min(node._progressIndex + 1, progressMessages.length - 1);
    status.textContent = progressMessages[node._progressIndex];
  }, 3500);
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
  return node;
}

function removeThinkingMessage(node) {
  if (node?._timerId) {
    window.clearInterval(node._timerId);
  }
  if (node?._progressTimerId) {
    window.clearInterval(node._progressTimerId);
  }
  if (node && node.parentNode) {
    node.remove();
  }
}

function formatElapsed(ms) {
  return `${(Math.max(0, ms) / 1000).toFixed(1)}s`;
}

function setEmptyChat() {
  els.messages.innerHTML = `
    <div class="empty-state">
      <div>
        <p class="eyebrow">Florentino local</p>
        <h3>Start a conversation</h3>
        <p>Try: "summarize this project" or "list the Python files".</p>
      </div>
    </div>
  `;
}

function buildSessionInfoMessage(payload) {
  const warnings = Array.isArray(payload.warnings) && payload.warnings.length
    ? `\nWarning: ${payload.warnings.join(" ")}`
    : "";
  return [
    "ci2lab UI",
    `Model: ${payload.model || payload.display_name || "?"}`,
    `Tool mode: ${payload.tool_mode || "?"}`,
    `CWD: ${payload.cwd || "?"}`,
    `Sesion: ${payload.session_id || "?"}`,
    `Modo: ${payload.multi_agent ? "agentes" : "chat clasico"}`,
    `Seguridad: ${payload.security_profile || "standard"} / ${payload.security_engine || "ci2lab"}`,
    "",
    "Ready. Type your request or attach files.",
  ].join("\n") + warnings;
}

async function startChatSession({ forceNew = false } = {}) {
  if (!forceNew && state.currentSession && state.chatMessages.length) return;
  setEmptyChat();
  const result = await api("/api/chat/start", {
    method: "POST",
    body: JSON.stringify({
      model: els.modelSelect.value,
      multi_agent: Boolean(els.agentsMode?.checked),
    }),
  });
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not start the local chat.", "error");
    return;
  }

  state.currentSession = result.session_id;
  state.chatMessages = [];
  applyTokenUsage(result.usage);
  addMessage("assistant", buildSessionInfoMessage(result), "session-info");
}

function updateCommandPreview() {
  const model = els.modelSelect.value || "<model>";
  if (els.commandPreview) {
    const agentsFlag = els.agentsMode?.checked ? " --multi-agent" : "";
    els.commandPreview.textContent = `ci2lab --model ${model}${agentsFlag} chat`;
  }
}

function updateAgentsModeState({ persist = true } = {}) {
  const active = Boolean(els.agentsMode?.checked);
  els.chatTools?.classList.toggle("agents-active", active);
  if (els.agentsModeLabel) {
    els.agentsModeLabel.textContent = active ? "Modo agentes activo" : "Modo agentes";
  }
  updateCommandPreview();
  if (persist) persistUiState();
}

function renderAttachments() {
  if (!els.attachmentsList) return;
  if (!state.uploadedFiles.length) {
    els.attachmentsList.innerHTML = `<span class="attachment-empty">Local PDF or text</span>`;
    return;
  }
  els.attachmentsList.innerHTML = state.uploadedFiles.map((file) => `
    <span class="attachment-chip">
      <span>${escapeHtml(file.name)}</span>
      <small>${escapeHtml(file.size_label || "")}</small>
      <button type="button" data-remove-attachment="${escapeHtml(file.path)}" title="Remove file">×</button>
    </span>
  `).join("");
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}

async function uploadSelectedFiles(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  els.fileInput.disabled = true;
  for (const file of files) {
    try {
      const content = await readFileAsDataUrl(file);
      const result = await api("/api/files/upload", {
        method: "POST",
        body: JSON.stringify({
          name: file.name,
          size: file.size,
          content_base64: content,
        }),
      });
      if (result.ok && result.file) {
        state.uploadedFiles.push(result.file);
        renderAttachments();
        persistUiState();
      } else {
        addMessage("assistant", result.error || `Could not upload ${file.name}`, "error");
      }
    } catch (error) {
      addMessage("assistant", error.message || `Could not upload ${file.name}`, "error");
    }
  }
  els.fileInput.value = "";
  els.fileInput.disabled = false;
}

function removeAttachment(path) {
  state.uploadedFiles = state.uploadedFiles.filter((file) => file.path !== path);
  renderAttachments();
  persistUiState();
}

function buildDisplayMessage(message, files) {
  const base = message || "Read and summarize the attached files.";
  if (!files.length) return base;
  const list = files.map((file) => `- ${file.name}`).join("\n");
  return `${base}\n\nAttachments:\n${list}`;
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function searchTerms(query) {
  const normalized = normalizeSearchText(query).trim();
  if (!normalized) return [];
  const terms = new Set(normalized.split(/\s+/).filter(Boolean));
  Object.entries(MODEL_SEARCH_SYNONYMS).forEach(([category, synonyms]) => {
    const allWords = [category, ...synonyms].map(normalizeSearchText);
    if (allWords.some((word) => normalized.includes(word))) {
      terms.add(category);
      allWords.forEach((word) => terms.add(word));
    }
  });
  return [...terms];
}

function modelSearchHaystack(model) {
  const categories = model.categories || [];
  const synonymWords = categories.flatMap((category) => MODEL_SEARCH_SYNONYMS[category] || []);
  const benchmarkUses = Object.entries(model.benchmark_score || {})
    .filter(([, score]) => Number(score) >= 0.7)
    .map(([use]) => use);
  return normalizeSearchText([
    model.display_name,
    model.id,
    model.ollama_tag,
    model.family,
    model.tier,
    model.fit_label,
    ...categories,
    ...benchmarkUses,
    ...synonymWords,
  ].join(" "));
}

function orderedModels() {
  const installed = state.models.filter((model) => model.installed);
  const pending = state.models.filter((model) => !model.installed);
  return [...installed, ...pending];
}

function renderModelProgress(model) {
  const deleteTask = state.deleteTasks[model.ollama_tag];
  if (deleteTask) return renderTaskProgress(deleteTask, "delete");

  const task = state.pullTasks[model.ollama_tag];
  if (!task) return "";
  return renderTaskProgress(task, "pull");
}

function renderTaskProgress(task, type) {
  if (!task) return "";
  const percent = clampPercent(task.percent || 0);
  const visiblePercent = task.done ? percent : Math.max(percent, task.total ? 3 : 8);
  const status = task.error || task.status || (type === "delete" ? "Uninstalling" : "Downloading");
  const detail = type === "pull"
    ? (task.total ? `${formatBytes(task.completed)} of ${formatBytes(task.total)}` : "Calculating size...")
    : (task.done ? "Ollama updated" : "Removing local files...");
  const className = `${type} ${task.error ? "error" : task.done ? "done" : "active"}`;
  const busyLoader = !task.done && !task.error
    ? `<span class="tiny-loader" aria-hidden="true"></span>`
    : "";

  return `
    <div class="download-progress ${className}">
      <div class="progress-row">
        <span>${escapeHtml(status)}</span>
        <strong class="progress-value">${busyLoader}${percent.toFixed(0)}%</strong>
      </div>
      <div class="progress-bar"><i style="width: ${visiblePercent}%"></i></div>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
}

function renderModelActions(model) {
  const buttons = [
    `<button type="button" data-action="use" data-model="${escapeHtml(model.id)}">Use</button>`,
  ];
  if (model.installed) {
    buttons.push(
      `<button class="danger-button" type="button" data-action="delete" data-tag="${escapeHtml(model.ollama_tag)}">Delete</button>`,
    );
  } else {
    buttons.push(
      `<button type="button" data-action="pull" data-tag="${escapeHtml(model.ollama_tag)}">Download</button>`,
    );
  }
  return `<div class="model-actions">${buttons.join("")}</div>`;
}

function renderModels() {
  const terms = searchTerms(els.modelSearch.value);
  const models = orderedModels().filter((model) => {
    const haystack = modelSearchHaystack(model);
    return !terms.length || terms.some((term) => haystack.includes(term));
  });

  els.modelsList.innerHTML = models.map((model) => `
    <article class="model-card">
      <header>
        <div>
          <h4>${escapeHtml(model.display_name)}</h4>
          <div class="meta">${escapeHtml(model.id)} · ${escapeHtml(model.ollama_tag)}</div>
        </div>
        <span class="badge ${model.installed ? "ok" : ""}">${model.installed ? "Installed" : model.tier}</span>
      </header>
      <div class="meta">
        ${escapeHtml(model.categories.join(", "))} · RAM approx. ${model.ram_inference_gb} GB
        ${model.fit_label ? ` · ${escapeHtml(model.fit_label)}` : ""}
      </div>
      ${renderModelActions(model)}
      ${renderModelProgress(model)}
    </article>
  `).join("");
}

function renderModelSelect() {
  const current = els.modelSelect.dataset.pendingValue || els.modelSelect.value;
  const models = orderedModels();
  els.modelSelect.innerHTML = models.map((model) => `
    <option value="${escapeHtml(model.id)}">${escapeHtml(model.display_name)} ${model.installed ? "" : "(not installed)"}</option>
  `).join("");

  const currentModel = models.find((model) => model.id === current || model.ollama_tag === current);
  const firstInstalled = models.find((model) => model.installed);
  const fallback = firstInstalled || models[0];
  if (currentModel?.installed) {
    els.modelSelect.value = currentModel.id;
    delete els.modelSelect.dataset.pendingValue;
  } else if (fallback) {
    els.modelSelect.value = fallback.id;
    delete els.modelSelect.dataset.pendingValue;
  } else {
    delete els.modelSelect.dataset.pendingValue;
  }
  updateCommandPreview();
  persistUiState();
}

function renderSessions(sessions) {
  if (!sessions.length) {
    els.sessionsList.innerHTML = `<p class="meta">No saved sessions yet.</p>`;
    return;
  }
  els.sessionsList.innerHTML = sessions.map((session) => `
    <article class="session-card">
      <h4>${escapeHtml(session.title || "Conversation")}</h4>
      <div class="session-tag">Internal tag: <code>${escapeHtml(session.internal_tag || session.id)}</code></div>
      <div class="meta">${escapeHtml(session.model)} · ${escapeHtml(formatDate(session.updated_at))}</div>
      <div class="meta">${escapeHtml(session.cwd)}</div>
      <div class="session-actions">
        <button type="button" data-session="${escapeHtml(session.id)}">Resume</button>
        <button
          class="danger-button"
          type="button"
          data-delete-session="${escapeHtml(session.id)}"
          title="Delete saved conversation"
        >Delete</button>
      </div>
    </article>
  `).join("");
}

function renderSystem(payload) {
  if (!payload || !payload.ok || !payload.hardware) {
    els.systemSummary.textContent = payload?.error || "Could not read the hardware.";
    els.recommendationsStrip.innerHTML = "";
    return;
  }

  const hardware = payload.hardware;
  const disk = payload.disk || {};
  const ramFreePercent = hardware.ram_total_gb
    ? hardware.ram_available_gb / hardware.ram_total_gb * 100
    : 0;
  const budgetBase = hardware.inference_budget_theoretical_gb || hardware.inference_budget_gb || 0;
  const budgetPercent = budgetBase
    ? hardware.inference_budget_available_gb / budgetBase * 100
    : 0;

  els.systemSummary.textContent = hardware.memory_pressure
    ? "Memory is under pressure: closing apps may allow larger models."
    : "Your machine is ready for compatible local models.";

  els.ramValue.textContent = `${formatGb(hardware.ram_available_gb)} free`;
  els.ramMeta.textContent = `${formatGb(hardware.ram_total_gb)} total`;
  setMeter(els.ramBar, ramFreePercent);

  els.diskValue.textContent = `${formatGb(disk.free_gb)} free`;
  els.diskMeta.textContent = `${formatGb(disk.total_gb)} total in ${disk.path || "workspace"}`;
  setMeter(els.diskBar, disk.free_percent || 0);

  els.budgetValue.textContent = formatGb(hardware.inference_budget_available_gb || hardware.inference_budget_gb);
  els.budgetMeta.textContent = `Safe now · ceiling ${formatGb(budgetBase)}`;
  setMeter(els.budgetBar, budgetPercent);

  els.modeValue.textContent = hardware.inference_mode === "gpu" ? "GPU" : "CPU";
  els.modeMeta.textContent = `${hardware.gpu_name || "CPU only"} · ${hardware.cpu_cores} cores · ${hardware.hardware_tier}`;

  const recommendations = payload.recommendations || [];
  if (!recommendations.length) {
    els.recommendationsStrip.innerHTML = `<p class="meta">No recommendations available right now.</p>`;
    return;
  }
  els.recommendationsStrip.innerHTML = recommendations.map((item) => `
    <article class="recommendation-card">
      <div>
        <h4>${escapeHtml(item.display_name)}</h4>
        <p>${escapeHtml(item.fit_label)} · ${escapeHtml(item.ollama_tag)}</p>
      </div>
      <div class="mini-meter">
        <span>${escapeHtml(formatGb(item.memory_required_gb))}</span>
        <div class="meter"><i style="width: ${clampPercent(item.memory_usage_percent)}%"></i></div>
      </div>
    </article>
  `).join("");
}

function groupBy(items, key) {
  return items.reduce((groups, item) => {
    const value = item[key] || "Other";
    if (!groups[value]) groups[value] = [];
    groups[value].push(item);
    return groups;
  }, {});
}

function renderTools(payload) {
  state.toolCatalog = payload;
  if (!els.toolsSummary || !els.quickActions || !els.toolsList) return;
  if (!payload || !payload.ok) {
    els.toolsSummary.textContent = payload?.error || "Could not load the tools.";
    els.quickActions.innerHTML = "";
    els.toolsList.innerHTML = "";
    return;
  }

  const tools = payload.tools || [];
  const skills = payload.skills || [];
  const mcpServers = payload.mcp_servers || [];
  els.toolsSummary.textContent = `${tools.length} tools · ${skills.length} skills · ${mcpServers.length} MCP`;

  const actions = payload.actions || [];
  els.quickActions.innerHTML = actions.map((action) => `
    <button
      type="button"
      class="action-chip"
      data-action-prompt="${escapeHtml(action.prompt)}"
      title="${escapeHtml(action.tool)}"
    >
      <span>${escapeHtml(action.group)}</span>
      ${escapeHtml(action.label)}
    </button>
  `).join("");

  const grouped = groupBy(tools, "group");
  const groupNames = ["Explore", "Edit", "Git", "Planning", "Web", "Notebook", "Skills", "MCP", "System", "Other"]
    .filter((name) => grouped[name]?.length);
  const toolGroups = groupNames.map((group) => `
    <section class="tool-group">
      <h4>${escapeHtml(group)}</h4>
      <div class="tool-grid">
        ${grouped[group].map((tool) => `
          <article class="tool-card">
            <div>
              <strong>${escapeHtml(tool.name)}</strong>
              <p>${escapeHtml(tool.description)}</p>
            </div>
            <small>${escapeHtml(tool.web_status || "")}</small>
          </article>
        `).join("")}
      </div>
    </section>
  `).join("");

  const skillsHtml = skills.length ? `
    <section class="tool-group">
      <h4>Loaded skills</h4>
      <div class="tool-grid">
        ${skills.map((skill) => `
          <article class="tool-card compact">
            <strong>${escapeHtml(skill.name)}</strong>
            <p>${escapeHtml(skill.description)} · ${escapeHtml(skill.source)}</p>
          </article>
        `).join("")}
      </div>
    </section>
  ` : "";

  const mcpHtml = mcpServers.length ? `
    <section class="tool-group">
      <h4>Configured MCP servers</h4>
      <div class="tool-grid">
        ${mcpServers.map((server) => `
          <article class="tool-card compact">
            <strong>${escapeHtml(server.name)}</strong>
            <p>${escapeHtml(server.command)}</p>
          </article>
        `).join("")}
      </div>
    </section>
  ` : "";

  els.toolsList.innerHTML = toolGroups + skillsHtml + mcpHtml;
}

function applyActionPrompt(prompt) {
  const current = els.messageInput.value.trim();
  els.messageInput.value = current ? `${current}\n\n${prompt}` : prompt;
  switchView("chatView");
  window.setTimeout(() => {
    els.messageInput.focus();
    els.messageInput.selectionStart = els.messageInput.value.length;
    els.messageInput.selectionEnd = els.messageInput.value.length;
  }, 60);
}

function renderOllamaLocation(health) {
  const api = health.ollama_base_url || "Ollama API not configured";
  const executable = health.ollama_executable || "Executable not found in PATH";
  const modelsDir = health.ollama_models_dir || "Models folder not detected";
  return `
    <span><b>API</b>${escapeHtml(api)}</span>
    <span><b>App</b>${escapeHtml(executable)}</span>
    <span><b>Models</b>${escapeHtml(modelsDir)}</span>
  `;
}

async function refreshAll() {
  const health = await api("/api/health");
  els.ollamaStatus.textContent = health.ok ? `Ollama ready (${health.installed_count})` : "Ollama unavailable";
  els.workspaceLabel.innerHTML = renderOllamaLocation(health);

  const systemPayload = await api("/api/system");
  renderSystem(systemPayload);

  const modelsPayload = await api("/api/models");
  state.models = modelsPayload.catalog || [];
  state.installed = modelsPayload.installed || [];
  renderModelSelect();
  renderModels();
  renderTokenInfo();

  const sessions = await api("/api/sessions");
  renderSessions(sessions.sessions || []);

  const toolsPayload = await api("/api/tools");
  renderTools(toolsPayload);
}

async function runRefreshFromButton(button) {
  if (!button) return;
  const label = button.dataset.defaultLabel || button.textContent.trim() || "Refresh data";
  button.dataset.defaultLabel = label;
  button.disabled = true;
  button.innerHTML = `<span class="tiny-loader button-loader" aria-hidden="true"></span><span>Refreshing</span>`;
  try {
    await refreshAll();
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const message = els.messageInput.value.trim();
  const files = [...state.uploadedFiles];
  if (!message && !files.length) return;
  const model = els.modelSelect.value;
  const prompt = message || "Read and summarize the attached files.";
  const sessionId = state.currentSession;
  addMessage("user", buildDisplayMessage(message, files));
  els.messageInput.value = "";
  state.uploadedFiles = [];
  renderAttachments();
  els.sendButton.disabled = true;
  els.sendButton.textContent = "Working...";
  persistUiState();
  const thinkingNode = addThinkingMessage(prompt, files);
  const requestStartedAt = Date.now();

  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: prompt,
        attachments: files,
        model,
        session_id: sessionId,
        multi_agent: Boolean(els.agentsMode?.checked),
        stream: false,
      }),
    });

    state.currentSession = result.session_id || state.currentSession;
    removeThinkingMessage(thinkingNode);

    if (result.ok) {
      applyTokenUsage(result.usage);
      addMessage(
        "assistant",
        result.answer || "(no response)",
        "",
        { duration_ms: Date.now() - requestStartedAt },
      );
    } else {
      addMessage(
        "assistant",
        result.error || "Unknown error",
        "error",
        { duration_ms: Date.now() - requestStartedAt },
      );
    }
    refreshAll();
  } catch (error) {
    removeThinkingMessage(thinkingNode);
    addMessage(
      "assistant",
      error.message || "Could not reach Ci2Lab.",
      "error",
      { duration_ms: Date.now() - requestStartedAt },
    );
  } finally {
    els.sendButton.disabled = false;
    els.sendButton.textContent = "Send";
    persistUiState();
  }
}

async function loadSessionIntoChat(sessionId) {
  const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not open the session", "error");
    return;
  }

  const session = result.session;
  state.currentSession = session.id;
  state.chatMessages = [];
  state.uploadedFiles = [];
  applyTokenUsage(session.token_usage);
  renderAttachments();
  els.messages.innerHTML = "";
  const sessionModel = state.models.find((model) => (
    model.id === session.model || model.ollama_tag === session.model
  ));
  if (sessionModel && [...els.modelSelect.options].some((option) => option.value === sessionModel.id)) {
    els.modelSelect.value = sessionModel.id;
    updateCommandPreview();
  }

  const visibleMessages = (session.messages || []).filter((message) => (
    message.role === "user" || message.role === "assistant"
  ));
  if (!visibleMessages.length) {
    setEmptyChat();
    addMessage("assistant", `Session ${session.id} resumed.`);
    switchView("chatView");
    return;
  }
  visibleMessages.forEach((message) => {
    addMessage(message.role === "user" ? "user" : "assistant", message.content);
  });
  switchView("chatView");
}

async function deleteSavedSession(sessionId, button) {
  const confirmed = window.confirm("Delete this saved conversation? Its local file will be removed.");
  if (!confirmed) return;

  button.disabled = true;
  button.textContent = "Deleting...";
  const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });

  if (!result.ok) {
    button.disabled = false;
    button.textContent = "Delete";
    addMessage("assistant", result.error || "Could not delete the session.", "error");
    return;
  }

  if (state.currentSession === sessionId) {
    state.currentSession = null;
    state.chatMessages = [];
    setEmptyChat();
    persistUiState();
  }
  await refreshAll();
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollPullTask(taskId, tag) {
  if (state.pullPolls[taskId]) return;
  state.pullPolls[taskId] = true;
  try {
    while (true) {
      await delay(900);
      const result = await api(`/api/models/pull/${encodeURIComponent(taskId)}`);
      if (!result.ok) {
        state.pullTasks[tag] = {
          id: taskId,
          tag,
          status: "Could not query the download",
          percent: 0,
          completed: 0,
          total: 0,
          done: true,
          ok: false,
          error: result.error || "Unknown error",
        };
        renderModels();
        break;
      }

      state.pullTasks[tag] = result.task;
      renderModels();
      if (result.task.done) {
        if (!result.task.ok) {
          addMessage("assistant", result.task.error || "Could not download the model", "error");
        }
        await refreshAll();
        break;
      }
    }
  } finally {
    delete state.pullPolls[taskId];
  }
}

async function pollDeleteTask(taskId, tag) {
  if (state.deletePolls[taskId]) return;
  state.deletePolls[taskId] = true;
  try {
    while (true) {
      await delay(700);
      const result = await api(`/api/models/delete/${encodeURIComponent(taskId)}`);
      if (!result.ok) {
        state.deleteTasks[tag] = {
          id: taskId,
          tag,
          status: "Could not query the uninstall",
          percent: 0,
          done: true,
          ok: false,
          error: result.error || "Unknown error",
        };
        renderModels();
        break;
      }

      state.deleteTasks[tag] = result.task;
      renderModels();
      if (result.task.done) {
        if (!result.task.ok) {
          addMessage("assistant", result.task.error || "Could not uninstall the model", "error");
        }
        await refreshAll();
        break;
      }
    }
  } finally {
    delete state.deletePolls[taskId];
  }
}

async function handleModelAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const tag = button.dataset.tag;
  if (action === "use") {
    els.modelSelect.value = button.dataset.model;
    updateCommandPreview();
    switchView("chatView");
    if (!state.currentSession && !state.chatMessages.length) {
      await startChatSession({ forceNew: true });
    }
    return;
  }
  button.disabled = true;
  button.textContent = action === "pull" ? "Starting..." : "Deleting...";
  const endpoint = action === "pull" ? "/api/models/pull" : "/api/models/delete";
  const result = await api(endpoint, {
    method: "POST",
    body: JSON.stringify({ tag }),
  });
  if (!result.ok) {
    addMessage("assistant", result.error || "Could not complete the action", "error");
    await refreshAll();
    return;
  }

  if (action === "pull") {
    state.pullTasks[tag] = result.task;
    renderModels();
    pollPullTask(result.task_id, tag);
    return;
  }

  state.deleteTasks[tag] = result.task;
  renderModels();
  pollDeleteTask(result.task_id, tag);
}

function handleModelSelectChange() {
  updateCommandPreview();
  renderTokenInfo();
  persistUiState();
}

function toggleControlHelp(button) {
  const target = document.getElementById(button.dataset.helpToggle || "");
  if (!target) return;
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  target.hidden = expanded;
}

function bindEvents() {
  els.chatForm.addEventListener("submit", sendMessage);
  els.fileInput.addEventListener("change", uploadSelectedFiles);
  els.attachmentsList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-remove-attachment]");
    if (!button) return;
    removeAttachment(button.dataset.removeAttachment);
  });
  els.modelSelect.addEventListener("change", handleModelSelectChange);
  els.modelSearch.addEventListener("input", renderModels);
  els.modelsList.addEventListener("click", handleModelAction);
  els.refreshButton.addEventListener("click", () => runRefreshFromButton(els.refreshButton));
  els.chatRefreshButton.addEventListener("click", () => runRefreshFromButton(els.chatRefreshButton));
  els.agentsMode?.addEventListener("change", updateAgentsModeState);
  els.quickActions?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action-prompt]");
    if (!button) return;
    applyActionPrompt(button.dataset.actionPrompt || "");
  });
  els.tokenCounter?.addEventListener("click", () => {
    renderTokenInfo();
    switchView("tokenInfoView");
  });
  els.backToChatFromTokens?.addEventListener("click", () => switchView("chatView"));
  document.querySelectorAll("[data-help-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleControlHelp(button));
  });
  els.newChat.addEventListener("click", async () => {
    state.currentSession = null;
    state.chatMessages = [];
    state.uploadedFiles = [];
    state.tokenUsage = emptyTokenUsage();
    if (els.agentsMode) {
      els.agentsMode.checked = false;
    }
    updateTokenDisplay();
    updateAgentsModeState({ persist: false });
    renderAttachments();
    setEmptyChat();
    persistUiState();
    switchView("chatView");
    await startChatSession({ forceNew: true });
  });
  els.sessionsList.addEventListener("click", (event) => {
    const deleteButton = event.target.closest("button[data-delete-session]");
    if (deleteButton) {
      deleteSavedSession(deleteButton.dataset.deleteSession, deleteButton);
      return;
    }
    const button = event.target.closest("button[data-session]");
    if (!button) return;
    loadSessionIntoChat(button.dataset.session);
  });
  els.navButtons.forEach((button) => {
    if (button.id === "newChat") return;
    button.addEventListener("click", async () => {
      switchView(button.dataset.view || "homeView", button.dataset.scroll || null);
      if (button.id === "openChat" && !state.currentSession && !state.chatMessages.length) {
        await startChatSession({ forceNew: true });
      }
    });
  });
}

restoreUiState();
state.tokenUsage = normalizeTokenUsage(state.tokenUsage);
if (els.agentsMode) {
  els.agentsMode.checked = Boolean(state.agentsMode);
}
updateTokenDisplay();
updateAgentsModeState({ persist: false });
renderChatMessages();
renderAttachments();
bindEvents();
renderTokenInfo();
switchView(state.activeView || "homeView");
refreshAll().catch((error) => {
  els.ollamaStatus.textContent = "UI error";
  addMessage("assistant", error.message, "error");
});
