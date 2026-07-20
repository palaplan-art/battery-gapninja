const viewRoot = document.getElementById("view-root");
const modalRoot = document.getElementById("modal-root");

let state = {
  machines: [],
  filters: { machine_code: "", status: "", end_user: "" },
};

/* ---------------- API helper ---------------- */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Session expired — please sign in again");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail || msg;
    } catch (e) {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

function toast(message, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtDate(d) {
  if (!d) return "—";
  const dt = new Date(d + (d.length === 10 ? "T00:00:00" : ""));
  // e.g. "22 July 2026"
  return dt.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

function fmtDateTime(d) {
  if (!d) return "—";
  const dt = new Date(d.endsWith("Z") ? d : d + "Z");
  return dt.toLocaleString("en-US", {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function daysAgo(d) {
  if (!d) return null;
  const dt = new Date(d + "T00:00:00");
  return Math.floor((Date.now() - dt.getTime()) / 86400000);
}

function healthClass(pct) {
  if (pct === null || pct === undefined) return "";
  if (pct >= 80) return "health-good";
  if (pct >= 50) return "health-mid";
  return "health-low";
}

function healthColor(pct) {
  if (pct >= 80) return "var(--green)";
  if (pct >= 50) return "var(--amber)";
  return "var(--red)";
}

const STATUS_LABEL = { active: "Active", maintenance: "Maintenance", retired: "Retired" };

/* ---------------- Routing ---------------- */
function navigate(view) {
  location.hash = view;
}

window.addEventListener("hashchange", route);

function route() {
  const hash = location.hash.replace(/^#/, "");
  if (hash.startsWith("battery/")) {
    renderDetail(decodeURIComponent(hash.slice("battery/".length)));
  } else if (hash.startsWith("machine/")) {
    renderMachineDetail(decodeURIComponent(hash.slice("machine/".length)));
  } else if (hash === "machines") {
    renderMachines();
  } else if (hash === "sync") {
    renderSync();
  } else {
    renderDashboard();
  }
}

/* ---------------- Dashboard ---------------- */
async function renderDashboard() {
  viewRoot.innerHTML = `<div class="loading">Loading...</div>`;

  const [summary, machines] = await Promise.all([
    api("/api/dashboard/summary"),
    api("/api/machines"),
  ]);
  state.machines = machines;

  const q = document.getElementById("search-input")?.value || "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (state.filters.machine_code) params.set("machine_code", state.filters.machine_code);
  if (state.filters.status) params.set("status", state.filters.status);
  if (state.filters.end_user) params.set("end_user", state.filters.end_user);
  let batteries = await api(`/api/batteries?${params.toString()}`);

  // When not filtering by a specific end-user, surface TBTS batteries first.
  if (!state.filters.end_user) {
    batteries = [...batteries].sort((a, b) => {
      const at = (a.end_user || "").toUpperCase().startsWith("TBTS") ? 0 : 1;
      const bt = (b.end_user || "").toUpperCase().startsWith("TBTS") ? 0 : 1;
      if (at !== bt) return at - bt;
      return a.serial.localeCompare(b.serial);
    });
  }

  const endUsers = summary.end_users || [];

  viewRoot.innerHTML = `
    <div class="stats-row stats-4">
      <div class="stat-card"><div class="num">${summary.total}</div><div class="label">Total Batteries</div></div>
      <div class="stat-card"><div class="num" style="color:var(--green)">${summary.active}</div><div class="label">Active</div></div>
      <div class="stat-card"><div class="num" style="color:var(--amber)">${summary.maintenance}</div><div class="label">Maintenance</div></div>
      <div class="stat-card"><div class="num" style="color:var(--gray)">${summary.retired}</div><div class="label">Retired</div></div>
    </div>

    <div class="filter-row">
      <select id="filter-enduser">
        <option value="">All End-Users</option>
        ${endUsers.map((u) => `<option value="${escapeHtml(u)}" ${state.filters.end_user === u ? "selected" : ""}>${escapeHtml(u)}</option>`).join("")}
      </select>
      <select id="filter-machine">
        <option value="">All Machines</option>
        ${state.machines.map((m) => `<option value="${escapeHtml(m.code)}" ${state.filters.machine_code === m.code ? "selected" : ""}>${escapeHtml(m.code)}</option>`).join("")}
      </select>
      <select id="filter-status">
        <option value="">All Status</option>
        ${Object.entries(STATUS_LABEL).map(([k, v]) => `<option value="${k}" ${state.filters.status === k ? "selected" : ""}>${v}</option>`).join("")}
      </select>
    </div>

    <div class="battery-grid">
      ${
        batteries.length
          ? batteries.map((b) => batteryCardHtml(b)).join("")
          : `<div class="empty-state">No batteries match the current filters.</div>`
      }
    </div>
  `;

  document.getElementById("filter-enduser").onchange = (e) => {
    state.filters.end_user = e.target.value;
    renderDashboard();
  };
  document.getElementById("filter-machine").onchange = (e) => {
    state.filters.machine_code = e.target.value;
    renderDashboard();
  };
  document.getElementById("filter-status").onchange = (e) => {
    state.filters.status = e.target.value;
    renderDashboard();
  };
  viewRoot.querySelectorAll(".battery-card").forEach((card) => {
    card.onclick = () => navigate(`battery/${card.dataset.serial}`);
  });
}

function batteryCardHtml(b) {
  const pct = b.health_percent;
  return `
    <div class="battery-card" data-serial="${escapeHtml(b.serial)}">
      <div class="battery-card-head">
        <span class="serial">${escapeHtml(b.serial)}</span>
        <span class="badge ${b.status}">${STATUS_LABEL[b.status]}</span>
      </div>
      <div class="row"><span>Machine</span><b>${escapeHtml(b.machine_code) || "—"}</b></div>
      <div class="row"><span>End-User</span><b>${escapeHtml(b.end_user) || "—"}</b></div>
      <div class="row"><span>Commissioned</span><b>${fmtDate(b.commission_date)}</b></div>
      ${
        pct !== null && pct !== undefined
          ? `<div class="row"><span>Health</span><b class="${healthClass(pct)}">${pct}%</b></div>`
          : ""
      }
    </div>
  `;
}

/* ---------------- Battery Detail ---------------- */
async function renderDetail(serial) {
  viewRoot.innerHTML = `<div class="loading">Loading...</div>`;
  let battery, machines;
  try {
    [battery, machines] = await Promise.all([
      api(`/api/batteries/${encodeURIComponent(serial)}`),
      api("/api/machines"),
    ]);
  } catch (e) {
    viewRoot.innerHTML = `<div class="empty-state">Battery "${escapeHtml(serial)}" not found.</div>`;
    return;
  }
  state.machines = machines;

  const pct = battery.health_percent;

  viewRoot.innerHTML = `
    <div class="detail-header">
      <button class="back-btn" id="back-btn">←</button>
      <div>
        <div class="detail-title">${escapeHtml(battery.serial)}</div>
      </div>
      <span class="badge ${battery.status}">${STATUS_LABEL[battery.status]}</span>
    </div>

    <div class="top-dates">
      <div class="date-card">
        <div class="label">Commissioned</div>
        <div class="value">${fmtDate(battery.commission_date)}</div>
      </div>
      <div class="date-card">
        <div class="label">Last Cell Change</div>
        <div class="value">${battery.last_cell_replacement_date ? fmtDate(battery.last_cell_replacement_date) : "Never"}</div>
      </div>
      <div class="date-card ${pct === null || pct === undefined ? "" : pct < 50 ? "danger" : pct < 80 ? "warn" : ""}">
        <div class="label">Battery Health</div>
        <div class="health-value">
          <div class="value ${healthClass(pct)}">${pct !== null && pct !== undefined ? pct + "%" : "—"}</div>
        </div>
        ${
          pct !== null && pct !== undefined
            ? `<div class="health-bar-track"><div class="health-bar-fill" style="width:${pct}%;background:${healthColor(pct)}"></div></div>`
            : `<div style="font-size:11.5px;color:var(--text-faint);margin-top:6px">No capacity reading yet</div>`
        }
      </div>
    </div>

    <div class="detail-grid">
      <div class="panel">
        <h3>Battery Info</h3>
        <div class="form-grid">
          <div class="field-row">
            <div class="field">
              <label>Machine In Use ${battery.machine_code ? `<a class="inline-link" href="#machine/${encodeURIComponent(battery.machine_code)}">open ${escapeHtml(battery.machine_code)} →</a>` : ""}</label>
              <select id="f-machine">
                <option value="">— Unassigned —</option>
                ${state.machines.map((m) => `<option value="${escapeHtml(m.code)}" ${battery.machine_code === m.code ? "selected" : ""}>${escapeHtml(m.code)}${m.customer ? " — " + escapeHtml(m.customer) : ""}</option>`).join("")}
              </select>
            </div>
            <button class="icon-btn" id="edit-machine-btn" title="Edit this machine's info">✎</button>
          </div>
          <div class="field">
            <label>End-User</label>
            <input id="f-enduser" type="text" value="${escapeHtml(battery.end_user)}" placeholder="User name / department" />
          </div>
          <div class="field">
            <label>Status</label>
            <select id="f-status">
              ${Object.entries(STATUS_LABEL).map(([k, v]) => `<option value="${k}" ${battery.status === k ? "selected" : ""}>${v}</option>`).join("")}
            </select>
          </div>
          <div class="field">
            <label>Commission Date</label>
            <input id="f-commission" type="date" value="${battery.commission_date || ""}" />
          </div>
          <div class="field">
            <label>Last Cell Replacement Date</label>
            <input id="f-cell" type="date" value="${battery.last_cell_replacement_date || ""}" />
          </div>
          <div class="field">
            <label>Measured Capacity (mAh, max 6000)</label>
            <input id="f-capacity" type="number" min="0" max="6000" value="${battery.last_capacity_mah ?? ""}" placeholder="e.g. 5731" />
          </div>
          <div class="field">
            <label>Notes</label>
            <textarea id="f-notes" placeholder="Additional notes">${escapeHtml(battery.notes)}</textarea>
          </div>
          <div class="form-actions">
            <button class="btn primary" id="save-btn">Save Changes</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <h3>Activity Log</h3>
        <div class="timeline" id="timeline">
          ${
            battery.logs.length
              ? battery.logs.map(logItemHtml).join("")
              : `<div class="empty-state">No activity yet</div>`
          }
        </div>
        <div class="add-note-row">
          <input id="note-input" type="text" placeholder="Add an activity note e.g. inspection / sent for repair" />
          <button class="btn ghost small" id="add-note-btn">Add</button>
        </div>
      </div>
    </div>

    <div class="panel test-panel">
      <div class="section-head">
        <h3>Test Records</h3>
        <button class="btn primary small" id="add-test-btn">+ Add Test Result</button>
      </div>
      <div class="table-scroll">
        <table class="tests-table">
          <thead>
            <tr>
              <th>Test Date</th>
              <th>Full Charge</th>
              <th>Capacity (mAh)</th>
              <th>Start</th>
              <th>1st Bar</th>
              <th>2nd Bar</th>
              <th>Alert</th>
              <th>Shutdown</th>
              <th>Total Runtime</th>
              <th>Run to 0 mAh</th>
              <th>Remark</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${
              battery.tests.length
                ? battery.tests.map(testRowHtml).join("")
                : `<tr><td colspan="12"><div class="empty-state">No test records yet</div></td></tr>`
            }
          </tbody>
        </table>
      </div>
    </div>
  `;

  document.getElementById("back-btn").onclick = () => navigate("");

  document.getElementById("edit-machine-btn").onclick = () => {
    const code = document.getElementById("f-machine").value;
    if (!code) {
      toast("Assign a machine first before editing it", true);
      return;
    }
    openEditMachineModal(code, () => renderDetail(battery.serial));
  };

  document.getElementById("save-btn").onclick = async () => {
    const capacityRaw = document.getElementById("f-capacity").value;
    const payload = {
      machine_code: document.getElementById("f-machine").value || null,
      end_user: document.getElementById("f-enduser").value || null,
      status: document.getElementById("f-status").value,
      commission_date: document.getElementById("f-commission").value || null,
      last_cell_replacement_date: document.getElementById("f-cell").value || null,
      last_capacity_mah: capacityRaw === "" ? null : parseInt(capacityRaw, 10),
      notes: document.getElementById("f-notes").value || null,
    };
    try {
      await api(`/api/batteries/${encodeURIComponent(battery.serial)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast("Changes saved");
      renderDetail(battery.serial);
    } catch (e) {
      toast(e.message, true);
    }
  };

  document.getElementById("add-note-btn").onclick = async () => {
    const input = document.getElementById("note-input");
    if (!input.value.trim()) return;
    try {
      await api(`/api/batteries/${encodeURIComponent(battery.serial)}/logs`, {
        method: "POST",
        body: JSON.stringify({ description: input.value.trim() }),
      });
      renderDetail(battery.serial);
    } catch (e) {
      toast(e.message, true);
    }
  };

  bindTimelineActions(battery.serial);

  document.getElementById("add-test-btn").onclick = () =>
    openTestModal(battery.serial, null);
  viewRoot.querySelectorAll(".tests-table [data-edit-test]").forEach((btn) => {
    const test = battery.tests.find((t) => String(t.id) === btn.dataset.editTest);
    btn.onclick = () => openTestModal(battery.serial, test);
  });
  viewRoot.querySelectorAll(".tests-table [data-del-test]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("Delete this test record?")) return;
      try {
        await api(
          `/api/batteries/${encodeURIComponent(battery.serial)}/tests/${btn.dataset.delTest}`,
          { method: "DELETE" }
        );
        renderDetail(battery.serial);
      } catch (e) {
        toast(e.message, true);
      }
    };
  });
}

function testCell(v) {
  return `<td>${escapeHtml(v) || "—"}</td>`;
}

function testRowHtml(t) {
  return `
    <tr>
      <td class="nowrap"><b>${t.test_date ? fmtDate(t.test_date) : "—"}</b></td>
      ${testCell(t.charge_full_time)}
      ${testCell(t.capacity_after_charge_mah)}
      ${testCell(t.start_time)}
      ${testCell(t.first_bar_time)}
      ${testCell(t.second_bar_time)}
      ${testCell(t.alert_time)}
      ${testCell(t.shutdown_time)}
      ${testCell(t.total_runtime)}
      ${testCell(t.run_to_zero_time)}
      ${testCell(t.remark)}
      <td class="nowrap">
        <button class="edit-link" data-edit-test="${t.id}">Edit</button>
        <button class="edit-link danger-link" data-del-test="${t.id}">Delete</button>
      </td>
    </tr>
  `;
}

const TEST_FIELDS = [
  { key: "test_date", label: "Test Date", type: "date" },
  { key: "charge_full_time", label: "Full Charge Time (h:mm)", type: "time" },
  { key: "capacity_after_charge_mah", label: "Capacity After Charge (mAh)", type: "number" },
  { key: "start_time", label: "Test Start Time", type: "time" },
  { key: "first_bar_time", label: "1st Bar Empty", type: "time" },
  { key: "second_bar_time", label: "2nd Bar Empty", type: "time" },
  { key: "alert_time", label: "Low Battery Alert", type: "time" },
  { key: "shutdown_time", label: "Shutdown / Empty", type: "time" },
  { key: "total_runtime", label: "Total Runtime (h:mm)", type: "time" },
  { key: "run_to_zero_time", label: "Run to 0 mAh (h:mm)", type: "time" },
  { key: "remark", label: "Remark", type: "textarea" },
];

// Two dropdowns (hour 00-23, minute 00-59) that together produce an "HH:MM"
// string. Works for both clock times and short durations.
function timeSelectHtml(key, value) {
  const [hh, mm] = (value || "").split(":");
  const opt = (n, sel) =>
    `<option value="${n}" ${sel === n ? "selected" : ""}>${n}</option>`;
  const hours = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
  const mins = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0"));
  return `
    <div class="time-select">
      <select id="t-${key}-h">
        <option value="">--</option>
        ${hours.map((h) => opt(h, hh)).join("")}
      </select>
      <span>:</span>
      <select id="t-${key}-m">
        <option value="">--</option>
        ${mins.map((m) => opt(m, mm)).join("")}
      </select>
    </div>`;
}

function readTimeSelect(key) {
  const h = document.getElementById(`t-${key}-h`).value;
  const m = document.getElementById(`t-${key}-m`).value;
  if (!h && !m) return null;
  return `${h || "00"}:${m || "00"}`;
}

function openTestModal(serial, test) {
  const editing = !!test;
  const t = test || {};
  const fieldsHtml = TEST_FIELDS.map((f) => {
    const val = t[f.key] ?? "";
    if (f.type === "textarea") {
      return `<div class="field"><label>${f.label}</label><textarea id="t-${f.key}" placeholder="${f.ph || ""}">${escapeHtml(val)}</textarea></div>`;
    }
    if (f.type === "time") {
      return `<div class="field"><label>${f.label}</label>${timeSelectHtml(f.key, val)}</div>`;
    }
    return `<div class="field"><label>${f.label}</label><input id="t-${f.key}" type="${f.type}" value="${escapeHtml(val)}" placeholder="${f.ph || ""}" ${f.type === "number" ? 'min="0" max="6000"' : ""} /></div>`;
  }).join("");

  openModal(`
    <h2>${editing ? "Edit" : "Add"} Test Result — ${escapeHtml(serial)}</h2>
    <div class="form-grid form-grid-2">
      ${fieldsHtml}
    </div>
    <div class="form-actions">
      <button class="btn ghost" id="cancel-btn">Cancel</button>
      <button class="btn primary" id="save-test-btn">${editing ? "Save" : "Add"}</button>
    </div>
  `, true);

  document.getElementById("cancel-btn").onclick = closeModal;
  document.getElementById("save-test-btn").onclick = async () => {
    const payload = {};
    for (const f of TEST_FIELDS) {
      if (f.type === "time") {
        payload[f.key] = readTimeSelect(f.key);
        continue;
      }
      const raw = document.getElementById(`t-${f.key}`).value;
      if (f.type === "number") {
        payload[f.key] = raw === "" ? null : parseInt(raw, 10);
      } else {
        payload[f.key] = raw.trim() === "" ? null : raw.trim();
      }
    }
    try {
      const url = editing
        ? `/api/batteries/${encodeURIComponent(serial)}/tests/${test.id}`
        : `/api/batteries/${encodeURIComponent(serial)}/tests`;
      await api(url, {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      closeModal();
      toast(editing ? "Test record updated" : "Test record added");
      renderDetail(serial);
    } catch (e) {
      toast(e.message, true);
    }
  };
}

function logItemHtml(log) {
  return `
    <div class="timeline-item" data-log-id="${log.id}">
      <div class="timeline-dot ${log.action_type}"></div>
      <div class="timeline-body" data-view>
        <div class="desc">${escapeHtml(log.description)}</div>
        <div class="ts">${fmtDateTime(log.timestamp)}</div>
      </div>
      <div class="timeline-actions">
        <button class="edit-log" title="Edit">✎</button>
        <button class="delete delete-log" title="Delete">🗑</button>
      </div>
    </div>
  `;
}

function bindTimelineActions(serial) {
  document.querySelectorAll(".timeline-item").forEach((item) => {
    const logId = item.dataset.logId;

    item.querySelector(".edit-log").onclick = () => {
      const body = item.querySelector("[data-view]");
      const currentText = body.querySelector(".desc").textContent;
      body.innerHTML = `
        <textarea>${escapeHtml(currentText)}</textarea>
        <div class="timeline-edit-actions">
          <button class="btn primary small" data-save>Save</button>
          <button class="btn ghost small" data-cancel>Cancel</button>
        </div>
      `;
      body.querySelector("[data-save]").onclick = async () => {
        const newText = body.querySelector("textarea").value.trim();
        if (!newText) return;
        try {
          await api(`/api/batteries/${encodeURIComponent(serial)}/logs/${logId}`, {
            method: "PATCH",
            body: JSON.stringify({ description: newText }),
          });
          renderDetail(serial);
        } catch (e) {
          toast(e.message, true);
        }
      };
      body.querySelector("[data-cancel]").onclick = () => renderDetail(serial);
    };

    item.querySelector(".delete-log").onclick = async () => {
      if (!confirm("Delete this activity log entry?")) return;
      try {
        await api(`/api/batteries/${encodeURIComponent(serial)}/logs/${logId}`, {
          method: "DELETE",
        });
        renderDetail(serial);
      } catch (e) {
        toast(e.message, true);
      }
    };
  });
}

/* ---------------- Machines view ---------------- */
async function renderMachines() {
  viewRoot.innerHTML = `<div class="loading">Loading...</div>`;
  // Machines already come sorted ascending by code from the API.
  const [machines, batteries] = await Promise.all([
    api("/api/machines"),
    api("/api/batteries"),
  ]);
  state.machines = machines;

  const countByMachine = {};
  for (const b of batteries) {
    if (b.machine_code) countByMachine[b.machine_code] = (countByMachine[b.machine_code] || 0) + 1;
  }

  viewRoot.innerHTML = `
    <div class="section-head">
      <h2>Machines</h2>
      <button class="btn primary" id="add-machine-btn">+ Machine</button>
    </div>
    <div class="machine-list">
      ${
        machines.length
          ? machines.map((m) => `
            <div class="machine-row" data-code="${escapeHtml(m.code)}">
              <div class="machine-row-main">
                <span class="machine-code">${escapeHtml(m.code)}</span>
                <span class="machine-sub">${escapeHtml(m.customer) || "—"}${m.division ? " · " + escapeHtml(m.division) : ""}</span>
              </div>
              <div class="machine-row-meta">
                ${m.system ? `<span class="chip">${escapeHtml(m.system)}</span>` : ""}
                <span class="chip">${countByMachine[m.code] || 0} batteries</span>
                <span class="machine-open">Open →</span>
              </div>
            </div>
          `).join("")
          : `<div class="empty-state">No machines yet</div>`
      }
    </div>
  `;

  document.getElementById("add-machine-btn").onclick = openNewMachineModal;
  viewRoot.querySelectorAll(".machine-row").forEach((row) => {
    row.onclick = () => navigate(`machine/${row.dataset.code}`);
  });
}

/* ---------------- Machine Detail ---------------- */
const MACHINE_FIELDS = [
  { key: "customer", label: "Customer", type: "text" },
  { key: "division", label: "Division", type: "text" },
  { key: "contact_person", label: "Contact Person", type: "text" },
  { key: "contact_phone", label: "Contact Phone", type: "text" },
  { key: "system", label: "System", type: "text", ph: "Inline / Stand alone" },
  { key: "install_date", label: "Install Date", type: "date" },
  { key: "gauge_block_sn", label: "Gauge Block S/N (calibration)", type: "text" },
  { key: "last_calibration_date", label: "Last Calibration Date", type: "date" },
  { key: "next_calibration_date", label: "Next Calibration Due", type: "date" },
  { key: "wifi_model", label: "Wi-Fi Model", type: "text" },
  { key: "wifi_sn", label: "Wi-Fi S/N", type: "text" },
  { key: "barcode_scanner_sn", label: "Barcode Scanner S/N", type: "text" },
  { key: "pc_model", label: "PC Model", type: "text" },
  { key: "pc_sn_tag", label: "PC S/N Tag", type: "text" },
  { key: "remark", label: "Remark", type: "textarea" },
];

async function renderMachineDetail(code) {
  viewRoot.innerHTML = `<div class="loading">Loading...</div>`;
  let machine;
  try {
    machine = await api(`/api/machines/${encodeURIComponent(code)}`);
  } catch (e) {
    viewRoot.innerHTML = `<div class="empty-state">Machine "${escapeHtml(code)}" not found.</div>`;
    return;
  }

  const fieldsHtml = MACHINE_FIELDS.map((f) => {
    const val = machine[f.key] ?? "";
    if (f.type === "textarea") {
      return `<div class="field"><label>${f.label}</label><textarea id="mf-${f.key}">${escapeHtml(val)}</textarea></div>`;
    }
    return `<div class="field"><label>${f.label}</label><input id="mf-${f.key}" type="${f.type}" value="${escapeHtml(val)}" placeholder="${f.ph || ""}" /></div>`;
  }).join("");

  const endUsers = [...new Set(machine.batteries.map((b) => b.end_user).filter(Boolean))];

  viewRoot.innerHTML = `
    <div class="detail-header">
      <button class="back-btn" id="back-btn">←</button>
      <div class="detail-title">${escapeHtml(machine.code)}</div>
      ${machine.system ? `<span class="badge active">${escapeHtml(machine.system)}</span>` : ""}
    </div>

    <div class="detail-grid">
      <div class="panel">
        <h3>Machine Info</h3>
        <div class="form-grid form-grid-2">
          ${fieldsHtml}
        </div>
        <div class="form-actions" style="margin-top:14px">
          <button class="btn primary" id="save-machine-detail-btn">Save Changes</button>
        </div>
      </div>

      <div class="panel">
        <h3>Linked Batteries${endUsers.length ? " · " + escapeHtml(endUsers.join(", ")) : ""}</h3>
        <div class="linked-batteries">
          ${
            machine.batteries.length
              ? machine.batteries.map((b) => `
                <a class="linked-battery" href="#battery/${encodeURIComponent(b.serial)}">
                  <span class="serial">${escapeHtml(b.serial)}</span>
                  <span class="badge ${b.status}">${STATUS_LABEL[b.status]}</span>
                  <span class="lb-health ${healthClass(b.health_percent)}">${b.health_percent != null ? b.health_percent + "%" : "—"}</span>
                </a>
              `).join("")
              : `<div class="empty-state">No batteries linked to this machine</div>`
          }
        </div>
        <div class="lb-hint">To change which batteries are linked, open a battery and set its “Machine In Use”.</div>

        <h3 style="margin-top:22px">Machine Notes</h3>
        <div class="timeline" id="m-timeline">
          ${
            machine.logs.length
              ? machine.logs.map(machineLogHtml).join("")
              : `<div class="empty-state">No notes yet</div>`
          }
        </div>
        <div class="add-note-row">
          <input id="m-note-input" type="text" placeholder="Add a note e.g. calibration done / repair" />
          <button class="btn ghost small" id="m-add-note-btn">Add</button>
        </div>
      </div>
    </div>
  `;

  document.getElementById("back-btn").onclick = () => navigate("machines");

  document.getElementById("save-machine-detail-btn").onclick = async () => {
    const payload = {};
    for (const f of MACHINE_FIELDS) {
      const raw = document.getElementById(`mf-${f.key}`).value;
      payload[f.key] = raw.trim() === "" ? null : raw.trim();
    }
    try {
      await api(`/api/machines/${encodeURIComponent(machine.code)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast("Machine saved");
      renderMachineDetail(machine.code);
    } catch (e) {
      toast(e.message, true);
    }
  };

  document.getElementById("m-add-note-btn").onclick = async () => {
    const input = document.getElementById("m-note-input");
    if (!input.value.trim()) return;
    try {
      await api(`/api/machines/${encodeURIComponent(machine.code)}/logs`, {
        method: "POST",
        body: JSON.stringify({ description: input.value.trim() }),
      });
      renderMachineDetail(machine.code);
    } catch (e) {
      toast(e.message, true);
    }
  };

  bindMachineLogActions(machine.code);
}

function machineLogHtml(log) {
  return `
    <div class="timeline-item" data-log-id="${log.id}">
      <div class="timeline-dot note"></div>
      <div class="timeline-body" data-view>
        <div class="desc">${escapeHtml(log.description)}</div>
        <div class="ts">${fmtDateTime(log.timestamp)}</div>
      </div>
      <div class="timeline-actions">
        <button class="edit-log" title="Edit">✎</button>
        <button class="delete delete-log" title="Delete">🗑</button>
      </div>
    </div>
  `;
}

function bindMachineLogActions(code) {
  document.querySelectorAll("#m-timeline .timeline-item").forEach((item) => {
    const logId = item.dataset.logId;
    item.querySelector(".edit-log").onclick = () => {
      const body = item.querySelector("[data-view]");
      const currentText = body.querySelector(".desc").textContent;
      body.innerHTML = `
        <textarea>${escapeHtml(currentText)}</textarea>
        <div class="timeline-edit-actions">
          <button class="btn primary small" data-save>Save</button>
          <button class="btn ghost small" data-cancel>Cancel</button>
        </div>
      `;
      body.querySelector("[data-save]").onclick = async () => {
        const newText = body.querySelector("textarea").value.trim();
        if (!newText) return;
        try {
          await api(`/api/machines/${encodeURIComponent(code)}/logs/${logId}`, {
            method: "PATCH",
            body: JSON.stringify({ description: newText }),
          });
          renderMachineDetail(code);
        } catch (e) {
          toast(e.message, true);
        }
      };
      body.querySelector("[data-cancel]").onclick = () => renderMachineDetail(code);
    };
    item.querySelector(".delete-log").onclick = async () => {
      if (!confirm("Delete this note?")) return;
      try {
        await api(`/api/machines/${encodeURIComponent(code)}/logs/${logId}`, {
          method: "DELETE",
        });
        renderMachineDetail(code);
      } catch (e) {
        toast(e.message, true);
      }
    };
  });
}

/* ---------------- Excel Sync ---------------- */
const SYNC_FIELD_LABELS = {
  customer: "Customer",
  division: "Division",
  contact_person: "Contact Person",
  contact_phone: "Contact Phone",
  system: "System",
  gauge_block_sn: "Gauge Block S/N",
  wifi_model: "Wi-Fi Model",
  wifi_sn: "Wi-Fi S/N",
  barcode_scanner_sn: "Barcode Scanner S/N",
  pc_model: "PC Model",
  pc_sn_tag: "PC S/N Tag",
  remark: "Remark",
  install: "Installation Day",
};

function syncRowsHtml(entries, kind) {
  return entries
    .map((e) => `
      <tr>
        <td class="nowrap"><b>${escapeHtml(e.code)}</b></td>
        <td>${escapeHtml(SYNC_FIELD_LABELS[e.field] || e.field)}</td>
        <td class="${kind === "to_app" ? "sync-win" : ""}">${escapeHtml(e.excel) || "<em>(empty)</em>"}</td>
        <td class="${kind === "to_excel" ? "sync-win" : ""}">${escapeHtml(e.app) || "<em>(empty)</em>"}</td>
        ${
          kind === "conflict"
            ? `<td class="nowrap">
                 <label class="pick"><input type="radio" name="c-${escapeHtml(e.code)}.${e.field}" value="excel" /> Excel</label>
                 <label class="pick"><input type="radio" name="c-${escapeHtml(e.code)}.${e.field}" value="app" /> App</label>
               </label></td>`
            : ""
        }
      </tr>`)
    .join("");
}

async function renderSync() {
  viewRoot.innerHTML = `<div class="loading">Reading the workbook from SharePoint…</div>`;

  let status;
  try {
    status = await api("/api/sync/status");
  } catch (e) {
    viewRoot.innerHTML = `<div class="empty-state">Sync unavailable: ${escapeHtml(e.message)}</div>`;
    return;
  }
  if (!status.configured) {
    viewRoot.innerHTML = `
      <div class="section-head"><h2>Excel Sync</h2></div>
      <div class="panel"><div class="empty-state">
        Microsoft Graph is not configured on this server.<br />
        Set GRAPH_CLIENT_ID, GRAPH_TENANT_ID, GRAPH_CLIENT_SECRET,
        SHAREPOINT_HOSTNAME and SHAREPOINT_SITE_PATH.
      </div></div>`;
    return;
  }

  let diff;
  try {
    diff = await api("/api/sync/preview");
  } catch (e) {
    viewRoot.innerHTML = `<div class="empty-state">Could not read the workbook: ${escapeHtml(e.message)}</div>`;
    return;
  }

  const f = status.file || {};
  const inSync =
    diff.to_app.length === 0 && diff.to_excel.length === 0 && diff.conflicts.length === 0;

  viewRoot.innerHTML = `
    <div class="section-head">
      <h2>Excel Sync</h2>
      <button class="btn ghost small" id="refresh-sync">Refresh</button>
    </div>

    <div class="panel" style="margin-bottom:18px">
      <div class="sync-file">
        <div><span class="lbl">Workbook</span><b>${escapeHtml(f.name)}</b></div>
        <div><span class="lbl">Last modified</span>${fmtDateTime(f.lastModifiedDateTime)}</div>
        <div><span class="lbl">Machines</span>Excel ${diff.excel_machine_count} · App ${diff.app_machine_count}</div>
      </div>
    </div>

    ${
      inSync
        ? `<div class="panel"><div class="empty-state">✅ Everything is in sync — no differences found.</div></div>`
        : `
      ${diff.conflicts.length ? `
        <div class="panel sync-block">
          <h3 class="sync-h conflict">⚠ Conflicts — changed on both sides (${diff.conflicts.length})</h3>
          <p class="sync-note">Pick which side wins. Anything left unpicked is skipped, not overwritten.</p>
          <div class="table-scroll"><table class="tests-table">
            <thead><tr><th>Machine</th><th>Field</th><th>Excel value</th><th>App value</th><th>Keep</th></tr></thead>
            <tbody>${syncRowsHtml(diff.conflicts, "conflict")}</tbody>
          </table></div>
        </div>` : ""}

      ${diff.to_app.length ? `
        <div class="panel sync-block">
          <h3 class="sync-h">Excel → App (${diff.to_app.length})</h3>
          <div class="table-scroll"><table class="tests-table">
            <thead><tr><th>Machine</th><th>Field</th><th>Excel value</th><th>App value</th></tr></thead>
            <tbody>${syncRowsHtml(diff.to_app, "to_app")}</tbody>
          </table></div>
        </div>` : ""}

      ${diff.to_excel.length ? `
        <div class="panel sync-block">
          <h3 class="sync-h">App → Excel (${diff.to_excel.length})</h3>
          <p class="sync-note">These are written into the SharePoint workbook only if you tick the write option below.</p>
          <div class="table-scroll"><table class="tests-table">
            <thead><tr><th>Machine</th><th>Field</th><th>Excel value</th><th>App value</th></tr></thead>
            <tbody>${syncRowsHtml(diff.to_excel, "to_excel")}</tbody>
          </table></div>
        </div>` : ""}
      `
    }

    ${
      diff.only_in_excel.length || diff.only_in_app.length
        ? `<div class="panel sync-block">
            <h3 class="sync-h">Not matched</h3>
            <div class="sync-note">Only in Excel: ${diff.only_in_excel.map(escapeHtml).join(", ") || "—"}</div>
            <div class="sync-note">Only in App: ${diff.only_in_app.map(escapeHtml).join(", ") || "—"}</div>
          </div>`
        : ""
    }

    ${
      inSync
        ? ""
        : `<div class="panel sync-actions">
            <label class="write-toggle">
              <input type="checkbox" id="write-excel" />
              <span>Also write “App → Excel” changes into the SharePoint workbook
              <b>(a timestamped backup copy is saved first)</b></span>
            </label>
            <button class="btn primary" id="apply-sync">Apply Sync</button>
          </div>`
    }
  `;

  document.getElementById("refresh-sync").onclick = () => renderSync();

  const applyBtn = document.getElementById("apply-sync");
  if (applyBtn) {
    applyBtn.onclick = async () => {
      const writeExcel = document.getElementById("write-excel").checked;
      const resolution = {};
      viewRoot.querySelectorAll('input[type=radio]:checked').forEach((r) => {
        resolution[r.name.slice(2)] = r.value;
      });
      if (writeExcel && !confirm(
        "This will modify the shared workbook on SharePoint.\n" +
        "A backup copy is saved first. Continue?"
      )) return;

      applyBtn.disabled = true;
      applyBtn.textContent = "Applying…";
      try {
        const res = await api("/api/sync/apply", {
          method: "POST",
          body: JSON.stringify({
            write_excel: writeExcel,
            conflict_resolution: resolution,
            backup_first: true,
          }),
        });
        let msg = `Applied — Excel→App: ${res.applied_to_app}, App→Excel: ${res.applied_to_excel}`;
        if (res.skipped_conflicts) msg += `, skipped conflicts: ${res.skipped_conflicts}`;
        toast(msg);
        renderSync();
      } catch (e) {
        toast(e.message, true);
        applyBtn.disabled = false;
        applyBtn.textContent = "Apply Sync";
      }
    };
  }
}

/* ---------------- Modals ---------------- */
function openModal(html, wide = false) {
  modalRoot.innerHTML = `<div class="modal-overlay" id="overlay"><div class="modal ${wide ? "wide" : ""}">${html}</div></div>`;
  document.getElementById("overlay").onclick = (e) => {
    if (e.target.id === "overlay") closeModal();
  };
}
function closeModal() {
  modalRoot.innerHTML = "";
}

async function openNewBatteryModal() {
  const machines = state.machines.length ? state.machines : (state.machines = await api("/api/machines"));
  openModal(`
    <h2>New Battery</h2>
    <div class="form-grid">
      <div class="field">
        <label>Serial (leave blank to auto-generate)</label>
        <input id="m-serial" type="text" placeholder="GNB-0001" />
      </div>
      <div class="field">
        <label>Machine In Use</label>
        <select id="m-machine">
          <option value="">— Unassigned —</option>
          ${machines.map((m) => `<option value="${escapeHtml(m.code)}">${escapeHtml(m.code)}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label>End-User</label>
        <input id="m-enduser" type="text" placeholder="User name" />
      </div>
      <div class="field">
        <label>Commission Date</label>
        <input id="m-commission" type="date" value="${new Date().toISOString().slice(0, 10)}" />
      </div>
    </div>
    <div class="form-actions">
      <button class="btn ghost" id="cancel-btn">Cancel</button>
      <button class="btn primary" id="create-btn">Create</button>
    </div>
  `);
  document.getElementById("cancel-btn").onclick = closeModal;
  document.getElementById("create-btn").onclick = async () => {
    try {
      const payload = {
        serial: document.getElementById("m-serial").value.trim() || null,
        machine_code: document.getElementById("m-machine").value || null,
        end_user: document.getElementById("m-enduser").value || null,
        commission_date: document.getElementById("m-commission").value || null,
      };
      const battery = await api("/api/batteries", { method: "POST", body: JSON.stringify(payload) });
      closeModal();
      toast(`Created battery ${battery.serial}`);
      navigate(`battery/${battery.serial}`);
    } catch (e) {
      toast(e.message, true);
    }
  };
}

function openNewMachineModal() {
  openModal(`
    <h2>New Machine</h2>
    <div class="form-grid">
      <div class="field">
        <label>Machine Code</label>
        <input id="mm-code" type="text" placeholder="GN-001" />
      </div>
      <div class="field">
        <label>Customer</label>
        <input id="mm-customer" type="text" placeholder="Customer / company name" />
      </div>
      <div class="field">
        <label>Division</label>
        <input id="mm-division" type="text" placeholder="e.g. QA, Body, BQS" />
      </div>
      <div class="field">
        <label>Contact Person</label>
        <input id="mm-contact" type="text" placeholder="Contact name" />
      </div>
      <div class="field">
        <label>Contact Phone</label>
        <input id="mm-phone" type="text" placeholder="Phone number" />
      </div>
      <div class="field">
        <label>Install Date</label>
        <input id="mm-install" type="date" />
      </div>
      <div class="field">
        <label>Remark</label>
        <textarea id="mm-remark" placeholder="Additional remark"></textarea>
      </div>
    </div>
    <div class="form-actions">
      <button class="btn ghost" id="cancel-btn">Cancel</button>
      <button class="btn primary" id="create-btn">Create</button>
    </div>
  `, true);
  document.getElementById("cancel-btn").onclick = closeModal;
  document.getElementById("create-btn").onclick = async () => {
    try {
      const code = document.getElementById("mm-code").value.trim();
      if (!code) { toast("Machine code is required", true); return; }
      await api("/api/machines", {
        method: "POST",
        body: JSON.stringify({
          code,
          customer: document.getElementById("mm-customer").value || null,
          division: document.getElementById("mm-division").value || null,
          contact_person: document.getElementById("mm-contact").value || null,
          contact_phone: document.getElementById("mm-phone").value || null,
          install_date: document.getElementById("mm-install").value || null,
          remark: document.getElementById("mm-remark").value || null,
        }),
      });
      closeModal();
      toast(`Machine ${code} created`);
      state.machines = await api("/api/machines");
      route();
    } catch (e) {
      toast(e.message, true);
    }
  };
}

async function openEditMachineModal(code, onSaved) {
  let machine;
  try {
    const all = await api("/api/machines");
    machine = all.find((m) => m.code === code);
  } catch (e) {
    toast(e.message, true);
    return;
  }
  if (!machine) {
    toast(`Machine ${code} not found`, true);
    return;
  }

  openModal(`
    <h2>Edit Machine — ${escapeHtml(machine.code)}</h2>
    <div class="form-grid">
      <div class="field">
        <label>Customer</label>
        <input id="em-customer" type="text" value="${escapeHtml(machine.customer)}" />
      </div>
      <div class="field">
        <label>Division</label>
        <input id="em-division" type="text" value="${escapeHtml(machine.division)}" />
      </div>
      <div class="field">
        <label>Contact Person</label>
        <input id="em-contact" type="text" value="${escapeHtml(machine.contact_person)}" />
      </div>
      <div class="field">
        <label>Contact Phone</label>
        <input id="em-phone" type="text" value="${escapeHtml(machine.contact_phone)}" />
      </div>
      <div class="field">
        <label>Install Date</label>
        <input id="em-install" type="date" value="${machine.install_date || ""}" />
      </div>
      <div class="field">
        <label>Remark</label>
        <textarea id="em-remark">${escapeHtml(machine.remark)}</textarea>
      </div>
    </div>
    <div class="form-actions">
      <button class="btn ghost" id="cancel-btn">Cancel</button>
      <button class="btn primary" id="save-machine-btn">Save</button>
    </div>
  `, true);

  document.getElementById("cancel-btn").onclick = closeModal;
  document.getElementById("save-machine-btn").onclick = async () => {
    try {
      await api(`/api/machines/${encodeURIComponent(machine.code)}`, {
        method: "PATCH",
        body: JSON.stringify({
          customer: document.getElementById("em-customer").value || null,
          division: document.getElementById("em-division").value || null,
          contact_person: document.getElementById("em-contact").value || null,
          contact_phone: document.getElementById("em-phone").value || null,
          install_date: document.getElementById("em-install").value || null,
          remark: document.getElementById("em-remark").value || null,
        }),
      });
      closeModal();
      toast(`Machine ${machine.code} updated`);
      state.machines = await api("/api/machines");
      if (onSaved) onSaved();
    } catch (e) {
      toast(e.message, true);
    }
  };
}

/* ---------------- Global bindings ---------------- */
document.getElementById("btn-new-battery").onclick = openNewBatteryModal;
document.getElementById("btn-new-machine").onclick = openNewMachineModal;
document.getElementById("btn-machines").onclick = () => navigate("machines");
document.getElementById("btn-sync").onclick = () => navigate("sync");
document.getElementById("search-btn").onclick = () => {
  navigate("");
  renderDashboard();
};
document.getElementById("search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    navigate("");
    renderDashboard();
  }
});

route();
