// ── Configuration ────────────────────────────────────────────────────────────
const API_BASE = "https://megatron14-candidate-recruitment-backend.hf.space";

// Supabase config — replace with your project values
const SUPABASE_URL = "https://YOUR_PROJECT.supabase.co";
const SUPABASE_ANON_KEY = "YOUR_ANON_KEY";

// ── Auth Guard ──────────────────────────────────────────────────────────────
if (!sessionStorage.getItem("auth_token")) {
    window.location.replace("login.html");
}

const AUTH_TOKEN = sessionStorage.getItem("auth_token");
const AUTH_USER_ID = sessionStorage.getItem("auth_user_id");

// ── Supabase Client ─────────────────────────────────────────────────────────
const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

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
        sessionStorage.removeItem("auth_user_id");
        window.location.replace("login.html");
    });
}

// ── DOM refs ────────────────────────────────────────────────────────────────
const evaluateFile = document.getElementById("evaluate-file");
const evaluateDrop = document.getElementById("evaluate-drop");
const evaluateFileName = document.getElementById("evaluate-file-name");
const evaluateBtn = document.getElementById("evaluate-btn");
const jdInput = document.getElementById("jd-input");
const testLinkInput = document.getElementById("test-link-input");
const sendEmailsToggle = document.getElementById("send-emails-toggle");

// Live results panel
const liveResultsPanel = document.getElementById("live-results-panel");
const liveResultsProgress = document.getElementById("live-results-progress");
const liveResultsTbody = document.getElementById("live-results-tbody");

const scheduleFile = document.getElementById("schedule-file");
const scheduleDrop = document.getElementById("schedule-drop");
const scheduleFileName = document.getElementById("schedule-file-name");
const scheduleBtn = document.getElementById("schedule-btn");

// Dashboard stat elements
const evalTotalEl = document.getElementById("eval-total");
const evalAcceptedEl = document.getElementById("eval-accepted");
const evalRejectedEl = document.getElementById("eval-rejected");
const evalPctEl = document.getElementById("eval-pct");
const schedTotalEl = document.getElementById("sched-total");
const schedScheduledEl = document.getElementById("sched-scheduled");
const schedRejectedEl = document.getElementById("sched-rejected");
const schedPctEl = document.getElementById("sched-pct");

// Last results list elements
const evalLastResultsEl = document.getElementById("eval-last-results");
const schedLastResultsEl = document.getElementById("sched-last-results");

// Scheduling option elements
const interviewDateInput = document.getElementById("interview-date");
const interviewStartTime = document.getElementById("interview-start-time");
const interviewDuration = document.getElementById("interview-duration");
const interviewGap = document.getElementById("interview-gap");

// Settings elements
const vacancyCountInput = document.getElementById("vacancy-count");
const saveSettingsBtn = document.getElementById("save-settings-btn");

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

async function uploadFile(endpoint, file, formFields = {}) {
    const url = new URL(endpoint, API_BASE);

    const form = new FormData();
    form.append("file", file);
    Object.entries(formFields).forEach(([k, v]) => form.append(k, v));

    const headers = {};
    if (AUTH_TOKEN) {
        headers["Authorization"] = `Bearer ${AUTH_TOKEN}`;
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

function renderEvalLastResults(containerEl, items) {
    if (!items || items.length === 0) {
        containerEl.innerHTML = '<p class="prev-results-empty">No results yet</p>';
        return;
    }
    containerEl.innerHTML = `
      <table class="prev-results-table">
        <thead><tr>
          <th>Name</th><th>Email</th><th>Score</th><th>Reason</th><th>Resume</th>
        </tr></thead>
        <tbody>
          ${items.map((item) => {
        const name = escapeHtml(item.name || "");
        const email = escapeHtml(item.email || "");
        const verdict = item.verdict || "";
        const reason = escapeHtml(item.reason || "");
        const resumeLink = item.resume_link || "";
        const badgeClass = verdict === "YES" ? "yes" : verdict === "NO" ? "no" : "err";
        const resumeHtml = resumeLink
            ? `<a href="${escapeHtml(resumeLink)}" target="_blank" rel="noopener">View</a>`
            : "—";
        return `<tr>
                <td>${name}</td>
                <td>${email}</td>
                <td><span class="badge badge--${badgeClass}">${escapeHtml(verdict)}</span></td>
                <td class="reason-cell">${reason}</td>
                <td>${resumeHtml}</td>
              </tr>`;
    }).join("")}
        </tbody>
      </table>`;
}

function renderSchedLastResults(containerEl, items) {
    if (!items || items.length === 0) {
        containerEl.innerHTML = '<p class="prev-results-empty">No results yet</p>';
        return;
    }
    containerEl.innerHTML = `
      <table class="prev-results-table">
        <thead><tr>
          <th>Name</th><th>Email</th><th>Reasoning Score</th><th>Coding Score</th><th>Link</th>
        </tr></thead>
        <tbody>
          ${items.map((item) => {
        const name = escapeHtml(item.name || "");
        const email = escapeHtml(item.email || "");
        const testLa = item.test_la != null ? item.test_la : "—";
        const testCode = item.test_code != null ? item.test_code : "—";
        const meetLink = item.meet_link || "";
        const linkHtml = meetLink && meetLink !== "N/A"
            ? `<a href="${escapeHtml(meetLink)}" target="_blank" rel="noopener">Join</a>`
            : "—";
        return `<tr>
                <td>${name}</td>
                <td>${email}</td>
                <td>${testLa}</td>
                <td>${testCode}</td>
                <td>${linkHtml}</td>
              </tr>`;
    }).join("")}
        </tbody>
      </table>`;
}

// ── Dashboard Stats ─────────────────────────────────────────────────────────
function renderLastResults(listEl, items, type) {
    if (type === "evaluate") {
        renderEvalLastResults(listEl, items);
    } else {
        renderSchedLastResults(listEl, items);
    }
}

async function fetchStats() {
    try {
        const res = await fetch(`${API_BASE}/stats`, {
            headers: { "Authorization": `Bearer ${AUTH_TOKEN}` },
        });
        if (!res.ok) return;
        const data = await res.json();

        // Evaluation
        evalTotalEl.textContent = data.evaluation.total;
        evalAcceptedEl.textContent = data.evaluation.accepted;
        evalRejectedEl.textContent = data.evaluation.rejected;
        evalPctEl.textContent = data.evaluation.acceptance_pct + "%";

        // Evaluation last batch
        renderLastResults(evalLastResultsEl, data.evaluation.last_batch, "evaluate");

        // Scheduling
        schedTotalEl.textContent = data.scheduling.total;
        schedScheduledEl.textContent = data.scheduling.scheduled;
        schedRejectedEl.textContent = data.scheduling.rejected;
        schedPctEl.textContent = data.scheduling.acceptance_pct + "%";

        // Scheduling last batch
        renderLastResults(schedLastResultsEl, data.scheduling.last_batch, "schedule");
    } catch (e) {
        console.error("Failed to fetch stats:", e);
    }
}

// ── Supabase Realtime — live evaluation results ─────────────────────────────
let realtimeChannel = null;
let expectedCandidates = 0;
let receivedCandidates = 0;

function showLivePanel(total) {
    expectedCandidates = total;
    receivedCandidates = 0;
    liveResultsTbody.innerHTML = "";
    liveResultsProgress.textContent = `0 / ${total}`;
    liveResultsPanel.hidden = false;
}

function hideLivePanel() {
    liveResultsPanel.hidden = true;
}

function appendLiveRow(row) {
    receivedCandidates++;
    liveResultsProgress.textContent = `${receivedCandidates} / ${expectedCandidates}`;

    const name = escapeHtml(row.candidate_name || "");
    const email = escapeHtml(row.candidate_email || "");
    const verdict = row.verdict || "";
    const reason = escapeHtml(row.reason || "");
    const resumeLink = row.resume_link || "";
    const badgeClass = verdict === "YES" ? "yes" : verdict === "NO" ? "no" : "err";
    const resumeHtml = resumeLink
        ? `<a href="${escapeHtml(resumeLink)}" target="_blank" rel="noopener">View</a>`
        : "—";

    const tr = document.createElement("tr");
    tr.innerHTML = `
        <td>${name}</td>
        <td>${email}</td>
        <td><span class="badge badge--${badgeClass}">${escapeHtml(verdict)}</span></td>
        <td class="reason-cell">${reason}</td>
        <td>${resumeHtml}</td>`;
    liveResultsTbody.prepend(tr);

    if (receivedCandidates >= expectedCandidates) {
        onEvaluationComplete();
    }
}

function onEvaluationComplete() {
    unsubscribeRealtime();
    setLoading(evaluateBtn, false);
    fetchStats();
}

function subscribeRealtime() {
    unsubscribeRealtime();

    if (!AUTH_USER_ID) {
        console.warn("No user_id — cannot subscribe to Supabase Realtime.");
        return;
    }

    realtimeChannel = supabase
        .channel("evaluation-results")
        .on(
            "postgres_changes",
            {
                event: "INSERT",
                schema: "public",
                table: "evaluation_results",
                filter: `user_id=eq.${AUTH_USER_ID}`,
            },
            (payload) => {
                appendLiveRow(payload.new);
            },
        )
        .subscribe();
}

function unsubscribeRealtime() {
    if (realtimeChannel) {
        supabase.removeChannel(realtimeChannel);
        realtimeChannel = null;
    }
}

// Clean up on page unload
window.addEventListener("beforeunload", unsubscribeRealtime);

// ── Button handlers ─────────────────────────────────────────────────────────
evaluateBtn.addEventListener("click", async () => {
    if (!evaluateCsvFile) return;
    setLoading(evaluateBtn, true);
    try {
        // Subscribe to Realtime BEFORE uploading so we don't miss events
        subscribeRealtime();

        const data = await uploadFile(
            "/evaluate",
            evaluateCsvFile,
            {
                jd: jdInput.value.trim(),
                test_link: testLinkInput.value.trim(),
                send_emails: sendEmailsToggle.checked ? "true" : "false",
            }
        );

        // Backend returns 202 with total_candidates
        showLivePanel(data.total_candidates || 0);
    } catch (err) {
        unsubscribeRealtime();
        hideLivePanel();
        setLoading(evaluateBtn, false);
        alert(err.message);
    }
});

scheduleBtn.addEventListener("click", async () => {
    if (!scheduleCsvFile) return;
    setLoading(scheduleBtn, true);
    try {
        await uploadFile(
            "/schedule",
            scheduleCsvFile,
            {
                start_date: interviewDateInput.value,
                start_time: interviewStartTime.value,
                duration: interviewDuration.value,
                gap: interviewGap.value,
            }
        );
        fetchStats();
    } catch (err) {
        alert(err.message);
    } finally {
        setLoading(scheduleBtn, false);
    }
});

// ── Settings ────────────────────────────────────────────────────────────────
async function fetchSettings() {
    try {
        const res = await fetch(`${API_BASE}/settings`, {
            headers: { "Authorization": `Bearer ${AUTH_TOKEN}` },
        });
        if (!res.ok) return;
        const data = await res.json();
        vacancyCountInput.value = data.vacancy_count ?? 10;
    } catch (e) {
        console.error("Failed to fetch settings:", e);
    }
}

saveSettingsBtn.addEventListener("click", async () => {
    setLoading(saveSettingsBtn, true);
    try {
        const res = await fetch(`${API_BASE}/settings`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${AUTH_TOKEN}`,
            },
            body: JSON.stringify({ vacancy_count: Number(vacancyCountInput.value) }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `Server error ${res.status}`);
        }
    } catch (err) {
        alert(err.message);
    } finally {
        setLoading(saveSettingsBtn, false);
    }
});

// ── Init ────────────────────────────────────────────────────────────────────
fetchStats();
fetchSettings();
