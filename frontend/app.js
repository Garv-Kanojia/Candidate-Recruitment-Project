// ── Configuration ────────────────────────────────────────────────────────────
// Replace with your Hugging Face Spaces backend URL
const API_BASE = "https://YOUR-HF-SPACE.hf.space";

// ── DOM refs ────────────────────────────────────────────────────────────────
const evaluateFile = document.getElementById("evaluate-file");
const evaluateDrop = document.getElementById("evaluate-drop");
const evaluateFileName = document.getElementById("evaluate-file-name");
const evaluateBtn = document.getElementById("evaluate-btn");
const evaluateResults = document.getElementById("evaluate-results");
const sendEmailsCheckbox = document.getElementById("send-emails");

const scheduleFile = document.getElementById("schedule-file");
const scheduleDrop = document.getElementById("schedule-drop");
const scheduleFileName = document.getElementById("schedule-file-name");
const scheduleBtn = document.getElementById("schedule-btn");
const scheduleResults = document.getElementById("schedule-results");

// ── State ───────────────────────────────────────────────────────────────────
let evaluateCsvFile = null;
let scheduleCsvFile = null;

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
    evaluateBtn.disabled = false;
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

async function uploadFile(endpoint, file, params = {}) {
    const url = new URL(endpoint, API_BASE);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));

    const form = new FormData();
    form.append("file", file);

    const res = await fetch(url.toString(), { method: "POST", body: form });

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

    scheduleResults.innerHTML = summaryHtml + tableHtml;
}

function showError(container, msg) {
    container.hidden = false;
    container.innerHTML = `<div class="error-banner">${escapeHtml(msg)}</div>`;
}

// ── Button handlers ─────────────────────────────────────────────────────────
evaluateBtn.addEventListener("click", async () => {
    if (!evaluateCsvFile) return;
    setLoading(evaluateBtn, true);
    evaluateResults.hidden = true;
    try {
        const data = await uploadFile("/evaluate", evaluateCsvFile, {
            send_emails: sendEmailsCheckbox.checked,
        });
        renderEvaluateResults(data);
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
        const data = await uploadFile("/schedule", scheduleCsvFile);
        renderScheduleResults(data);
    } catch (err) {
        showError(scheduleResults, err.message);
    } finally {
        setLoading(scheduleBtn, false);
    }
});
