const state = {
  models: [],
  installed: [],
  currentSession: null,
  chatMessages: [],
  activeView: "homeView",
  pullTasks: {},
  pullPolls: {},
  deleteTasks: {},
  deletePolls: {},
};

const STORAGE_KEY = "ci2lab.ui.state.v1";

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
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  commandPreview: document.querySelector("#commandPreview"),
  technicalMode: document.querySelector("#technicalMode"),
  technicalModeLabel: document.querySelector("#technicalModeLabel"),
  chatTools: document.querySelector(".chat-tools"),
  refreshButton: document.querySelector("#refreshButton"),
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
  return new Intl.DateTimeFormat("es", {
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
    activeView: state.activeView,
    selectedModel: els.modelSelect?.value || "",
    technicalMode: Boolean(els.technicalMode?.checked),
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
    state.activeView = payload.activeView || "homeView";
    if (payload.selectedModel) {
      els.modelSelect.dataset.pendingValue = payload.selectedModel;
    }
    if (els.technicalMode) {
      els.technicalMode.checked = Boolean(payload.technicalMode);
    }
  } catch {
    state.currentSession = null;
    state.chatMessages = [];
    state.activeView = "homeView";
  }
}

function switchView(viewId, scrollTarget = null) {
  state.activeView = viewId;
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

function renderChatMessages() {
  els.messages.innerHTML = "";
  if (!state.chatMessages.length) {
    setEmptyChat();
    return;
  }
  state.chatMessages.forEach((message) => {
    appendMessageNode(message.role, message.text, message.extraClass || "");
  });
}

function appendMessageNode(role, text, extraClass = "") {
  const empty = els.messages.querySelector(".empty-state");
  if (empty) empty.remove();
  const node = document.createElement("div");
  node.className = `message ${role} ${extraClass}`.trim();
  node.textContent = text;
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
  return node;
}

function addMessage(role, text, extraClass = "") {
  state.chatMessages.push({ role, text, extraClass });
  appendMessageNode(role, text, extraClass);
  persistUiState();
}

function addThinkingMessage() {
  const empty = els.messages.querySelector(".empty-state");
  if (empty) empty.remove();
  const node = document.createElement("div");
  node.className = "message assistant thinking";
  node.innerHTML = `
    <span class="lion-loader" aria-hidden="true">
      <span class="lion-body"></span>
      <span class="lion-head"></span>
      <span class="lion-mane"></span>
      <span class="lion-tail"></span>
      <span class="lion-leg front"></span>
      <span class="lion-leg back"></span>
    </span>
    <span>Pensando</span>
  `;
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
  return node;
}

function removeThinkingMessage(node) {
  if (node && node.parentNode) {
    node.remove();
  }
}

function setEmptyChat() {
  els.messages.innerHTML = `
    <div class="empty-state">
      <div>
        <p class="eyebrow">Florentino local</p>
        <h3>Empieza una conversación</h3>
        <p>Prueba: "resume este proyecto" o "lista los archivos Python".</p>
      </div>
    </div>
  `;
}

function updateCommandPreview() {
  const model = els.modelSelect.value || "<modelo>";
  if (els.commandPreview) {
    const technicalFlag = els.technicalMode?.checked ? "--yes " : "";
    els.commandPreview.textContent = `ci2lab ${technicalFlag}--model ${model} chat`;
  }
}

function updateTechnicalModeState({ persist = true } = {}) {
  const active = Boolean(els.technicalMode?.checked);
  els.chatTools?.classList.toggle("technical-active", active);
  if (els.technicalModeLabel) {
    els.technicalModeLabel.textContent = active ? "Modo técnico activo" : "Modo técnico";
  }
  updateCommandPreview();
  if (persist) persistUiState();
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
  const status = task.error || task.status || (type === "delete" ? "Desinstalando" : "Descargando");
  const detail = type === "pull"
    ? (task.total ? `${formatBytes(task.completed)} de ${formatBytes(task.total)}` : "Calculando tamaño...")
    : (task.done ? "Ollama actualizado" : "Eliminando archivos locales...");
  const className = `${type} ${task.error ? "error" : task.done ? "done" : "active"}`;

  return `
    <div class="download-progress ${className}">
      <div class="progress-row">
        <span>${escapeHtml(status)}</span>
        <strong>${percent.toFixed(0)}%</strong>
      </div>
      <div class="progress-bar"><i style="width: ${visiblePercent}%"></i></div>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
}

function renderModels() {
  const query = els.modelSearch.value.toLowerCase().trim();
  const models = orderedModels().filter((model) => {
    const haystack = `${model.display_name} ${model.id} ${model.ollama_tag} ${model.categories.join(" ")}`.toLowerCase();
    return !query || haystack.includes(query);
  });

  els.modelsList.innerHTML = models.map((model) => `
    <article class="model-card">
      <header>
        <div>
          <h4>${escapeHtml(model.display_name)}</h4>
          <div class="meta">${escapeHtml(model.id)} · ${escapeHtml(model.ollama_tag)}</div>
        </div>
        <span class="badge ${model.installed ? "ok" : ""}">${model.installed ? "Instalado" : model.tier}</span>
      </header>
      <div class="meta">
        ${escapeHtml(model.categories.join(", "))} · RAM aprox. ${model.ram_inference_gb} GB
        ${model.fit_label ? ` · ${escapeHtml(model.fit_label)}` : ""}
      </div>
      <div class="model-actions">
        <button type="button" data-action="use" data-model="${escapeHtml(model.id)}">Usar</button>
        <button type="button" data-action="pull" data-tag="${escapeHtml(model.ollama_tag)}">Descargar</button>
        <button type="button" data-action="delete" data-tag="${escapeHtml(model.ollama_tag)}">Eliminar</button>
      </div>
      ${renderModelProgress(model)}
    </article>
  `).join("");
}

function renderModelSelect() {
  const current = els.modelSelect.dataset.pendingValue || els.modelSelect.value;
  const models = orderedModels();
  els.modelSelect.innerHTML = models.map((model) => `
    <option value="${escapeHtml(model.id)}">${escapeHtml(model.display_name)} ${model.installed ? "" : "(no instalado)"}</option>
  `).join("");

  if (current && models.some((model) => model.id === current)) {
    els.modelSelect.value = current;
    delete els.modelSelect.dataset.pendingValue;
  }
  updateCommandPreview();
  persistUiState();
}

function renderSessions(sessions) {
  if (!sessions.length) {
    els.sessionsList.innerHTML = `<p class="meta">Aún no hay sesiones guardadas.</p>`;
    return;
  }
  els.sessionsList.innerHTML = sessions.map((session) => `
    <article class="session-card">
      <h4>${escapeHtml(session.title || "Conversación")}</h4>
      <div class="session-tag">Tag interno: <code>${escapeHtml(session.internal_tag || session.id)}</code></div>
      <div class="meta">${escapeHtml(session.model)} · ${escapeHtml(formatDate(session.updated_at))}</div>
      <div class="meta">${escapeHtml(session.cwd)}</div>
      <button type="button" data-session="${escapeHtml(session.id)}">Reanudar</button>
    </article>
  `).join("");
}

function renderSystem(payload) {
  if (!payload || !payload.ok || !payload.hardware) {
    els.systemSummary.textContent = payload?.error || "No se pudo leer el hardware.";
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
    ? "Hay presión de memoria: cerrar apps puede permitir modelos más grandes."
    : "Tu equipo está listo para modelos locales compatibles.";

  els.ramValue.textContent = `${formatGb(hardware.ram_available_gb)} libres`;
  els.ramMeta.textContent = `${formatGb(hardware.ram_total_gb)} totales`;
  setMeter(els.ramBar, ramFreePercent);

  els.diskValue.textContent = `${formatGb(disk.free_gb)} libres`;
  els.diskMeta.textContent = `${formatGb(disk.total_gb)} totales en ${disk.path || "workspace"}`;
  setMeter(els.diskBar, disk.free_percent || 0);

  els.budgetValue.textContent = formatGb(hardware.inference_budget_available_gb || hardware.inference_budget_gb);
  els.budgetMeta.textContent = `Seguro ahora · techo ${formatGb(budgetBase)}`;
  setMeter(els.budgetBar, budgetPercent);

  els.modeValue.textContent = hardware.inference_mode === "gpu" ? "GPU" : "CPU";
  els.modeMeta.textContent = `${hardware.gpu_name || "CPU only"} · ${hardware.cpu_cores} núcleos · ${hardware.hardware_tier}`;

  const recommendations = payload.recommendations || [];
  if (!recommendations.length) {
    els.recommendationsStrip.innerHTML = `<p class="meta">No hay recomendaciones disponibles ahora mismo.</p>`;
    return;
  }
  els.recommendationsStrip.innerHTML = recommendations.map((item) => `
    <article class="recommendation-card">
      <div>
        <div class="recommendation-card-head">
          <h4>${escapeHtml(item.display_name)}</h4>
          <span class="badge ${item.installed ? "ok" : ""}">${escapeHtml(item.installation_label || (item.installed ? "Instalado" : "Para descargar"))}</span>
        </div>
        <p>${escapeHtml(item.fit_label)} · ${escapeHtml(item.ollama_tag)}</p>
      </div>
      <div class="mini-meter">
        <span>${escapeHtml(formatGb(item.memory_required_gb))}</span>
        <div class="meter"><i style="width: ${clampPercent(item.memory_usage_percent)}%"></i></div>
      </div>
    </article>
  `).join("");
}

async function refreshAll() {
  const health = await api("/api/health");
  els.ollamaStatus.textContent = health.ok ? `Ollama listo (${health.installed_count})` : "Ollama no disponible";
  els.workspaceLabel.textContent = health.workspace || "";

  const systemPayload = await api("/api/system");
  renderSystem(systemPayload);

  const modelsPayload = await api("/api/models");
  state.models = modelsPayload.catalog || [];
  state.installed = modelsPayload.installed || [];
  renderModelSelect();
  renderModels();

  const sessions = await api("/api/sessions");
  renderSessions(sessions.sessions || []);
}

async function sendMessage(event) {
  event.preventDefault();
  const message = els.messageInput.value.trim();
  if (!message) return;
  const model = els.modelSelect.value;
  addMessage("user", message);
  els.messageInput.value = "";
  els.sendButton.disabled = true;
  els.sendButton.textContent = "Pensando";
  persistUiState();
  const thinkingNode = addThinkingMessage();

  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        model,
        session_id: state.currentSession,
        technical_mode: els.technicalMode.checked,
        stream: false,
      }),
    });

    state.currentSession = result.session_id || state.currentSession;
    removeThinkingMessage(thinkingNode);

    if (result.ok) {
      addMessage("assistant", result.answer || "(sin respuesta)");
    } else {
      addMessage("assistant", result.error || "Error desconocido", "error");
    }
    refreshAll();
  } catch (error) {
    removeThinkingMessage(thinkingNode);
    addMessage("assistant", error.message || "No se pudo contactar con Ci2Lab.", "error");
  } finally {
    els.sendButton.disabled = false;
    els.sendButton.textContent = "Enviar";
    persistUiState();
  }
}

async function loadSessionIntoChat(sessionId) {
  const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (!result.ok) {
    addMessage("assistant", result.error || "No se pudo abrir la sesión", "error");
    return;
  }

  const session = result.session;
  state.currentSession = session.id;
  state.chatMessages = [];
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
    addMessage("assistant", `Sesión ${session.id} reanudada.`);
    switchView("chatView");
    return;
  }
  visibleMessages.forEach((message) => {
    addMessage(message.role === "user" ? "user" : "assistant", message.content);
  });
  switchView("chatView");
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
          status: "No se pudo consultar la descarga",
          percent: 0,
          completed: 0,
          total: 0,
          done: true,
          ok: false,
          error: result.error || "Error desconocido",
        };
        renderModels();
        break;
      }

      state.pullTasks[tag] = result.task;
      renderModels();
      if (result.task.done) {
        if (!result.task.ok) {
          addMessage("assistant", result.task.error || "No se pudo descargar el modelo", "error");
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
          status: "No se pudo consultar la desinstalación",
          percent: 0,
          done: true,
          ok: false,
          error: result.error || "Error desconocido",
        };
        renderModels();
        break;
      }

      state.deleteTasks[tag] = result.task;
      renderModels();
      if (result.task.done) {
        if (!result.task.ok) {
          addMessage("assistant", result.task.error || "No se pudo desinstalar el modelo", "error");
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
    return;
  }
  button.disabled = true;
  button.textContent = action === "pull" ? "Iniciando..." : "Eliminando...";
  const endpoint = action === "pull" ? "/api/models/pull" : "/api/models/delete";
  const result = await api(endpoint, {
    method: "POST",
    body: JSON.stringify({ tag }),
  });
  if (!result.ok) {
    addMessage("assistant", result.error || "No se pudo completar la acción", "error");
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
  persistUiState();
}

function bindEvents() {
  els.chatForm.addEventListener("submit", sendMessage);
  els.modelSelect.addEventListener("change", handleModelSelectChange);
  els.technicalMode.addEventListener("change", () => updateTechnicalModeState());
  els.modelSearch.addEventListener("input", renderModels);
  els.modelsList.addEventListener("click", handleModelAction);
  els.refreshButton.addEventListener("click", async () => {
    els.refreshButton.disabled = true;
    els.refreshButton.textContent = "Actualizando...";
    try {
      await refreshAll();
    } finally {
      els.refreshButton.disabled = false;
      els.refreshButton.textContent = "Actualizar datos";
    }
  });
  els.newChat.addEventListener("click", () => {
    state.currentSession = null;
    state.chatMessages = [];
    setEmptyChat();
    persistUiState();
    switchView("chatView");
  });
  els.sessionsList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-session]");
    if (!button) return;
    loadSessionIntoChat(button.dataset.session);
  });
  els.navButtons.forEach((button) => {
    if (button.id === "newChat") return;
    button.addEventListener("click", () => {
      switchView(button.dataset.view || "homeView", button.dataset.scroll || null);
    });
  });
}

restoreUiState();
renderChatMessages();
bindEvents();
updateTechnicalModeState({ persist: false });
switchView(state.activeView || "homeView");
refreshAll().catch((error) => {
  els.ollamaStatus.textContent = "Error de UI";
  addMessage("assistant", error.message, "error");
});
