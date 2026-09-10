let currentData = null;
let history = [];

const MAX_CHART_POINTS = 20; // Sliding window timeline size
const chartInstances = {};

const $ = (id) => document.getElementById(id);

function number(value, digits = 1) {
  return value === undefined || value === null
    ? "—"
    : Number(value).toFixed(digits);
}

// ========================================================
// 1. DYNAMIC APEXCHARTS LOADER & INJECT ENGINE
// ========================================================
function loadApexChartsAndRender(callback) {
  if (window.ApexCharts) {
    callback();
    return;
  }
  // Inject CDN dynamically if header file script is commented out
  const script = document.createElement("script");
  script.src = "https://jsdelivr.net";
  script.onload = callback;
  document.head.appendChild(script);
}

// Core rendering blueprint for environmental timeline grids
function drawChart(element, values, options = {}) {
  const id = element.id;
  const validValues = values.map(Number).filter(Number.isFinite).slice(-MAX_CHART_POINTS);

  if (!validValues.length) {
    if (chartInstances[id]) {
      chartInstances[id].destroy();
      delete chartInstances[id];
    }
    element.innerHTML = `<div class="chart-empty" style="color:#8da3ba;padding:20px;text-align:center;">No data</div>`;
    return;
  }

  const recentHistory = history.slice(-MAX_CHART_POINTS);
  const chartData = validValues.map((val, idx) => {
    const historyItem = recentHistory[idx];
    const timestamp = historyItem && historyItem.timestamp 
      ? new Date(historyItem.timestamp).getTime() 
      : new Date().getTime();
    return [timestamp, val];
  });

  if (chartInstances[id]) {
    chartInstances[id].updateOptions({
      series: [{ name: options.name || "Value", data: chartData }]
    }, false, false);
    return;
  }

  element.innerHTML = "";
  const chart = new ApexCharts(element, {
    chart: {
      type: "area",
      height: options.height || 140,
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
      background: "transparent",
      foreColor: "#8da3ba"
    },
    theme: { mode: "dark" },
    series: [{ name: options.name || "Value", data: chartData }],
    colors: [options.color || "#56b4ff"],
    stroke: { curve: "smooth", width: 3 },
    fill: { type: "gradient", gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.03 } },
    xaxis: {
      type: 'datetime',
      labels: { show: true, datetimeUTC: false, format: 'hh:mm:ss TT', style: { fontSize: "10px" } },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      tickAmount: 3,
      labels: { style: { colors: "#8da3ba" }, formatter: value => Number(value).toFixed(1) }
    },
    grid: { borderColor: "#203650", strokeDashArray: 4 },
    tooltip: { theme: "dark", x: { format: 'hh:mm:ss TT' } },
    dataLabels: { enabled: false }
  });

  chartInstances[id] = chart;
  chart.render();
}

// Custom multi-series renderer comparing tracking variables vs predictive arrays
function drawEnergyChart(element, predictionData = {}) {
  const id = element.id;

  // A. Map historic actual wind logs from database streams
  const actualWindData = history
    .map(item => Number(item.payload?.environment?.wind_speed?.value ?? item.payload?.wind_speed?.value ?? item.payload?.wind_speed))
    .filter(Number.isFinite)
    .slice(-MAX_CHART_POINTS);

  const currentWind = currentData?.environment?.wind_speed?.value ?? currentData?.wind_speed?.value ?? currentData?.wind_speed ?? 0;
  const historicalSeries = actualWindData.length ? actualWindData : [Number(currentWind)];

  // B. Pull upcoming predictive projections lines from prediction matrix maps
  const windForecastValues = predictionData?.series?.["environment.wind_speed.value"]?.values || 
                             predictionData?.series?.["wind_speed"]?.values || [];
  const validForecast = windForecastValues.map(Number).filter(Number.isFinite);

  const series = [
    { name: "💨 Actual Wind Speed (km/h)", data: historicalSeries },
    { name: "🔮 Predicted Wind Speed (km/h)", data: validForecast }
  ];

  const maxPoints = Math.max(...series.map(item => item.data.length), 1);
  const categories = Array.from({ length: maxPoints }, (_, index) => index + 1);

  if (chartInstances[id]) {
    chartInstances[id].updateOptions({
      xaxis: { categories },
      series: series
    }, false, false);
    return;
  }

  element.innerHTML = "";
  const chart = new ApexCharts(element, {
    chart: {
      type: "area",
      height: 170,
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
      background: "transparent",
      foreColor: "#8da3ba"
    },
    theme: { mode: "dark" },
    series,
    colors: ["#56b4ff", "#fbbf24"], // Sky Blue actual vs Amber predictive trends
    stroke: { curve: "smooth", width: 3 },
    fill: { type: "gradient", gradient: { opacityFrom: 0.25, opacityTo: 0.02 } },
    markers: { size: 0, hover: { size: 5 } },
    legend: { position: "top", labels: { colors: "#8da3ba" } },
    xaxis: {
      categories,
      labels: { show: true, style: { colors: "#8da3ba", fontSize: "10px" } },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      labels: { style: { colors: "#8da3ba" }, formatter: value => `${Number(value).toFixed(1)} km/h` }
    },
    grid: { borderColor: "#203650", strokeDashArray: 4 },
    tooltip: { theme: "dark", y: { formatter: value => `${Number(value).toFixed(1)} km/h` } },
    dataLabels: { enabled: false }
  });

  chartInstances[id] = chart;
  chart.render();
}

// ========================================================
// 2. WIND TELEMETRY PIPELINE HANDLING
// ========================================================
function render(data) {
  if (!data) return;
  currentData = data;

  // Populate textual parameters safely if components exist inside view layout
  if ($("stationName")) $("stationName").textContent = data.station?.name || "Unknown Station";
  if ($("stationLocation")) {
    $("stationLocation").textContent = `${data.station?.location?.latitude ?? "—"}°, ${data.station?.location?.longitude ?? "—"}°`;
  }

  // Update dynamic real-time label node
  const activeWindVal = data.environment?.wind_speed?.value ?? data.wind_speed?.value ?? data.wind_speed;
  if ($("windValue")) $("windValue").textContent = number(activeWindVal);

  // Extract core predictions maps securely
  const predictions = data.predictions || {};

  loadApexChartsAndRender(() => {
    // A. Draw Isolated Environmental Trend timeline graph
    if ($("windChart")) {
      const recentHistory = history.slice(-MAX_CHART_POINTS);
      const windHistoryData = recentHistory.map(
        item => item.payload?.environment?.wind_speed?.value ?? item.payload?.wind_speed?.value ?? item.payload?.wind_speed
      ).filter(Number.isFinite);
      
      drawChart($("windChart"), windHistoryData, {
        name: "Wind speed",
        color: "#56b4ff",
        height: 120
      });
    }

    // B. Draw Side-by-Side Actual vs Prediction Matrix mapping graph inside Energy card container
    if ($("energyChart")) {
      drawEnergyChart($("energyChart"), predictions);
    }
  });
}

// ========================================================
// 3. RUNTIME WEBSOCKET ROUTING CONNECTION
// ========================================================
function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "initial") {
      history = message.history || [];
      render(message.latest);
      return;
    }

    history.push({
      timestamp: message.timestamp || new Date().toISOString(),
      payload: message
    });

    if (history.length > 100) history.shift();
    render(message);
  };

  socket.onclose = () => setTimeout(connect, 3000);
  socket.onerror = () => socket.close();
}

// Attach click navigation callback sequences cleanly to back action bar triggers
document.addEventListener("DOMContentLoaded", () => {
  const backBtn = $("btnPrevPage");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      window.location.href = "/"; // Direct routing link back to landing platform
    });
  }
});

connect();
