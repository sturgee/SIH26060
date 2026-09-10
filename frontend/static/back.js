let currentData = null;
let history = [];

const MAX_CHART_POINTS = 20; // Rolling viewport window timeline size
const chartInstances = {};

const $ = (id) => document.getElementById(id);

function number(value, digits = 1) {
  return value === undefined || value === null
    ? "—"
    : Number(value).toFixed(digits);
}

// Helper utility to strictly find asset matching ID "GEN-01" out of the generators list array
function findGen01(generatorsList) {
  if (!Array.isArray(generatorsList)) return null;
  return generatorsList.find(gen => gen && gen.id === "GEN-01") || generatorsList[0] || null;
}

// ========================================================
// 1. GEN-01 ACTUAL CORE LINE ENGINE (LEFT CARD CONTAINER)
// ========================================================
function drawActualFuelChart(element, values) {
  const id = element.id;
  const validValues = values.map(Number).filter(Number.isFinite).slice(-MAX_CHART_POINTS);

  if (!validValues.length) {
    if (chartInstances[id]) {
      chartInstances[id].destroy();
      delete chartInstances[id];
    }
    element.innerHTML = `<div class="chart-empty" style="color:#8da3ba;padding:20px;text-align:center;">Waiting for database telemetry...</div>`;
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
      series: [{ name: "Live Consumption (GEN-01)", data: chartData }]
    }, false, false);
    return;
  }

  element.innerHTML = "";
  const chart = new ApexCharts(element, {
    chart: {
      type: "area",
      height: 140, 
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
      background: "transparent",
      foreColor: "#8da3ba"
    },
    theme: { mode: "dark" },
    series: [{ name: "Live Consumption (GEN-01)", data: chartData }],
    colors: ["#a78bfa"], // Sleek Purple theme targeting fuel performance
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
      labels: { style: { colors: "#8da3ba" }, formatter: value => `${Number(value).toFixed(1)} L/h` }
    },
    grid: { borderColor: "#203650", strokeDashArray: 4 },
    tooltip: { theme: "dark", x: { format: 'hh:mm:ss TT' }, y: { formatter: value => `${Number(value).toFixed(1)} L/h` } },
    dataLabels: { enabled: false }
  });

  chartInstances[id] = chart;
  chart.render();
}

// ========================================================
// 2. GEN-01 FORECAST TIMELINE ENGINE (RIGHT CARD CONTAINER)
// ========================================================
function drawPredictedFuelChart(element, forecastValues) {
  const id = element.id;
  const validForecast = forecastValues.map(Number).filter(Number.isFinite);

  const series = [{
    name: "Predicted Consumption (GEN-01)",
    data: validForecast
  }];

  const maxPoints = Math.max(validForecast.length, 1);
  const categories = Array.from({ length: maxPoints }, (_, index) => `Step ${index + 1}`);

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
    colors: ["#fbbf24"], // Vibrant Amber explicitly mapping predictions
    stroke: { curve: "smooth", width: 3 },
    fill: { type: "gradient", gradient: { opacityFrom: 0.25, opacityTo: 0.02 } },
    markers: { size: 0, hover: { size: 5 } },
    xaxis: {
      categories,
      labels: { show: true, style: { colors: "#8da3ba", fontSize: "10px" } },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      labels: { style: { colors: "#8da3ba" }, formatter: value => `${Number(value).toFixed(1)} L/h` }
    },
    grid: { borderColor: "#203650", strokeDashArray: 4 },
    tooltip: { theme: "dark", y: { formatter: value => `${Number(value).toFixed(1)} L/h` } },
    dataLabels: { enabled: false }
  });

  chartInstances[id] = chart;
  chart.render();
}

// ========================================================
// 3. TELEMETRY DATA INTERPRETER AND INJECTOR PIPELINE
// ========================================================
function render(data) {
  if (!data) return;
  currentData = data;

  // Sync Station Title Text Node
  if ($("stationName")) $("stationName").textContent = data.station?.name || "Unknown Station";

  // Isolate current state for exact asset code "GEN-01"
  const gen01Data = findGen01(data.energy?.generators || []);
  const liveFuelValue = gen01Data ? gen01Data.fuel_consumption_rate : 0;

  // Extract prediction sequence matrix target key
  const predictions = data.predictions || {};
  
  // Directly targeting the specific JSON sequence path string key for generator 0
  const fuelForecastValues = predictions.series?.["energy.generators[0].fuel_consumption_rate"]?.values || 
                             predictions.series?.["energy.generators.fuel_consumption_rate"]?.values || [];

  // Inject text metric details into the specific HTML text elements rows
  if ($("windValue")) $("windValue").textContent = number(liveFuelValue);
  if ($("act_value")) $("act_value").textContent = `${number(liveFuelValue)} L/h`;
  if ($("pre_value")) {
    const nextForecastValue = fuelForecastValues[0]; // Fetch first upcoming step prediction index value
    $("pre_value").textContent = nextForecastValue !== undefined ? `${number(nextForecastValue)} L/h` : "—";
  }

  // A. Plot real-time actual GEN-01 fuel data directly into Left Column container (#windChart)
  if ($("windChart")) {
    const recentHistory = history.slice(-MAX_CHART_POINTS);
    const actualFuelHistory = recentHistory
      .map(item => {
        const targetGen = findGen01(item.payload?.energy?.generators || []);
        return targetGen ? targetGen.fuel_consumption_rate : null;
      })
      .filter(val => val !== null && Number.isFinite(val));

    drawActualFuelChart($("windChart"), actualFuelHistory.length ? actualFuelHistory : [Number(liveFuelValue)]);
  }

  // B. Plot the future prediction array steps values inside the Right Column container (#energyChart)
  if ($("energyChart")) {
    drawPredictedFuelChart($("energyChart"), fuelForecastValues);
  }
}

// ========================================================
// 4. WEBSOCKET REALTIME NETWORK EVENT RUNTIME
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

// Bind navigation callbacks neatly when browser mounting frames assemble
document.addEventListener("DOMContentLoaded", () => {
  const backBtn = $("btnPrevPage");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      window.location.href = "/"; // Direct routing link dropped back to home views path
    });
  }
});

// Structural helper function preventing console button action trigger crashes
function switchView(viewName) {
  console.log(`View context focused securely: ${viewName}`);
}

connect();
