const unavailableEntrances = {
  nisqually: {
    id: "nisqually",
    name: "Nisqually Entrance",
    approach: "From Ashford via WA-706",
    min: null,
    median: null,
    max: null,
    queueMiles: null,
    trend: "Unavailable",
    confidence: "Unavailable",
    confidenceScore: 0,
    reports: 0,
    updatedMinutes: null,
    status: "unavailable",
    statusLabel: "Estimate unavailable",
    dataMode: "unavailable",
    displayable: false,
    freshnessStatus: "unavailable"
  },
  "white-river": {
    id: "white-river",
    name: "White River Entrance",
    approach: "From Enumclaw via WA-410",
    min: null,
    median: null,
    max: null,
    queueMiles: null,
    trend: "Unavailable",
    confidence: "Unavailable",
    confidenceScore: 0,
    reports: 0,
    updatedMinutes: null,
    status: "unavailable",
    statusLabel: "Estimate unavailable",
    dataMode: "unavailable",
    displayable: false,
    freshnessStatus: "unavailable"
  }
};

const fallbackAlerts = [
  {
    tag: "SERVICE STATUS",
    title: "Current condition feed unavailable",
    detail: "Wait estimates are hidden until the site can retrieve a recent traffic observation. Check official NPS conditions before travel."
  }
];

const fallbackForecasts = {
  nisqually: [
    [6, 0, 5], [7, 0, 8], [8, 5, 15], [9, 10, 25], [10, 25, 45], [11, 40, 65],
    [12, 45, 75], [13, 45, 70], [14, 35, 60], [15, 25, 45], [16, 15, 30], [17, 5, 18]
  ],
  "white-river": [
    [6, 0, 5], [7, 0, 5], [8, 0, 10], [9, 5, 15], [10, 10, 25], [11, 20, 40],
    [12, 25, 45], [13, 25, 45], [14, 20, 35], [15, 12, 25], [16, 5, 15], [17, 0, 10]
  ]
};

let entrances = structuredClone(unavailableEntrances);
let operationalAlerts = fallbackAlerts;
let systemMode = "unavailable";
let timerInterval = null;
let timerStartedAt = null;
let activeReportId = null;
let activeReportToken = null;
let activeReportMode = "local";

function deviceIdentifier() {
  // A random per-browser value. It replaces the network address as the key for
  // duplicate and abuse control, because visitors queued at the same entrance
  // usually share a small number of carrier addresses.
  try {
    let value = localStorage.getItem("rainier-device-id");
    if (!value) {
      value = (crypto.randomUUID && crypto.randomUUID()) || `dev-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
      localStorage.setItem("rainier-device-id", value);
    }
    return value;
  } catch {
    return "";
  }
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

function isDisplayable(entrance) {
  return Boolean(
    entrance
    && entrance.displayable !== false
    && Number.isFinite(entrance.min)
    && Number.isFinite(entrance.max)
  );
}

function waitLabel(entrance) {
  if (entrance?.entranceClosed || entrance?.freshnessStatus === "closed") return "Closed";
  if (!isDisplayable(entrance)) return "Unavailable";
  return entrance.min === 0 && entrance.max <= 10
    ? "Under 10"
    : `${entrance.min}–${entrance.max}`;
}

function freshnessLabel(entrance) {
  if (entrance.freshnessStatus === "closed") return "Manual closure override";
  const minutes = entrance.updatedMinutes;
  if (entrance.freshnessStatus === "unavailable" || minutes === null || minutes === undefined) {
    return "No recent observation";
  }
  if (entrance.freshnessStatus === "last-daytime") {
    return minutes <= 0 ? "Last daytime observation" : `Last daytime observation · ${minutes} min ago`;
  }
  if (entrance.freshnessStatus === "stale") {
    return `Stale · ${minutes} min ago`;
  }
  if (minutes <= 0) return "Just now";
  return `${minutes} min ago`;
}

function sourceLabel(entrance) {
  if (entrance.entranceClosed || entrance.freshnessStatus === "closed") {
    return "This entrance is marked closed; verify current status with the National Park Service.";
  }
  if (!isDisplayable(entrance)) {
    return "A recent traffic observation is required before an estimate is shown.";
  }
  if (entrance.freshnessStatus === "stale") {
    return "This estimate is aging and may no longer reflect the entrance line.";
  }
  if (entrance.freshnessStatus === "last-daytime") {
    return "Daytime polling has ended; this is the last recent observation, not a live reading.";
  }
  if (Number.isFinite(entrance.queueMiles)) {
    return `Traffic speed categories suggest congestion begins about ${entrance.queueMiles.toFixed(1)} miles before the entrance. The boundary is approximate.`;
  }
  if (Number.isFinite(entrance.queueUpdatedMinutes)) {
    return "The latest hourly traffic scan did not identify a gate-connected slow or jammed segment. The wait still uses full-route travel time.";
  }
  return "Wait is based on current full-route travel time minus a provisional free-flow baseline.";
}

function queueSignalLabel(entrance) {
  if (!isDisplayable(entrance)) return "Unavailable";
  if (Number.isFinite(entrance.queueMiles)) {
    return `Starts ~${entrance.queueMiles.toFixed(1)} mi out`;
  }
  if (Number.isFinite(entrance.queueUpdatedMinutes)) return "No connected slowdown";
  return "Awaiting hourly scan";
}

function renderEntranceCards() {
  const container = document.querySelector("#entrance-cards");
  container.innerHTML = Object.values(entrances).map((entrance) => {
    const displayable = isDisplayable(entrance);
    const waitMarkup = displayable
      ? `<strong>${waitLabel(entrance)}</strong><span>minutes</span>`
      : entrance.entranceClosed || entrance.freshnessStatus === "closed"
        ? `<strong>Closed</strong><span>estimate suppressed</span>`
        : `<strong>Unavailable</strong><span>no current estimate</span>`;
    const freshnessClass = ["stale", "last-daytime"].includes(entrance.freshnessStatus)
      ? " freshness-warning"
      : "";
    return `
      <article class="entrance-card ${escapeHtml(entrance.status || "unavailable")}">
        <div class="card-top">
          <div>
            <h3>${escapeHtml(entrance.name)}</h3>
            <p>${escapeHtml(entrance.approach)}</p>
          </div>
          <span class="status-pill ${escapeHtml(entrance.status || "unavailable")}">${escapeHtml(entrance.statusLabel || "Estimate unavailable")}</span>
        </div>
        <div class="wait-number ${displayable ? "" : "unavailable-wait"}">${waitMarkup}</div>
        <p class="queue-detail${freshnessClass}">${escapeHtml(sourceLabel(entrance))}</p>
        <div class="metric-row">
          <div><span>Trend</span><strong>${escapeHtml(displayable ? entrance.trend : "Unavailable")}</strong></div>
          <div><span>Signal strength</span><strong>${escapeHtml(displayable ? entrance.confidence : "Unavailable")}${displayable && Number.isFinite(entrance.confidenceScore) ? ` · ${entrance.confidenceScore}` : ""}</strong></div>
          <div><span>Community reports</span><strong>${Number(entrance.reports) || 0}</strong></div>
          <div><span>Queue signal</span><strong>${escapeHtml(queueSignalLabel(entrance))}</strong></div>
          <div><span>Observation</span><strong>${escapeHtml(freshnessLabel(entrance))}</strong></div>
        </div>
        <button class="feedback-card-link" type="button" data-feedback-entrance="${escapeHtml(entrance.id)}">Report an inaccurate estimate</button>
      </article>
    `;
  }).join("");

  for (const entranceId of ["nisqually", "white-river"]) {
    const entrance = entrances[entranceId] || unavailableEntrances[entranceId];
    const mapLabel = document.querySelector(`#map-${entranceId}`);
    if (mapLabel) {
      mapLabel.textContent = isDisplayable(entrance)
        ? `${waitLabel(entrance)} min`
        : entrance.entranceClosed || entrance.freshnessStatus === "closed"
          ? "Closed"
          : "Unavailable";
    }
    const line = document.querySelector(`#${entranceId}-queue-line`);
    if (line) line.setAttribute("class", `queue-line ${entrance.status || "unavailable"}`);
  }

  const values = Object.values(entrances);
  const available = values.filter(isDisplayable);
  if (available.length) {
    const longest = [...available].sort((a, b) => b.max - a.max)[0];
    const best = [...available].sort((a, b) => a.max - b.max)[0];
    document.querySelector("#longest-wait").textContent = `${waitLabel(longest)} min`;
    document.querySelector("#best-entrance").textContent = best.name.replace(" Entrance", "");
  } else {
    document.querySelector("#longest-wait").textContent = "Unavailable";
    document.querySelector("#best-entrance").textContent = "Unavailable";
  }
  document.querySelector("#report-coverage").textContent = `${values.filter((entry) => Number(entry.reports) > 0).length} of ${values.length}`;
}

function renderAlerts() {
  const list = document.querySelector("#alerts-list");
  if (!operationalAlerts.length) {
    list.innerHTML = `<div class="alert-item"><strong>No active alerts were returned.</strong><p>Always verify official park conditions before travel.</p></div>`;
    return;
  }
  list.innerHTML = operationalAlerts.map((alert) => `
    <div class="alert-item">
      <span class="alert-tag">${escapeHtml(alert.tag || "NOTICE")}</span>
      <strong>${escapeHtml(alert.title || "Condition notice")}</strong>
      <p>${escapeHtml(alert.detail || "")}</p>
      ${alert.url ? `<a class="alert-link" href="${escapeAttribute(alert.url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}
    </div>
  `).join("");
}

function setMode(mode, generatedAt = null) {
  systemMode = mode;
  const badge = document.querySelector("#data-mode-badge");
  const visualMode = mode === "live" ? "live" : mode === "mixed" ? "mixed" : mode === "unavailable" ? "unavailable" : "demo";
  badge.className = `data-mode-badge ${visualMode}`;
  badge.textContent = mode === "live"
    ? "Live traffic data"
    : mode === "mixed"
      ? "Mixed data availability"
      : mode === "demo"
        ? "Synthetic local demo"
        : "Estimates unavailable";

  const timestamp = generatedAt ? new Date(generatedAt) : new Date();
  const formatted = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(timestamp);
  document.querySelector("#last-updated").textContent = mode === "live"
    ? `Estimate response generated at ${formatted}`
    : mode === "mixed"
      ? `Some entrance data unavailable · checked at ${formatted}`
      : mode === "demo"
        ? `Synthetic local observations generated at ${formatted}`
        : `No recent public estimate · checked at ${formatted}`;
}

async function loadCurrentData() {
  try {
    const payload = await apiFetch("/api/v1/entrances/current");
    entrances = Object.fromEntries(payload.entrances.map((entry) => [entry.id, entry]));
    setMode(payload.dataMode, payload.generatedAt);
  } catch (error) {
    console.warn("Current wait API unavailable:", error);
    entrances = structuredClone(unavailableEntrances);
    setMode("unavailable");
  }
  renderEntranceCards();
}

async function loadConditions() {
  try {
    const payload = await apiFetch("/api/v1/conditions");
    operationalAlerts = payload.alerts || [];
  } catch (error) {
    console.warn("Condition API unavailable:", error);
    operationalAlerts = fallbackAlerts;
  }
  renderAlerts();
}

function multiplierForDayType(dayType) {
  if (dayType === "holiday") return 1.25;
  if (dayType === "weekday") return 0.62;
  return 1;
}

function fallbackForecast(entranceId, dayType) {
  const multiplier = multiplierForDayType(dayType);
  return fallbackForecasts[entranceId].map(([hour, low, high]) => ({
    hour,
    low: Math.round(low * multiplier),
    high: Math.round(high * multiplier)
  }));
}

async function loadForecast() {
  const entranceId = document.querySelector("#planner-entrance").value;
  const dayType = document.querySelector("#planner-day-type").value;
  const date = document.querySelector("#planner-date").value;
  let forecast;
  let caption;
  try {
    const query = new URLSearchParams({ date, dayType });
    const payload = await apiFetch(`/api/v1/entrances/${entranceId}/forecast?${query}`);
    forecast = payload.hours;
    caption = payload.notice;
  } catch (error) {
    console.warn("Forecast API unavailable; using clearly labeled local template:", error);
    forecast = fallbackForecast(entranceId, dayType);
    caption = "Experimental seasonal template—not current traffic and not a validated historical prediction.";
  }
  renderForecast(forecast);
  document.querySelector("#forecast-caption").textContent = caption;
}

function renderForecast(forecast) {
  const maxValue = Math.max(...forecast.map((row) => row.high), 20);
  document.querySelector("#forecast-chart").innerHTML = forecast.map(({ hour, low, high }) => {
    const height = Math.max(6, Math.round((high / maxValue) * 188));
    const status = high >= 45 ? "severe" : high >= 20 ? "moderate" : "clear";
    const time = hour > 12 ? `${hour - 12}p` : hour === 12 ? "12p" : `${hour}a`;
    return `
      <div class="forecast-column" title="${time}: ${low} to ${high} minutes">
        <div class="forecast-bar-wrap">
          <div class="forecast-bar ${status}" data-height="${height}"><span>${high}</span></div>
        </div>
        <span class="forecast-time">${time}</span>
        <span class="forecast-range">${low}–${high}</span>
      </div>
    `;
  }).join("");

  // Bar heights are applied through the CSSOM rather than an inline style
  // attribute, which the Content Security Policy blocks.
  document.querySelectorAll("#forecast-chart .forecast-bar").forEach((bar) => {
    bar.style.height = `${bar.dataset.height}px`;
  });

  const lowWindows = forecast.filter(({ high }) => high <= 10).map(({ hour }) => hour);
  const firstLow = lowWindows[0];
  const lastLow = lowWindows[lowWindows.length - 1];
  let recommendation = "Before 8:00 a.m.";
  if (firstLow !== undefined && lastLow >= 16) recommendation = "Before 8:00 a.m. or after 4:00 p.m.";
  document.querySelector("#recommended-window").textContent = recommendation;

  const peakRows = [...forecast].sort((a, b) => b.high - a.high);
  const peakHour = peakRows[0].hour;
  const endHour = Math.min(peakHour + 2, 18);
  const formatHour = (hour) => `${hour > 12 ? hour - 12 : hour}:00 ${hour >= 12 ? "p.m." : "a.m."}`;
  document.querySelector("#expected-peak").textContent = `${formatHour(peakHour)}–${formatHour(endHour)}`;
}

function setDefaultDate() {
  const dateInput = document.querySelector("#planner-date");
  const nextSaturday = new Date();
  nextSaturday.setDate(nextSaturday.getDate() + ((6 - nextSaturday.getDay() + 7) % 7 || 7));
  dateInput.value = nextSaturday.toISOString().slice(0, 10);
}

function formatElapsed(milliseconds) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function beginVisualTimer() {
  document.querySelector("#start-timer").disabled = true;
  document.querySelector("#stop-timer").disabled = false;
  document.querySelector("#timer-result").hidden = true;
  document.querySelector("#timer-status").textContent = activeReportMode === "server"
    ? "Timing your entrance wait. A private completion token is stored only in this browser."
    : "Timing locally. The report service could not be reached, so this timer will not affect estimates.";
  window.clearInterval(timerInterval);
  timerInterval = window.setInterval(() => {
    document.querySelector("#timer-display").textContent = formatElapsed(Date.now() - timerStartedAt);
  }, 250);
}

async function startTimer() {
  const entrance = document.querySelector("#timer-entrance").value;
  timerStartedAt = Date.now();
  activeReportId = null;
  activeReportToken = null;
  activeReportMode = "local";
  try {
    const result = await apiFetch("/api/v1/reports/start", {
      method: "POST",
      body: JSON.stringify({ entrance, deviceId: deviceIdentifier() })
    });
    activeReportId = result.reportId;
    activeReportToken = result.reportToken;
    activeReportMode = "server";
  } catch (error) {
    console.warn("Timer will remain local:", error);
  }
  localStorage.setItem("rainier-active-timer", JSON.stringify({
    entrance,
    timerStartedAt,
    activeReportId,
    activeReportToken,
    activeReportMode
  }));
  beginVisualTimer();
}

async function stopTimer() {
  window.clearInterval(timerInterval);
  timerInterval = null;
  const durationMs = Date.now() - timerStartedAt;
  const entranceId = document.querySelector("#timer-entrance").value;
  const entrance = entrances[entranceId] || unavailableEntrances[entranceId];
  const resultBox = document.querySelector("#timer-result");
  let saveMessage = "This timer was kept only in your browser.";

  if (activeReportMode === "server" && activeReportId && activeReportToken) {
    try {
      const saved = await apiFetch("/api/v1/reports/complete", {
        method: "POST",
        body: JSON.stringify({ reportId: activeReportId, reportToken: activeReportToken })
      });
      saveMessage = saved.message;
      await loadCurrentData();
    } catch (error) {
      saveMessage = `The timer stopped, but the report was not saved: ${error.message}`;
    }
  }

  resultBox.hidden = false;
  resultBox.innerHTML = `<strong>Wait report complete</strong><br>${escapeHtml(entrance.name)} · ${formatElapsed(durationMs)} elapsed.<br><span>${escapeHtml(saveMessage)}</span>`;
  document.querySelector("#timer-status").textContent = "Timer stopped. You can start another report.";
  document.querySelector("#start-timer").disabled = false;
  document.querySelector("#stop-timer").disabled = true;
  document.querySelector("#timer-display").textContent = formatElapsed(durationMs);
  timerStartedAt = null;
  activeReportId = null;
  activeReportToken = null;
  activeReportMode = "local";
  localStorage.removeItem("rainier-active-timer");
}

function restoreTimer() {
  try {
    const stored = JSON.parse(localStorage.getItem("rainier-active-timer") || "null");
    if (!stored || !stored.timerStartedAt || Date.now() - stored.timerStartedAt > 4 * 60 * 60 * 1000) {
      localStorage.removeItem("rainier-active-timer");
      return;
    }
    timerStartedAt = stored.timerStartedAt;
    activeReportId = stored.activeReportId;
    activeReportToken = stored.activeReportToken;
    activeReportMode = stored.activeReportMode || "local";
    if (activeReportMode === "server" && (!activeReportId || !activeReportToken)) {
      activeReportMode = "local";
    }
    document.querySelector("#timer-entrance").value = stored.entrance;
    beginVisualTimer();
  } catch {
    localStorage.removeItem("rainier-active-timer");
  }
}

function feedbackEstimateText(entrance) {
  if (!entrance || !isDisplayable(entrance)) return "No estimate was displayed";
  return `${waitLabel(entrance)} minutes · ${freshnessLabel(entrance)}`;
}

function setFeedbackMode(type, entranceId = "", preselectedCategory = "") {
  const form = document.querySelector("#feedback-form");
  const accuracyFields = document.querySelector("#feedback-accuracy-fields");
  const entrance = entranceId ? entrances[entranceId] || unavailableEntrances[entranceId] : null;
  form.reset();
  form.elements.feedbackType.value = type;
  form.elements.pagePath.value = window.location.pathname;
  form.elements.website.value = "";
  document.querySelector("#feedback-status").textContent = "";

  if (type === "accuracy") {
    document.querySelector("#feedback-dialog-title").textContent = "Report an inaccurate estimate";
    document.querySelector("#feedback-dialog-intro").textContent = "Tell us what the site showed and what you actually experienced. This report will be reviewed and will not automatically change the live estimate.";
    accuracyFields.hidden = false;
    form.elements.entrance.value = entranceId;
    form.elements.category.value = "estimate-accuracy";
    form.elements.actualWaitMinutes.required = true;
    form.elements.message.required = false;
    form.elements.message.placeholder = "Where did the queue begin, and how did the displayed estimate differ from your experience?";
    form.elements.displayedLowMinutes.value = Number.isFinite(entrance?.min) ? entrance.min : "";
    form.elements.displayedHighMinutes.value = Number.isFinite(entrance?.max) ? entrance.max : "";
    form.elements.displayedObservedAt.value = entrance?.observedAt || "";
    document.querySelector("#feedback-estimate-summary").textContent = feedbackEstimateText(entrance);
  } else {
    document.querySelector("#feedback-dialog-title").textContent = "Send beta feedback";
    document.querySelector("#feedback-dialog-intro").textContent = "Report a timer or website problem, confusing information, or an idea for improving the beta.";
    accuracyFields.hidden = true;
    form.elements.entrance.value = "";
    form.elements.category.value = "other";
    form.elements.actualWaitMinutes.required = false;
    form.elements.message.required = true;
    form.elements.displayedLowMinutes.value = "";
    form.elements.displayedHighMinutes.value = "";
    form.elements.displayedObservedAt.value = "";
    if (preselectedCategory === "methodology") {
      document.querySelector("#feedback-dialog-title").textContent = "Comment on the methodology";
      document.querySelector("#feedback-dialog-intro").textContent = "Share concerns, suggested changes, or questions about the estimate calculation, weighting, uncertainty range, or known limitations.";
      form.elements.category.value = "methodology";
      form.elements.message.placeholder = "Which assumption or part of the calculation should be reconsidered, and why?";
    } else {
      form.elements.message.placeholder = "What happened, or what should be improved?";
    }
  }
}

function openFeedback(type, entranceId = "", preselectedCategory = "") {
  setFeedbackMode(type, entranceId, preselectedCategory);
  const dialog = document.querySelector("#feedback-dialog");
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeFeedback() {
  const dialog = document.querySelector("#feedback-dialog");
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function submitFeedback(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector('button[type="submit"]');
  const status = document.querySelector("#feedback-status");
  const gateArrivalValue = form.elements.gateArrivalAt.value;
  const payload = {
    feedbackType: form.elements.feedbackType.value,
    category: form.elements.category.value,
    entrance: form.elements.entrance.value || null,
    displayedLowMinutes: form.elements.displayedLowMinutes.value || null,
    displayedHighMinutes: form.elements.displayedHighMinutes.value || null,
    displayedObservedAt: form.elements.displayedObservedAt.value || null,
    actualWaitMinutes: form.elements.actualWaitMinutes.value || null,
    gateArrivalAt: gateArrivalValue ? new Date(gateArrivalValue).toISOString() : null,
    message: form.elements.message.value,
    contactEmail: form.elements.contactEmail.value,
    pagePath: form.elements.pagePath.value,
    website: form.elements.website.value
  };
  submitButton.disabled = true;
  status.className = "form-status";
  status.textContent = "Submitting…";
  try {
    const result = await apiFetch("/api/v1/feedback", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    status.className = "form-status success";
    status.textContent = result.message || "Thank you—your feedback was saved.";
    window.setTimeout(closeFeedback, 1400);
  } catch (error) {
    status.className = "form-status error";
    status.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  const text = String(value || "");
  return /^https:\/\//i.test(text) ? escapeHtml(text) : "#";
}

async function initialize() {
  setDefaultDate();
  renderEntranceCards();
  await Promise.all([loadCurrentData(), loadConditions()]);
  await loadForecast();
  restoreTimer();

  document.querySelector("#planner-entrance").addEventListener("change", loadForecast);
  document.querySelector("#planner-day-type").addEventListener("change", loadForecast);
  document.querySelector("#planner-date").addEventListener("change", loadForecast);
  document.querySelector("#start-timer").addEventListener("click", startTimer);
  document.querySelector("#stop-timer").addEventListener("click", stopTimer);
  document.querySelector("#entrance-cards").addEventListener("click", (event) => {
    const button = event.target.closest("[data-feedback-entrance]");
    if (button) openFeedback("accuracy", button.dataset.feedbackEntrance);
  });
  document.querySelector("#general-feedback-link").addEventListener("click", () => openFeedback("general"));
  document.querySelector("#methodology-feedback-link").addEventListener("click", () => openFeedback("general", "", "methodology"));
  document.querySelector("#feedback-form").addEventListener("submit", submitFeedback);
  document.querySelectorAll("[data-close-feedback]").forEach((button) => button.addEventListener("click", closeFeedback));
  document.querySelector("#feedback-dialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeFeedback();
  });

  const requestedFeedback = new URLSearchParams(window.location.search).get("feedback");
  if (requestedFeedback === "methodology") {
    openFeedback("general", "", "methodology");
  } else if (requestedFeedback === "general") {
    // Deep link used by the privacy notice for questions and removal requests.
    openFeedback("general", "", "other");
  }

  // The server polls the traffic provider every 15 minutes, so a one-minute
  // refresh only burned battery and cellular data in a queued vehicle.
  let lastRefreshAt = Date.now();
  const refresh = () => {
    lastRefreshAt = Date.now();
    loadCurrentData();
    loadConditions();
  };
  window.setInterval(() => {
    if (document.visibilityState === "visible") refresh();
  }, 300_000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - lastRefreshAt > 120_000) refresh();
  });
}

initialize();
