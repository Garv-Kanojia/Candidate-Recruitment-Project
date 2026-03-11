// ── Configuration ────────────────────────────────────────────────────────────
const API_BASE = "https://megatron14-candidate-recruitment-backend.hf.space";

// ── Auth Guard ──────────────────────────────────────────────────────────────
if (!sessionStorage.getItem("auth_token")) {
    window.location.replace("login.html");
}

// Show user email & wire logout
const userEmailEl = document.getElementById("user-email");
const logoutBtn = document.getElementById("logout-btn");

if (userEmailEl) {
    userEmailEl.textContent = sessionStorage.getItem("auth_email") || "";
}

if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
        sessionStorage.removeItem("auth_token");
        sessionStorage.removeItem("auth_email");
        window.location.replace("login.html");
    });
}

// ── DOM refs ────────────────────────────────────────────────────────────────
const evaluateFile = document.getElementById("evaluate-file");
const evaluateDrop = document.getElementById("evaluate-drop");
const evaluateFileName = document.getElementById("evaluate-file-name");
const evaluateBtn = document.getElementById("evaluate-btn");
const evaluateResults = document.getElementById("evaluate-results");
const jdInput = document.getElementById("jd-input");
const testLinkInput = document.getElementById("test-link-input");

const scheduleFile = document.getElementById("schedule-file");
const scheduleDrop = document.getElementById("schedule-drop");
const scheduleFileName = document.getElementById("schedule-file-name");
const scheduleBtn = document.getElementById("schedule-btn");
const scheduleResults = document.getElementById("schedule-results");

// Dashboard stat elements
const evalTotalEl = document.getElementById("eval-total");
const evalAcceptedEl = document.getElementById("eval-accepted");
const evalRejectedEl = document.getElementById("eval-rejected");
const evalPctEl = document.getElementById("eval-pct");
const schedTotalEl = document.getElementById("sched-total");
const schedScheduledEl = document.getElementById("sched-scheduled");
const schedRejectedEl = document.getElementById("sched-rejected");
const schedPctEl = document.getElementById("sched-pct");
const vacancyDisplay = document.getElementById("vacancy-display");

// Vacancy editor elements
const vacancyEditBtn = document.getElementById("vacancy-edit-btn");
const vacancyEditor = document.getElementById("vacancy-editor");
const vacancyInput = document.getElementById("vacancy-input");
const vacancySaveBtn = document.getElementById("vacancy-save-btn");
const vacancyCancelBtn = document.getElementById("vacancy-cancel-btn");

// Scheduling option elements
const interviewDateInput = document.getElementById("interview-date");
const interviewStartTime = document.getElementById("interview-start-time");
const interviewDuration = document.getElementById("interview-duration");
const interviewGap = document.getElementById("interview-gap");

// ── State ───────────────────────────────────────────────────────────────────
let evaluateCsvFile = null;
let scheduleCsvFile = null;

function updateEvaluateBtnState() {
    evaluateBtn.disabled = !(evaluateCsvFile && jdInput.value.trim() && testLinkInput.value.trim());
}

jdInput.addEventListener("input", updateEvaluateBtnState);
testLinkInput.addEventListener("input", updateEvaluateBtnState);

// Set default interview date to tomorrow
(function setDefaultDate() {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    interviewDateInput.value = tomorrow.toISOString().split("T")[0];
})();

// ── Drag-and-Drop + Click helpers ───────────────────────────────────────────
function setupUploadArea(dropArea, fileInput, onFileSelected) {
    dropArea.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) onFileSelected(fileInput.files[0]);
    });

    dropArea.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropArea.classList.add("drag-over");
    });

    dropArea.addEventListener("dragleave", () => {
        dropArea.classList.remove("drag-over");
    });

    dropArea.addEventListener("drop", (e) => {
        e.preventDefault();
        dropArea.classList.remove("drag-over");
        const file = e.dataTransfer.files[0];
        if (file) onFileSelected(file);
    });
}

function validateCsv(file) {
    if (!file.name.toLowerCase().endsWith(".csv")) {
        alert("Please upload a .csv file.");
        return false;
    }
    return true;
}

// ── Wire up Evaluate upload ─────────────────────────────────────────────────
setupUploadArea(evaluateDrop, evaluateFile, (file) => {
    if (!validateCsv(file)) return;
    evaluateCsvFile = file;
    evaluateFileName.textContent = file.name;
    evaluateDrop.classList.add("has-file");
    updateEvaluateBtnState();
});

// ── Wire up Schedule upload ─────────────────────────────────────────────────
setupUploadArea(scheduleDrop, scheduleFile, (file) => {
    if (!validateCsv(file)) return;
    scheduleCsvFile = file;
    scheduleFileName.textContent = file.name;
    scheduleDrop.classList.add("has-file");
    scheduleBtn.disabled = false;
});

// ── API helpers ─────────────────────────────────────────────────────────────
function setLoading(btn, loading) {
    const text = btn.querySelector(".btn-text");
    const loader = btn.querySelector(".btn-loader");
    if (loading) {
        text.hidden = true;
        loader.hidden = false;
        btn.disabled = true;
    } else {
        text.hidden = false;
        loader.hidden = true;
        btn.disabled = false;
    }
}

async function uploadFile(endpoint, file, params = {}, formFields = {}) {
    const url = new URL(endpoint, API_BASE);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));

    const form = new FormData();
    form.append("file", file);
    Object.entries(formFields).forEach(([k, v]) => form.append(k, v));

    const headers = {};
    const token = sessionStorage.getItem("auth_token");
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    const res = await fetch(url.toString(), { method: "POST", body: form, headers });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Server error ${res.status}`);
    }
    return res.json();
}

// ── Render helpers ──────────────────────────────────────────────────────────
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function renderEvaluateResults(data) {
    evaluateResults.hidden = false;

    const summaryHtml = `
    <div class="results-summary">
      <span class="stat stat--total">Total: ${data.total_candidates}</span>
      <span class="stat stat--success">Selected: ${data.selected}</span>
      <span class="stat stat--error">Rejected: ${data.rejected}</span>
      ${data.errors ? `<span class="stat stat--warning">Errors: ${data.errors}</span>` : ""}
    </div>`;

    let tableHtml = "";
    if (data.results && data.results.length) {
        tableHtml = `
      <div class="result-table-wrap">
        <table class="result-table">
          <thead><tr>
            <th>Name</th><th>Email</th><th>Verdict</th><th>Reason</th>
          </tr></thead>
          <tbody>
            ${data.results.map((r) => `
              <tr>
                <td>${escapeHtml(r.name || "")}</td>
                <td>${escapeHtml(r.email || "")}</td>
                <td><span class="badge badge--${r.verdict === "YES" ? "yes" : r.verdict === "NO" ? "no" : "err"}">${escapeHtml(r.verdict)}</span></td>
                <td>${escapeHtml(r.reason || r.analysis?.summary || "")}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    }

    evaluateResults.innerHTML = summaryHtml + tableHtml;
}

function renderScheduleResults(data) {
    scheduleResults.hidden = false;

    const summaryHtml = `
    <div class="results-summary">
      <span class="stat stat--total">Total: ${data.total_candidates}</span>
      <span class="stat stat--success">Scheduled: ${data.interviews_scheduled || 0}</span>
      <span class="stat stat--error">Rejected: ${data.rejected}</span>
      ${data.schedule_errors ? `<span class="stat stat--warning">Errors: ${data.schedule_errors}</span>` : ""}
    </div>`;

    let tableHtml = "";
    if (data.scheduled && data.scheduled.length) {
        tableHtml = `
      <div class="result-table-wrap">
        <table class="result-table">
          <thead><tr>
            <th>Name</th><th>Email</th><th>LA</th><th>Code</th><th>Time</th><th>Meet</th>
          </tr></thead>
          <tbody>
            ${data.scheduled.map((r) => `
              <tr>
                <td>${escapeHtml(r.name || "")}</td>
                <td>${escapeHtml(r.email || "")}</td>
                <td>${r.test_la}</td>
                <td>${r.test_code}</td>
                <td>${new Date(r.scheduled_time).toLocaleString()}</td>
                <td>${r.meet_link !== "N/A" ? `<a href="${escapeHtml(r.meet_link)}" target="_blank" rel="noopener">Join</a>` : "N/A"}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    }

    if (data.message) {
        tableHtml += `<p style="margin-top:.75rem;color:var(--clr-text-muted);font-size:.85rem">${escapeHtml(data.message)}</p>`;
    }

    if (data.warning) {
        tableHtml += `<div class="warning-banner" style="margin-top:.75rem">${escapeHtml(data.warning)}</div>`;
    }

    scheduleResults.innerHTML = summaryHtml + tableHtml;
}

function showError(container, msg) {
    container.hidden = false;
    container.innerHTML = `<div class="error-banner">${escapeHtml(msg)}</div>`;
}

// ── Dashboard Stats ─────────────────────────────────────────────────────────
async function fetchStats() {
    try {
        const token = sessionStorage.getItem("auth_token");
        const res = await fetch(`${API_BASE}/stats`, {
            headers: { "Authorization": `Bearer ${token}` },
        });
        if (!res.ok) return;
        const data = await res.json();

        // Evaluation
        evalTotalEl.textContent = data.evaluation.total;
        evalAcceptedEl.textContent = data.evaluation.accepted;
        evalRejectedEl.textContent = data.evaluation.rejected;
        evalPctEl.textContent = data.evaluation.acceptance_pct + "%";

        // Scheduling
        schedTotalEl.textContent = data.scheduling.total;
        schedScheduledEl.textContent = data.scheduling.scheduled;
        schedRejectedEl.textContent = data.scheduling.rejected;
        schedPctEl.textContent = data.scheduling.acceptance_pct + "%";

        // Vacancy
        vacancyDisplay.textContent = data.vacancy_count;
        vacancyInput.value = data.vacancy_count;
    } catch (e) {
        console.error("Failed to fetch stats:", e);
    }
}

// Fetch stats on page load
fetchStats();

// ── Vacancy Editor ──────────────────────────────────────────────────────────
vacancyEditBtn.addEventListener("click", () => {
    vacancyEditor.hidden = false;
    vacancyEditBtn.hidden = true;
    vacancyInput.focus();
});

vacancyCancelBtn.addEventListener("click", () => {
    vacancyEditor.hidden = true;
    vacancyEditBtn.hidden = false;
});

vacancySaveBtn.addEventListener("click", async () => {
    const value = parseInt(vacancyInput.value, 10);
    if (isNaN(value) || value < 1) return;
    try {
        const token = sessionStorage.getItem("auth_token");
        const res = await fetch(`${API_BASE}/settings`, {
            method: "PUT",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ vacancy_count: value }),
        });
        if (res.ok) {
            const data = await res.json();
            vacancyDisplay.textContent = data.vacancy_count;
        }
    } catch (e) {
        console.error("Failed to update vacancy:", e);
    }
    vacancyEditor.hidden = true;
    vacancyEditBtn.hidden = false;
});

// ── Button handlers ─────────────────────────────────────────────────────────
evaluateBtn.addEventListener("click", async () => {
    if (!evaluateCsvFile) return;
    setLoading(evaluateBtn, true);
    evaluateResults.hidden = true;
    try {
        const data = await uploadFile(
            "/evaluate",
            evaluateCsvFile,
            { send_emails: true },
            { jd: jdInput.value.trim(), test_link: testLinkInput.value.trim() }
        );
        renderEvaluateResults(data);
        fetchStats();
    } catch (err) {
        showError(evaluateResults, err.message);
    } finally {
        setLoading(evaluateBtn, false);
    }
});

scheduleBtn.addEventListener("click", async () => {
    if (!scheduleCsvFile) return;
    setLoading(scheduleBtn, true);
    scheduleResults.hidden = true;
    try {
        const data = await uploadFile(
            "/schedule",
            scheduleCsvFile,
            {},
            {
                start_date: interviewDateInput.value,
                start_time: interviewStartTime.value,
                duration: interviewDuration.value,
                gap: interviewGap.value,
            }
        );
        renderScheduleResults(data);
        fetchStats();
    } catch (err) {
        showError(scheduleResults, err.message);
    } finally {
        setLoading(scheduleBtn, false);
    }
});
