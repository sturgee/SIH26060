/* ================================================================
   Energy Grid Monitor - live + timestamp-range telemetry frontend
   All dashboard display/input times are explicitly IST (Asia/Kolkata).
   Backend/database timestamps remain UTC.
   ================================================================ */

const MAX_DATA_POINTS = 900;
const HISTORY_LIMIT = 900;
const DISPLAY_TIME_ZONE = "Asia/Kolkata";
let socket = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
let connectedOnce = false;
let chartMode = "live";
let historicalRequest = 0;
let latestPollTimer = null;
let lastFallbackTimestamp = null;

const history = {
    timestamps: [], labels: [], temperature: [], humidity: [], wind: [], solar: [], power: [], load: []
};

function $(id) { return document.getElementById(id); }
function setText(id, value) { const el = $(id); if (el) el.textContent = value; }
function numberAt(value, fallback = null) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }

function getMetrics(payload) {
    const environment = payload?.environment || {};
    const generator = (payload?.energy?.generators || [])[0] || {};
    return {
        timestamp: payload?.timestamp || new Date().toISOString(),
        temperature: numberAt(environment?.external_temperature?.value),
        humidity: numberAt(environment?.relative_humidity?.value),
        wind: numberAt(environment?.wind_speed?.value),
        solar: numberAt(environment?.solar_irradiance?.value),
        power: numberAt(generator?.output_power),
        load: numberAt(generator?.load_percent)
    };
}

// Treat legacy timestamps without an offset as UTC. New backend responses
// always end in Z, making the interpretation unambiguous.
function parseTimestamp(timestamp) {
    if (timestamp instanceof Date) return timestamp;
    if (!timestamp) return new Date(NaN);
    const text = String(timestamp).trim();
    if (/Z$|[+-]\d\d:\d\d$/.test(text)) return new Date(text);
    return new Date(text.endsWith(" ") ? `${text}Z` : `${text}Z`);
}

function formatTime(timestamp, longRange = false) {
    const date = parseTimestamp(timestamp);
    if (Number.isNaN(date.getTime())) return "--";
    return new Intl.DateTimeFormat("en-IN", {
        timeZone: DISPLAY_TIME_ZONE,
        ...(longRange
            ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
            : { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        hour12: true
    }).format(date);
}

function formatDateTimeIST(timestamp) {
    const date = parseTimestamp(timestamp);
    if (Number.isNaN(date.getTime())) return "--";
    return new Intl.DateTimeFormat("en-IN", {
        timeZone: DISPLAY_TIME_ZONE,
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true
    }).format(date);
}

// datetime-local has no timezone. Interpret it as IST and convert to UTC.
function parseISTInput(value) {
    if (!value) return new Date(NaN);
    const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (!match) return new Date(NaN);
    const [, y, mo, d, h, mi, sec = "00"] = match;
    return new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h) - 5, Number(mi) - 30, Number(sec)));
}

function formatInputDate(date) {
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: DISPLAY_TIME_ZONE,
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hour12: false
    }).formatToParts(date).reduce((o, p) => { o[p.type] = p.value; return o; }, {});
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function updateConnection(online) {
    const indicator = $("connection-indicator");
    if (indicator) {
        indicator.classList.toggle("online", online);
        indicator.classList.toggle("offline", !online);
    }
    const status = $("connection-status");
    if (status) status.textContent = chartMode === "history" ? "Historical" : (online ? "Live" : "Disconnected");
}

function appendLog(message) {
    const logs = $("logs");
    if (!logs) return;
    const row = document.createElement("div");
    row.innerHTML = `<span style="color:var(--text-muted)">[${formatTime(new Date())}]</span> ${escapeHtml(message)}`;
    logs.appendChild(row);
    while (logs.children.length > 100) logs.removeChild(logs.firstChild);
    logs.scrollTop = logs.scrollHeight;
}

function escapeHtml(value) {
    return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function pushPoint(target, value) {
    target.push(value);
    if (target.length > MAX_DATA_POINTS) target.shift();
}
function clearHistory() { Object.values(history).forEach(a => a.splice(0, a.length)); }

function addMetrics(metrics, redraw = true) {
    pushPoint(history.timestamps, metrics.timestamp);
    pushPoint(history.labels, formatTime(metrics.timestamp));
    pushPoint(history.temperature, metrics.temperature);
    pushPoint(history.humidity, metrics.humidity);
    pushPoint(history.wind, metrics.wind);
    pushPoint(history.solar, metrics.solar);
    pushPoint(history.power, metrics.power);
    pushPoint(history.load, metrics.load);
    updateMetricCards(metrics);
    if (redraw) redrawCharts();
}

function updateMetricCards(metrics) {
    if (metrics.temperature !== null) setText("temperature", metrics.temperature.toFixed(1));
    if (metrics.humidity !== null) setText("humidity", Math.round(metrics.humidity));
    if (metrics.wind !== null) setText("wind_speed", Math.round(metrics.wind));
    if (metrics.solar !== null) setText("solar_irradiance", Math.round(metrics.solar));
    if (metrics.power !== null) setText("generated_power", metrics.power.toFixed(1));
    if (metrics.load !== null) setText("generator_load", Math.round(metrics.load));
}

function loadInitialMessage(message) {
    if (chartMode !== "live") return;
    clearHistory();
    const rows = Array.isArray(message?.history) ? message.history : [];
    rows.slice(-HISTORY_LIMIT).forEach(row => { if (row?.payload) addMetrics(getMetrics(row.payload), false); });
    if (message?.latest) updateMetricCards(getMetrics(message.latest));
    redrawCharts();
}

function handleTelemetry(payload) {
    if (!payload || typeof payload !== "object") return;
    if (payload.type === "initial") {
        loadInitialMessage(payload);
        appendLog("Historical telemetry loaded. Live stream ready.");
        return;
    }
    if (chartMode === "history") return;
    const metrics = getMetrics(payload);
    addMetrics(metrics, true);
    if (payload?.station?.id) setText("station-id", payload.station.id);
    if (payload?.predictions?.series) renderPredictions(payload.predictions.series);
}

function renderPredictions(series) {
    const target = $("prediction-status");
    if (!target) return;
    const count = Object.keys(series || {}).length;
    target.textContent = count ? `${count} forecast series active` : "No forecast data";
}

async function loadLatestFallback() {
    // REST fallback is intentionally used only when the WebSocket is not open,
    // so a healthy WebSocket does not duplicate chart points.
    if (chartMode !== "live" || (socket && socket.readyState === WebSocket.OPEN)) return;
    try {
        const response = await fetch("/api/telemetry/latest", { cache: "no-store" });
        if (!response.ok) return;
        const latest = await response.json();
        if (!latest?.payload || chartMode !== "live") return;

        updateMetricCards(getMetrics(latest.payload));
        if (latest.station_id) setText("station-id", latest.station_id);

        // If the socket is unavailable, still keep the landing-page charts moving
        // from newly stored MQTT packets. Do not append the same packet twice.
        const ts = latest.timestamp || latest.payload.timestamp;
        if (ts && ts !== lastFallbackTimestamp) {
            lastFallbackTimestamp = ts;
            addMetrics(getMetrics(latest.payload), true);
        }
    } catch (error) {
        console.debug("Latest telemetry REST fallback unavailable", error);
    }
}

function startLatestPolling() {
    clearInterval(latestPollTimer);
    latestPollTimer = setInterval(loadLatestFallback, 2000);
}

function connectDataPipeline() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
    socket.onopen = () => {
        reconnectDelay = 1000; connectedOnce = true; updateConnection(true);
        appendLog("WebSocket connected to live telemetry stream.");
    };
    socket.onmessage = event => { try { handleTelemetry(JSON.parse(event.data)); } catch (e) { console.error("Invalid telemetry message", e); } };
    socket.onerror = error => console.error("WebSocket error:", error);
    socket.onclose = () => {
        updateConnection(false);
        if (connectedOnce) appendLog("WebSocket disconnected. Reconnecting...");
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connectDataPipeline, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    };
}

function drawChart(containerId, series, options = {}) {
    const container = $(containerId);
    if (!container) return;
    const width = Math.max(container.clientWidth || 600, 320);
    const height = options.height || 240;
    const padding = { left: 48, right: 16, top: 28, bottom: 42 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const validSeries = series.map(item => ({ ...item, data: item.data.map(numberAt) }));
    const allValues = validSeries.flatMap(item => item.data).filter(v => v !== null);
    if (!allValues.length) { container.innerHTML = '<div class="chart-empty">No telemetry in selected range.</div>'; return; }

    let min = options.min, max = options.max;
    if (min === undefined || max === undefined) {
        const rawMin = Math.min(...allValues), rawMax = Math.max(...allValues), range = Math.max(rawMax - rawMin, 1);
        min = rawMin - range * 0.1; max = rawMax + range * 0.1;
    }
    if (min === max) max = min + 1;
    const count = Math.max(history.labels.length - 1, 1);
    const x = i => padding.left + (i / count) * plotWidth;
    const y = value => padding.top + ((max - value) / (max - min)) * plotHeight;
    const pathFor = data => data.map((value, i) => value === null ? "" : `${i === 0 || data[i-1] === null ? "M" : "L"} ${x(i).toFixed(2)} ${y(value).toFixed(2)}`).join(" ");
    const grid = [0, .25, .5, .75, 1].map(r => {
        const gy = padding.top + r * plotHeight, value = max - r * (max-min);
        return `<line x1="${padding.left}" y1="${gy}" x2="${width-padding.right}" y2="${gy}" stroke="#e2e8f0" stroke-dasharray="4 4"/><text x="${padding.left-8}" y="${gy+4}" text-anchor="end" fill="#94a3b8" font-size="10">${formatAxis(value)}</text>`;
    }).join("");
    const paths = validSeries.map(item => `<path d="${pathFor(item.data)}" fill="none" stroke="${item.color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`).join("");
    const legend = validSeries.map(item => `<span class="live-chart-legend-item"><i style="background:${item.color}"></i>${escapeHtml(item.name)}</span>`).join("");
    const firstLabel = history.labels[0] || "Waiting", lastLabel = history.labels.at(-1) || "Waiting";
    container.innerHTML = `<div class="live-chart"><div class="live-chart-header">${legend}</div><svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="Telemetry chart">${grid}<line x1="${padding.left}" y1="${padding.top+plotHeight}" x2="${width-padding.right}" y2="${padding.top+plotHeight}" stroke="#cbd5e1"/>${paths}</svg><div class="live-chart-axis"><span>${escapeHtml(firstLabel)}</span><span>${escapeHtml(lastLabel)}</span></div></div>`;
}
function formatAxis(value) { return Math.abs(value) >= 100 ? Math.round(value) : Number(value).toFixed(1); }

function redrawCharts() {
    const longRange = chartMode === "history" && history.timestamps.length > 2 && (parseTimestamp(history.timestamps.at(-1)) - parseTimestamp(history.timestamps[0])) > 86400000;
    if (longRange) history.labels = history.timestamps.map(t => formatTime(t, true));
    drawChart("chart", [{name:"Temperature (°C)",data:history.temperature,color:"#2563eb"},{name:"Humidity (%)",data:history.humidity,color:"#10b981"}]);
    drawChart("energyChart", [{name:"Power Output (kW)",data:history.power,color:"#f59e0b"}], {min:0});
    drawChart("environmentChart", [{name:"Temperature (°C)",data:history.temperature,color:"#2563eb"},{name:"Humidity (%)",data:history.humidity,color:"#10b981"}]);
    drawChart("generatorChart", [{name:"Power (kW)",data:history.power,color:"#f59e0b"},{name:"Load (%)",data:history.load,color:"#8b5cf6"}], {min:0});
}

function createRangeControls() {
    const anchors = [$("chart"), $("environmentChart"), $("generatorChart")].filter(Boolean);
    if (!anchors.length || $("telemetry-range-controls")) return;
    const controls = document.createElement("section");
    controls.id = "telemetry-range-controls";
    controls.className = "telemetry-range-controls";
    controls.innerHTML = `
      <div class="range-top"><div><strong>Telemetry Time Range</strong><span id="range-mode-badge" class="range-badge">LIVE</span></div><button id="live-mode-btn" type="button">↻ Back to Live</button></div>
      <div class="range-fields"><label>Start <input id="range-start" type="datetime-local"></label><label>End <input id="range-end" type="datetime-local"></label><button id="apply-range" type="button">Apply Range</button></div>
      <div class="range-presets"><span>Quick range:</span>${[[5,"5 min"],[15,"15 min"],[30,"30 min"],[60,"1 hr"],[360,"6 hr"],[1440,"24 hr"],[10080,"7 days"],[43200,"30 days"],[129600,"90 days"],[525600,"1 year"]].map(([m,t])=>`<button type="button" data-minutes="${m}">${t}</button>`).join("")}</div>
      <div id="range-status" class="range-status">Live stream active. Select a range to inspect historical telemetry.</div>`;
    // Insert the controls before the chart card itself. The old implementation
    // called section.insertBefore(..., chartElement), but #chart is nested
    // inside the section rather than being its direct child, which causes:
    // "NotFoundError: Failed to execute 'insertBefore' on 'Node'".
    const chartCard = anchors[0].closest(".split-card") || anchors[0].parentElement;
    if (chartCard?.parentElement) {
        chartCard.parentElement.insertBefore(controls, chartCard);
    } else if (anchors[0].parentElement) {
        anchors[0].parentElement.insertBefore(controls, anchors[0]);
    }

    const end = new Date(), start = new Date(end.getTime() - 5*60000);
    $("range-start").value = formatInputDate(start); $("range-end").value = formatInputDate(end);
    document.querySelectorAll("[data-minutes]").forEach(btn => btn.addEventListener("click", () => {
        const mins = Number(btn.dataset.minutes), e = new Date(), s = new Date(e.getTime()-mins*60000);
        $("range-start").value = formatInputDate(s); $("range-end").value = formatInputDate(e); applyHistoricalRange();
    }));
    $("apply-range").addEventListener("click", applyHistoricalRange);
    $("live-mode-btn").addEventListener("click", returnToLive);
}

async function fetchRangeMetric(metric, start, end, requestId) {
    const params = new URLSearchParams({metric, start: start.toISOString(), end: end.toISOString()});
    const response = await fetch(`/api/telemetry/range?${params}`, { cache: "no-store" });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    if (requestId !== historicalRequest) throw new Error("stale request");
    return data;
}

async function applyHistoricalRange() {
    const start = parseISTInput($("range-start")?.value), end = parseISTInput($("range-end")?.value);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) {
        setText("range-status", "Please provide a valid start and end timestamp."); return;
    }
    const requestId = ++historicalRequest;
    chartMode = "history"; updateConnection(false);
    $("range-mode-badge").textContent = "HISTORY";
    setText("range-status", "Loading historical telemetry and selecting proportional resolution…");
    try {
        const metrics = await Promise.all([
            fetchRangeMetric("temperature", start, end, requestId), fetchRangeMetric("humidity", start, end, requestId),
            fetchRangeMetric("wind", start, end, requestId), fetchRangeMetric("solar", start, end, requestId),
            fetchRangeMetric("generator_power", start, end, requestId), fetchRangeMetric("generator_load", start, end, requestId)
        ]);
        clearHistory();
        const byTime = new Map();
        const keys = ["temperature","humidity","wind","solar","power","load"];
        metrics.forEach((series, index) => series.points.forEach(point => {
            const key = parseTimestamp(point.timestamp).toISOString();
            if (!byTime.has(key)) byTime.set(key, {});
            byTime.get(key)[keys[index]] = point.value;
        }));
        [...byTime.keys()].sort().forEach(timestamp => {
            const row = byTime.get(timestamp);
            history.timestamps.push(timestamp); history.labels.push(formatTime(timestamp, (end-start)>86400000));
            history.temperature.push(row.temperature ?? null); history.humidity.push(row.humidity ?? null);
            history.wind.push(row.wind ?? null); history.solar.push(row.solar ?? null); history.power.push(row.power ?? null); history.load.push(row.load ?? null);
        });
        if (history.timestamps.length) updateMetricCards({temperature:history.temperature.at(-1),humidity:history.humidity.at(-1),wind:history.wind.at(-1),solar:history.solar.at(-1),power:history.power.at(-1),load:history.load.at(-1)});
        const bucket = Math.max(...metrics.map(x => x.bucket_seconds || 1));
        const pointCount = history.timestamps.length;
        setText("range-status", `${pointCount.toLocaleString()} chart points • aggregation bucket ${formatDuration(bucket)} • ${formatDateTimeIST(start)} → ${formatDateTimeIST(end)}`);
        redrawCharts();
    } catch (error) {
        if (error.message !== "stale request") {
            console.error(error); setText("range-status", "Unable to load this range. Check that the timestamps contain stored telemetry.");
        }
    }
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.round(seconds/60)} min`;
    if (seconds < 86400) return `${Math.round(seconds/3600)} hr`;
    return `${Math.round(seconds/86400)} day`;
}

function returnToLive() {
    ++historicalRequest;
    chartMode = "live"; $("range-mode-badge").textContent = "LIVE";
    setText("range-status", "Live stream active. Historical selection cleared.");
    clearHistory();
    updateConnection(socket?.readyState === WebSocket.OPEN);
    appendLog("Returned to live telemetry mode.");
    loadLatestFallback();
}

document.addEventListener("DOMContentLoaded", () => {
    createRangeControls();
    updateConnection(false);
    loadLatestFallback();
    startLatestPolling();
    connectDataPipeline();
    window.addEventListener("resize", redrawCharts);
});
window.addEventListener("beforeunload", () => {
    clearInterval(latestPollTimer);
    if (socket) socket.close();
});
