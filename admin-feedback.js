let adminToken = sessionStorage.getItem("rainier-admin-token") || "";
let currentSubmissions = [];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function adminFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "X-Admin-Token": adminToken,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {}
    throw new Error(message);
  }
  return response;
}

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit"
  }).format(date);
}

function categoryLabel(value) {
  return {
    "estimate-accuracy": "Estimate accuracy",
    "timer-problem": "Timer problem",
    "website-problem": "Website problem",
    "confusing-information": "Confusing information",
    "feature-suggestion": "Feature suggestion",
    methodology: "Methodology or calculation",
    other: "Other"
  }[value] || value;
}

function entranceLabel(value) {
  return value === "nisqually" ? "Nisqually" : value === "white-river" ? "White River" : "Not specified";
}

function estimateLabel(item) {
  if (item.displayedLowMinutes === null || item.displayedHighMinutes === null) return "Not captured";
  return `${item.displayedLowMinutes}–${item.displayedHighMinutes} min`;
}

function differenceLabel(item) {
  if (item.actualWaitMinutes === null || item.displayedHighMinutes === null || item.displayedLowMinutes === null) return "—";
  if (item.actualWaitMinutes < item.displayedLowMinutes) return `${item.actualWaitMinutes - item.displayedLowMinutes} min below range`;
  if (item.actualWaitMinutes > item.displayedHighMinutes) return `+${item.actualWaitMinutes - item.displayedHighMinutes} min above range`;
  return "Within displayed range";
}

function renderSubmissions() {
  const list = document.querySelector("#feedback-list");
  if (!currentSubmissions.length) {
    list.innerHTML = '<div class="admin-empty"><strong>No matching feedback.</strong><p>New submissions will appear here.</p></div>';
    return;
  }
  list.innerHTML = currentSubmissions.map((item) => `
    <article class="feedback-admin-card" data-feedback-id="${escapeHtml(item.id)}">
      <div class="feedback-admin-summary">
        <div>
          <span class="admin-status-pill ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
          <strong>${escapeHtml(categoryLabel(item.category))}</strong>
          <span>${escapeHtml(entranceLabel(item.entrance))} · ${escapeHtml(formatTimestamp(item.createdAt))}</span>
        </div>
        <div class="feedback-difference">${escapeHtml(differenceLabel(item))}</div>
      </div>
      <div class="feedback-admin-metrics">
        <div><span>Estimate shown</span><strong>${escapeHtml(estimateLabel(item))}</strong></div>
        <div><span>Actual wait</span><strong>${item.actualWaitMinutes === null ? "—" : `${item.actualWaitMinutes} min`}</strong></div>
        <div><span>Estimate observation</span><strong>${escapeHtml(formatTimestamp(item.displayedObservedAt))}</strong></div>
        <div><span>Reached booth</span><strong>${escapeHtml(formatTimestamp(item.gateArrivalAt))}</strong></div>
      </div>
      ${item.message ? `<div class="feedback-message"><span>Visitor details</span><p>${escapeHtml(item.message)}</p></div>` : ""}
      ${item.contactEmail ? `<div class="feedback-contact"><span>Follow-up email</span><strong>${escapeHtml(item.contactEmail)}</strong></div>` : ""}
      <div class="feedback-review-controls">
        <label>
          Review status
          <select data-review-status>
            <option value="new" ${item.status === "new" ? "selected" : ""}>New</option>
            <option value="reviewed" ${item.status === "reviewed" ? "selected" : ""}>Reviewed</option>
            <option value="calibration" ${item.status === "calibration" ? "selected" : ""}>Useful for calibration</option>
            <option value="resolved" ${item.status === "resolved" ? "selected" : ""}>Resolved</option>
            <option value="spam" ${item.status === "spam" ? "selected" : ""}>Spam</option>
          </select>
        </label>
        <label>
          Private review notes
          <textarea data-review-notes rows="3" maxlength="4000">${escapeHtml(item.resolutionNotes || "")}</textarea>
        </label>
        <button class="button primary" type="button" data-save-feedback>Save review</button>
      </div>
    </article>
  `).join("");
}

async function loadFeedback() {
  const status = document.querySelector("#feedback-status-filter").value;
  const query = new URLSearchParams({ limit: "250" });
  if (status) query.set("status", status);
  const statusLine = document.querySelector("#admin-status");
  statusLine.className = "form-status";
  statusLine.textContent = "Loading feedback…";
  try {
    const response = await adminFetch(`/api/v1/admin/feedback?${query}`);
    const payload = await response.json();
    currentSubmissions = payload.submissions || [];
    document.querySelector("#feedback-count").textContent = `${payload.total} submission${payload.total === 1 ? "" : "s"}${status ? ` with status “${status}”` : ""}`;
    renderSubmissions();
    statusLine.textContent = "";
    document.querySelector("#admin-login").hidden = true;
    document.querySelector("#admin-dashboard").hidden = false;
  } catch (error) {
    statusLine.className = "form-status error";
    statusLine.textContent = error.message;
    if (error.message.includes("Invalid admin token") || error.message.includes("disabled")) lockDashboard(error.message);
  }
}

async function saveReview(card) {
  const id = card.dataset.feedbackId;
  const button = card.querySelector("[data-save-feedback]");
  const payload = {
    status: card.querySelector("[data-review-status]").value,
    resolutionNotes: card.querySelector("[data-review-notes]").value
  };
  button.disabled = true;
  button.textContent = "Saving…";
  try {
    await adminFetch(`/api/v1/admin/feedback/${id}`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    button.textContent = "Saved";
    window.setTimeout(() => { button.textContent = "Save review"; }, 1200);
  } catch (error) {
    button.textContent = "Save failed";
    document.querySelector("#admin-status").className = "form-status error";
    document.querySelector("#admin-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function downloadCsv() {
  const status = document.querySelector("#feedback-status-filter").value;
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  try {
    const response = await adminFetch(`/api/v1/admin/feedback.csv${query}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `rainier-gate-waits-feedback${status ? `-${status}` : ""}.csv`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    document.querySelector("#admin-status").className = "form-status error";
    document.querySelector("#admin-status").textContent = error.message;
  }
}

function lockDashboard(message = "") {
  adminToken = "";
  sessionStorage.removeItem("rainier-admin-token");
  currentSubmissions = [];
  document.querySelector("#admin-dashboard").hidden = true;
  document.querySelector("#admin-login").hidden = false;
  document.querySelector("#admin-login-status").className = message ? "form-status error" : "form-status";
  document.querySelector("#admin-login-status").textContent = message;
  document.querySelector("#admin-token").value = "";
}

document.querySelector("#admin-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  adminToken = document.querySelector("#admin-token").value.trim();
  sessionStorage.setItem("rainier-admin-token", adminToken);
  document.querySelector("#admin-login-status").textContent = "Checking token…";
  await loadFeedback();
});
document.querySelector("#feedback-status-filter").addEventListener("change", loadFeedback);
document.querySelector("#refresh-feedback").addEventListener("click", loadFeedback);
document.querySelector("#download-feedback").addEventListener("click", downloadCsv);
document.querySelector("#admin-logout").addEventListener("click", () => lockDashboard());
document.querySelector("#feedback-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-save-feedback]");
  if (button) saveReview(button.closest("[data-feedback-id]"));
});

if (adminToken) loadFeedback();
