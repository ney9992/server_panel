let currentServerId = null;
let refreshTimer = null;

function api() {
  return window.pywebview.api;
}

function waitForPywebview() {
  return new Promise((resolve) => {
    if (window.pywebview) return resolve();
    window.addEventListener("pywebviewready", () => resolve());
  });
}

function showToast(msg, kind) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (kind ? " " + kind : "");
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3500);
}

function formatBytes(n) {
  if (n === null || n === undefined) return "—";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(1) + " " + units[i];
}

function formatUptime(sec) {
  if (sec === null || sec === undefined) return "—";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  let out = "";
  if (d) out += d + "д ";
  out += h + "ч " + m + "м";
  return out;
}

function barClass(pct) {
  if (pct >= 90) return "crit";
  if (pct >= 70) return "warn";
  return "";
}

// ---------- список серверов (для редактирования) ----------

async function loadServers() {
  servers = await api().list_servers();
  const list = document.getElementById("serverList");
  list.innerHTML = "";
  for (const s of servers) {
    const li = document.createElement("li");
    li.className = s.id === currentServerId ? "active" : "";
    li.innerHTML = `<span class="dot" id="dot-${s.id}"></span><span>${s.name || s.host}</span>`;
    li.addEventListener("click", () => selectServer(s.id));
    list.appendChild(li);
  }
  if (!servers.length) {
    document.getElementById("emptyState").classList.remove("hidden");
    document.getElementById("dashboard").classList.add("hidden");
  }
}

function selectServer(id) {
  currentServerId = id;
  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("dashboard").classList.remove("hidden");
  [...document.querySelectorAll(".server-list li")].forEach((li, i) => {
    li.classList.toggle("active", servers[i] && servers[i].id === id);
  });
  const s = servers.find((x) => x.id === id);
  document.getElementById("serverTitle").textContent = s ? (s.name || s.host) : "—";
  refreshDashboard();
  restartAutoRefresh();
}

function restartAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    if (currentServerId) refreshDashboard(true);
  }, 15000);
}

// ---------- дашборд ----------

async function refreshDashboard(silent) {
  if (!currentServerId) return;
  const dot = document.getElementById("dot-" + currentServerId);
  const res = await api().get_metrics(currentServerId);
  if (!res.ok) {
    if (dot) { dot.classList.remove("ok"); dot.classList.add("err"); }
    if (!silent) showToast("Ошибка получения метрик: " + (res.error || "неизвестно"), "err");
    return;
  }
  if (dot) { dot.classList.remove("err"); dot.classList.add("ok"); }

  document.getElementById("cardUptime").textContent = formatUptime(res.uptime_seconds);
  document.getElementById("cardLoad").textContent =
    `${res.load["1"]} / ${res.load["5"]} / ${res.load["15"]}`;

  const mem = res.memory;
  const memPct = mem.mem_total ? Math.round((mem.mem_used / mem.mem_total) * 100) : 0;
  document.getElementById("cardRam").textContent = `${formatBytes(mem.mem_used)} / ${formatBytes(mem.mem_total)} (${memPct}%)`;
  const barRam = document.getElementById("barRam");
  barRam.style.width = memPct + "%";
  barRam.className = "card-bar-fill " + barClass(memPct);

  const swapPct = mem.swap_total ? Math.round((mem.swap_used / mem.swap_total) * 100) : 0;
  document.getElementById("cardSwap").textContent = mem.swap_total
    ? `${formatBytes(mem.swap_used)} / ${formatBytes(mem.swap_total)} (${swapPct}%)`
    : "нет свопа";
  const barSwap = document.getElementById("barSwap");
  barSwap.style.width = swapPct + "%";
  barSwap.className = "card-bar-fill " + barClass(swapPct);

  const root = res.disk.root;
  if (root) {
    const pct = Math.round((root.used / root.total) * 100);
    document.getElementById("cardDiskRoot").textContent = `${formatBytes(root.used)} / ${formatBytes(root.total)} (${pct}%)`;
    const bar = document.getElementById("barDiskRoot");
    bar.style.width = pct + "%";
    bar.className = "card-bar-fill " + barClass(pct);
  } else {
    document.getElementById("cardDiskRoot").textContent = "—";
  }

  const flash = res.disk.flash;
  if (flash) {
    const pct = Math.round((flash.used / flash.total) * 100);
    document.getElementById("cardDiskFlash").textContent = `${formatBytes(flash.used)} / ${formatBytes(flash.total)} (${pct}%)`;
    const bar = document.getElementById("barDiskFlash");
    bar.style.width = pct + "%";
    bar.className = "card-bar-fill " + barClass(pct);
  } else {
    document.getElementById("cardDiskFlash").textContent = "не смонтирована";
  }

  renderServices(res.services || []);
}

function renderServices(list) {
  const body = document.getElementById("servicesBody");
  const noServices = document.getElementById("noServices");
  body.innerHTML = "";
  if (!list.length) {
    noServices.classList.remove("hidden");
    return;
  }
  noServices.classList.add("hidden");
  for (const svc of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${svc.name}</td>
      <td>${svc.type}</td>
      <td><span class="status-pill ${svc.status}">${statusLabel(svc.status)}</span></td>
      <td>${svc.branch}</td>
      <td class="row-actions">
        <button data-act="restart">Рестарт</button>
        <button data-act="${svc.status === "running" ? "stop" : "start"}">${svc.status === "running" ? "Стоп" : "Старт"}</button>
        <button data-act="logs">Логи</button>
        <button data-act="remove" class="danger">Удалить</button>
      </td>
    `;
    tr.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => handleServiceAction(svc.name, btn.dataset.act));
    });
    body.appendChild(tr);
  }
}

function statusLabel(st) {
  return { running: "запущена", stopped: "остановлена", unknown: "неизвестно" }[st] || st;
}

async function handleServiceAction(name, act) {
  if (act === "logs") return openLogsModal(name);
  if (act === "remove") return openRemoveConfirm(name);

  showToast(`Выполняется: ${act} для ${name}…`);
  const res = await api().service_action(currentServerId, name, act);
  if (res.ok) {
    showToast(`${name}: ${act} выполнено`, "ok");
  } else {
    showToast(`Ошибка: ${res.error || res.output || "неизвестно"}`, "err");
  }
  refreshDashboard(true);
}

// ---------- модалки ----------

function openModal(html) {
  document.getElementById("modalBox").innerHTML = html;
  document.getElementById("modalOverlay").classList.remove("hidden");
}
function closeModal() {
  document.getElementById("modalOverlay").classList.add("hidden");
}
document.getElementById("modalOverlay").addEventListener("click", (e) => {
  if (e.target.id === "modalOverlay") closeModal();
});

function openDeployModal() {
  openModal(`
    <h2>Деплой проекта</h2>
    <div class="field"><label>Имя проекта (латиница, цифры, - _)</label><input id="fName" placeholder="myapp"></div>
    <div class="field"><label>Git URL</label><input id="fGitUrl" placeholder="https://github.com/user/repo.git"></div>
    <div class="field"><label>Ветка</label><input id="fBranch" value="main"></div>
    <div class="field"><label>Тип (пусто = автоопределение по package.json/requirements.txt)</label>
      <select id="fType">
        <option value="">Автоопределение</option>
        <option value="node">Node.js</option>
        <option value="python">Python</option>
        <option value="custom">Своя команда</option>
      </select>
    </div>
    <div class="field"><label>Своя команда запуска (если тип "Своя команда")</label><input id="fCustom" placeholder="./start.sh"></div>
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Отмена</button>
      <button class="btn btn-primary" id="btnDeploySubmit">Развернуть</button>
    </div>
  `);
  document.getElementById("btnDeploySubmit").addEventListener("click", submitDeploy);
}

async function submitDeploy() {
  const name = document.getElementById("fName").value.trim();
  const gitUrl = document.getElementById("fGitUrl").value.trim();
  const branch = document.getElementById("fBranch").value.trim() || "main";
  const type = document.getElementById("fType").value;
  const custom = document.getElementById("fCustom").value.trim();

  if (!name || !gitUrl) {
    showToast("Укажите имя проекта и Git URL", "err");
    return;
  }
  closeModal();
  showToast(`Деплой ${name}… это может занять время`);
  const res = await api().deploy_project(currentServerId, name, gitUrl, branch, type, custom);
  if (res.ok) {
    showToast(`Проект ${name} развёрнут (${res.type})`, "ok");
  } else {
    showToast(`Ошибка деплоя: ${res.error || "неизвестно"}`, "err");
  }
  refreshDashboard(true);
}

function openRemoveConfirm(name) {
  openModal(`
    <h2>Удалить проект «${name}»?</h2>
    <p class="muted">Служба будет остановлена, init-скрипт и каталог проекта удалены безвозвратно.</p>
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Отмена</button>
      <button class="btn btn-danger" id="btnRemoveSubmit">Удалить</button>
    </div>
  `);
  document.getElementById("btnRemoveSubmit").addEventListener("click", async () => {
    closeModal();
    const res = await api().remove_project(currentServerId, name);
    if (res.ok) {
      showToast(`Проект ${name} удалён`, "ok");
    } else {
      showToast(`Ошибка удаления: ${res.error || "неизвестно"}`, "err");
    }
    refreshDashboard(true);
  });
}

async function openLogsModal(name) {
  openModal(`<h2>Логи: ${name}</h2><div class="log-box" id="logBox">Загрузка…</div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Закрыть</button></div>`);
  const res = await api().get_logs(currentServerId, name, 300);
  document.getElementById("logBox").textContent = res.ok ? (res.log || "(пусто)") : ("Ошибка: " + res.error);
}

function openServerModal(existing) {
  // Обработчик кнопки ⚙
  document.getElementById("btnEditServer").addEventListener("click", () => {
    const s = servers.find((x) => x.id === currentServerId);
    if (s) openServerModal(s);
  });

  const s = existing || { id: "", name: "", host: "", port: 22, user: "root", auth: "password", password: "", key_path: "", projects_dir: "/mnt/data/projects", flash_mount: "/mnt/data" };
  openModal(`
    <h2>${existing ? "Настройки сервера" : "Новый сервер"}</h2>
    <div class="field"><label>Название</label><input id="sName" value="${s.name}"></div>
    <div class="field"><label>Хост / IP</label><input id="sHost" value="${s.host}"></div>
    <div class="field"><label>Порт</label><input id="sPort" value="${s.port}"></div>
    <div class="field"><label>Пользователь</label><input id="sUser" value="${s.user}"></div>
    <div class="field">
      <label>Аутентификация</label>
      <div class="radio-row">
        <label><input type="radio" name="auth" value="password" ${s.auth !== "key" ? "checked" : ""}> Пароль</label>
        <label><input type="radio" name="auth" value="key" ${s.auth === "key" ? "checked" : ""}> SSH-ключ</label>
      </div>
    </div>
    <div class="field"><label>Пароль (оставьте пустым, чтобы не менять)</label><input id="sPassword" type="password" ${s.auth === 'password' ? '' : 'disabled'}></div>
    <div class="field"><label>Путь к приватному ключу (если auth = key)</label><input id="sKeyPath" value="${s.key_path || ""}"></div>
    <div class="field"><label>Каталог проектов на сервере</label><input id="sProjectsDir" value="${s.projects_dir}"></div>
    <div class="field"><label>Точка монтирования флешки</label><input id="sFlashMount" value="${s.flash_mount}"></div>
    <div class="modal-actions">
      ${existing ? '<button class="btn btn-danger" id="btnDeleteServer" style="margin-right:auto">Удалить сервер</button>' : ""}
      <button class="btn" onclick="closeModal()">Отмена</button>
      <button class="btn" id="btnTestConn">Проверить</button>
      <button class="btn btn-primary" id="btnSaveServer">Сохранить</button>
    </div>
  `);

  document.getElementById("btnSaveServer").addEventListener("click", async () => {
    const server = collectServerForm(s.id);
    const res = await api().save_server(server);
    if (res.ok) {
      showToast("Сервер сохранён", "ok");
      closeModal();
      await loadServers();
      selectServer(res.id);
    } else {
      showToast("Ошибка сохранения", "err");
    }
  });

  document.getElementById("btnTestConn").addEventListener("click", async () => {
    const server = collectServerForm(s.id || "tmp-test");
    await api().save_server(server);
    showToast("Проверка соединения…");
    const res = await api().test_connection(server.id);
    showToast(res.ok ? "Соединение успешно" : "Ошибка: " + (res.error || "нет связи"), res.ok ? "ok" : "err");
  });

  if (existing) {
    document.getElementById("btnDeleteServer").addEventListener("click", async () => {
      await api().delete_server(s.id);
      closeModal();
      currentServerId = null;
      document.getElementById("dashboard").classList.add("hidden");
      document.getElementById("emptyState").classList.remove("hidden");
      await loadServers();
    });
  }
}

// ---------- init ----------

document.getElementById("btnDeploy").addEventListener("click", openDeployModal);
document.getElementById("btnEditServer").addEventListener("click", () => {
  const s = servers.find((x) => x.id === currentServerId);
  if (s) openServerModal(s);
});

waitForPywebview().then(async () => {
  const list = document.getElementById("serverList");
  if (list) list.innerHTML = "";

  const servers = await api().list_servers();
  if (servers.length > 0) {
    currentServerId = servers[0].id;
    document.getElementById("emptyState").classList.add("hidden");
    document.getElementById("dashboard").classList.remove("hidden");
    refreshDashboard();
    restartAutoRefresh();
  } else {
    document.getElementById("emptyState").classList.remove("hidden");
    document.getElementById("dashboard").classList.add("hidden");
  }
});
