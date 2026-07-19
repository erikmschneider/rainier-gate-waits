const fallbackEntrances = {
  "nisqually": {
    id: "nisqually",
    name: "Nisqually Entrance",
    approach: "From Ashford via WA-706",
    min: 35,
    median: 42,
    max: 50,
    queueMiles: 2.4,
    trend: "Rising",
    confidence: "Low",
    confidenceScore: 42,
    reports: 0,
    updatedMinutes: 0,
    status: "severe",
    statusLabel: "Heavy delay",
    dataMode: "browser-fallback"
  },
  "white-river": {
    id: "white-river",
    name: "White River Entrance",
    approach: "From Enumclaw via WA-410",
    min: 10,
    median: 15,
    max: 20,
    queueMiles: 0.7,
    trend: "Stable",
    confidence: "Low",
    confidenceScore: 40,
    reports: 0,
    updatedMinutes: 0,
    status: "moderate",
    statusLabel: "Moderate delay",
    dataMode: "browser-fallback"
  }
};

const fallbackAlerts = [
  {
    tag: "STATIC FALLBACK",
    title: "The backend is not running",
    detail: "Start server.py to use persistent observations, API forecasts, and saved visitor timers."
  },
  {
    tag: "DATA QUALITY",
    title: "Displayed waits are illustrative",
    detail: "Do not use these fallback values as current park conditions."
  }
];

const fallbackForecasts = {
  "nisqually": [
    [6, 0, 5], [7, 0, 8], [8, 5, 15], [9, 10, 25], [10, 25, 45], [11, 40, 65],
    [12, 45, 75], [13, 45, 70], [14, 35, 60], [15, 25, 45], [16, 15, 30], [17, 5, 18]
  ],
  "white-river": [
    [6, 0, 5], [7, 0, 5], [8, 0, 10], [9, 5, 15], [10, 10, 25], [11, 20, 40],
    [12, 25, 45], [13, 25, 45], [14, 20, 35], [15, 12, 25], [16, 5, 15], [17, 0, 10]
  ]
};

let entrances = structuredClone(fallbackEntrances);
let operationalAlerts = fallbackAlerts;
let systemMode = "browser-fallback";
let timerInterval = null;
let timerStartedAt = null;
let activeReportId = null;
let activeReportMode = "local";

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

function waitLabel(entrance) {
  return entrance.min === 0 && entrance.max <= 10
    ? "Under 10"
    : `${entrance.min}–${entrance.max}`;
}

function freshnessLabel(minutes) {
  if (minutes === null || minutes === undefined) return "No observation";
  if (minutes <= 0) return "Just now";
  return `${minutes} min ago`;
}

function queueLabel(entrance) {
  if (entrance.queueMiles === null || entrance.queueMiles === undefined) {
    return "Queue length not yet available";
  }
  if (entrance.queueMiles <= 0) return "No sustained approach queue detected";
  return `Approximate delay footprint: ${Number(entrance.queueMiles).toFixed(1)} miles`;
}

function renderEntranceCards() {
  const container = document.querySelector("#entrance-cards");
  container.innerHTML = Object.values(entrances).map((entrance) => `
    <article class="entrance-card ${entrance.status}">
      <div class="card-top">
        <div>
          <h3>${escapeHtml(entrance.name)}</h3>
          <p>${escapeHtml(entrance.approach)}</p>
        </div>
        <span class="status-pill ${entrance.status}">${escapeHtml(entrance.statusLabel)}</span>
      </div>
      <div class="wait-number">
        <strong>${waitLabel(entrance)}</strong>
        <span>minutes</span>
      </div>
      <p class="queue-detail">${escapeHtml(queueLabel(entrance))}</p>
      <div class="metric-row">
        <div><span>Trend</span><strong>${escapeHtml(entrance.trend)}</strong></div>
        <div><span>Confidence</span><strong>${escapeHtml(entrance.confidence)}${Number.isFinite(entrance.confidenceScore) ? ` · ${entrance.confidenceScore}` : ""}</strong></div>
        <div><span>Recent reports</span><strong>${entrance.reports}</strong></div>
        <div><span>Updated</span><strong>${freshnessLabel(entrance.updatedMinutes)}</strong></div>
      </div>
    </article>
  `).join("");

  document.querySelector("#map-nisqually").textContent = `${waitLabel(entrances.nisqually)} min`;
  document.querySelector("#map-white-river").textContent = `${waitLabel(entrances["white-river"])} min`;
  for (const entranceId of ["nisqually", "white-river"]) {
    const line = document.querySelector(`#${entranceId}-queue-line`);
    if (line) line.setAttribute("class", `queue-line ${entrances[entranceId].status}`);
  }

  const values = Object.values(entrances);
  const longest = [...values].sort((a, b) => b.max - a.max)[0];
  const best = [...values].sort((a, b) => a.max - b.max)[0];
  document.querySelector("#longest-wait").textContent = `${waitLabel(longest)} min`;
  document.querySelector("#best-entrance").textContent = best.name.replace(" Entrance", "");
  document.querySelector("#report-coverage").textContent = `${values.filter((entry) => entry.reports > 0).length} of ${values.length}`;
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
  badge.className = `data-mode-badge ${mode === "live" ? "live" : mode === "mixed" ? "mixed" : "demo"}`;
  badge.textContent = mode === "live" ? "Live traffic mode" : mode === "mixed" ? "Mixed data mode" : mode === "browser-fallback" ? "Static fallback" : "Demo traffic mode";

  const timestamp = generatedAt ? new Date(generatedAt) : new Date();
  const formatted = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(timestamp);
  document.querySelector("#last-updated").textContent = mode === "live"
    ? `Live estimates generated at ${formatted}`
    : mode === "mixed"
      ? `Mixed-source estimates generated at ${formatted}`
      : mode === "demo"
        ? `Synthetic observations generated at ${formatted}`
        : `Static fallback loaded at ${formatted}`;
}

async function loadCurrentData() {
  try {
    const payload = await apiFetch("/api/v1/entrances/current");
    entrances = Object.fromEntries(payload.entrances.map((entry) => [entry.id, entry]));
    setMode(payload.dataMode, payload.generatedAt);
  } catch (error) {
    console.warn("Using browser fallback:", error);
    entrances = structuredClone(fallbackEntrances);
    setMode("browser-fallback");
  }
  renderEntranceCards();
}

async function loadConditions() {
  try {
    const payload = await apiFetch("/api/v1/conditions");
    operationalAlerts = payload.alerts || [];
  } catch (error) {
    console.warn("Using fallback alerts:", error);
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
    console.warn("Using browser forecast template:", error);
    forecast = fallbackForecast(entranceId, dayType);
    caption = "Browser fallback forecast. Start server.py for API-delivered planning ranges.";
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
          <div class="forecast-bar ${status}" style="height:${height}px"><span>${high}</span></div>
        </div>
        <span class="forecast-time">${time}</span>
        <span class="forecast-range">${low}–${high}</span>
      </div>
    `;
  }).join("");

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
    ? "Timing your entrance wait. The start time is saved anonymously."
    : "Timing locally. Start server.py to save an anonymous report.";
  window.clearInterval(timerInterval);
  timerInterval = window.setInterval(() => {
    document.querySelector("#timer-display").textContent = formatElapsed(Date.now() - timerStartedAt);
  }, 250);
}

async function startTimer() {
  const entrance = document.querySelector("#timer-entrance").value;
  timerStartedAt = Date.now();
  activeReportId = null;
  activeReportMode = "local";
  try {
    const result = await apiFetch("/api/v1/reports/start", {
      method: "POST",
      body: JSON.stringify({ entrance })
    });
    activeReportId = result.reportId;
    activeReportMode = "server";
  } catch (error) {
    console.warn("Timer will remain local:", error);
  }
  localStorage.setItem("rainier-active-timer", JSON.stringify({
    entrance,
    timerStartedAt,
    activeReportId,
    activeReportMode
  }));
  beginVisualTimer();
}

async function stopTimer() {
  window.clearInterval(timerInterval);
  timerInterval = null;
  const durationMs = Date.now() - timerStartedAt;
  const entranceId = document.querySelector("#timer-entrance").value;
  const entrance = entrances[entranceId] || fallbackEntrances[entranceId];
  const resultBox = document.querySelector("#timer-result");
  let saveMessage = "This timer was kept only in your browser.";

  if (activeReportMode === "server" && activeReportId) {
    try {
      const saved = await apiFetch("/api/v1/reports/complete", {
        method: "POST",
        body: JSON.stringify({ reportId: activeReportId })
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
    activeReportMode = stored.activeReportMode || "local";
    document.querySelector("#timer-entrance").value = stored.entrance;
    beginVisualTimer();
  } catch {
    localStorage.removeItem("rainier-active-timer");
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
  await Promise.all([loadCurrentData(), loadConditions()]);
  await loadForecast();
  restoreTimer();

  document.querySelector("#planner-entrance").addEventListener("change", loadForecast);
  document.querySelector("#planner-day-type").addEventListener("change", loadForecast);
  document.querySelector("#planner-date").addEventListener("change", loadForecast);
  document.querySelector("#start-timer").addEventListener("click", startTimer);
  document.querySelector("#stop-timer").addEventListener("click", stopTimer);

  window.setInterval(() => {
    loadCurrentData();
    loadConditions();
  }, 60_000);
}

initialize();
