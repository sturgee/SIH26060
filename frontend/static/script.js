let currentData = null;
let history = [];

const MAX_CHART_POINTS = 60;
const chartInstances = {};
let dataWatchdog = null;

const $ = (id) => document.getElementById(id);

function number(value, digits = 1) {
  return Number.isFinite(Number(value))
    ? Number(value).toFixed(digits)
    : "—";
}

function showDataWarning() {
  $("dataWarning")?.classList.add("visible");
}

function hideDataWarning() {
  $("dataWarning")?.classList.remove("visible");
}

function resetDataWatchdog() {
  hideDataWarning();
  clearTimeout(dataWatchdog);
  dataWatchdog = setTimeout(showDataWarning, 1000);
}

function timestampOf(item) {
  return item.timestamp || item.payload?.timestamp;
}

function timeLabel(value) {
  if (!value) return "";

  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function chartOptions(categories) {
  return {
    categories,
    labels: {
      show: true,
      rotate: -35,
      hideOverlappingLabels: true,
      style: {
        colors: "#8da3ba",
        fontSize: "11px",
      },
    },
    axisBorder: { show: false },
    axisTicks: { show: false },
    tickAmount: Math.min(6, categories.length),
  };
}

function updateLineChart(element, values, options = {}) {
  if (!element) return;

  const records = history.slice(-MAX_CHART_POINTS);
  const categories = records.map((item) => timeLabel(timestampOf(item)));

  const data = values
    .slice(-MAX_CHART_POINTS)
    .map((value) => Number.isFinite(Number(value)) ? Number(value) : null);

  if (!data.some((value) => value !== null)) {
    element.innerHTML = `<div class="chart-empty">No data</div>`;
    return;
  }

  const series = [{
    name: options.name || "Value",
    data,
  }];

  if (chartInstances[element.id]) {
    chartInstances[element.id].updateOptions({
      xaxis: chartOptions(categories),
    }, false, false);

    chartInstances[element.id].updateSeries(series, false);
    return;
  }

  element.innerHTML = "";

  const chart = new ApexCharts(element, {
    chart: {
      type: "area",
      height: options.height || 130,
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
      background: "transparent",
    },
    series,
    colors: [options.color || "#56b4ff"],
    stroke: {
      curve: "smooth",
      width: 3,
    },
    fill: {
      type: "gradient",
      gradient: {
        opacityFrom: 0.35,
        opacityTo: 0.03,
      },
    },
    markers: {
      size: 0,
      hover: { size: 5 },
    },
    xaxis: chartOptions(categories),
    yaxis: {
      labels: {
        style: { colors: "#8da3ba" },
        formatter: (value) => Number(value).toFixed(1),
      },
    },
    grid: {
      borderColor: "#203650",
      strokeDashArray: 4,
    },
    tooltip: {
      theme: "dark",
      x: { show: true },
    },
    dataLabels: { enabled: false },
  });

  chartInstances[element.id] = chart;
  chart.render();
}

function valueFrom(item, paths) {
  for (const path of paths) {
    let value = item.payload;

    for (const key of path.split(".")) {
      value = value?.[key];
    }

    if (Number.isFinite(Number(value))) {
      return Number(value);
    }
  }

  return null;
}

function renderMetrics(data) {
  const metrics = $("metrics");
  if (!metrics) return;

  metrics.innerHTML = [
    ["⚡", "Power load", `${number(data.energy?.consumption?.total_power)} kW`],
    ["💧", "Fresh water", `${number(data.water?.fresh_water?.remaining, 0)} L`],
    ["🍱", "Food supply", `${number(data.food?.estimated_days_remaining)} days`],
    ["⛽", "Fuel remaining", `${number(data.logistics?.fuel?.total_remaining, 0)} L`],
    ["👥", "Personnel", data.logistics?.personnel?.current ?? "—"],
  ].map(([icon, label, value]) => `
    <div class="metric">
      <div class="metric-label">${icon} ${label}</div>
      <div class="metric-value">${value}</div>
    </div>
  `).join("");
}

function renderResources(data) {
  const container = $("resourceList");
  if (!container) return;

  const resources = [
    ["Fuel", data.logistics?.fuel?.total_remaining, "L"],
    ["Fresh water", data.water?.fresh_water?.remaining, "L"],
    ["Food", data.food?.total_remaining, "kg"],
  ];

  container.innerHTML = resources.map(([name, value, unit]) => `
    <div class="resource-row">
      <div class="resource-info">
        <span>${name}</span>
        <strong>${number(value, 0)} ${unit}</strong>
      </div>
    </div>
  `).join("");
}

function renderEnergy(data) {
  const energy = data.energy || {};
  const generators = energy.generators || [];
  const container = $("energyChart");

  if (!container) return;

  const records = history.slice(-MAX_CHART_POINTS);
  const categories = records.map((item) => timeLabel(timestampOf(item)));

  const series = generators.map((generator, index) => ({
    name: generator.name || `Generator ${index + 1}`,
    data: records.map((item) => {
      const value = item.payload?.energy?.generators?.[index]?.output_power;
      return Number.isFinite(Number(value)) ? Number(value) : null;
    }),
  }));

  if (!series.length) return;

  if (chartInstances.energyChart) {
    chartInstances.energyChart.updateOptions({
      xaxis: chartOptions(categories),
    }, false, false);

    chartInstances.energyChart.updateSeries(series, false);
    return;
  }

  const chart = new ApexCharts(container, {
    chart: {
      type: "area",
      height: 240,
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
    },
    series,
    colors: ["#56b4ff", "#a78bfa", "#4ade80"],
    stroke: {
      curve: "smooth",
      width: 3,
    },
    fill: {
      type: "gradient",
      gradient: {
        opacityFrom: 0.3,
        opacityTo: 0.02,
      },
    },
    xaxis: chartOptions(categories),
    yaxis: {
      labels: {
        style: { colors: "#8da3ba" },
        formatter: (value) => `${Number(value).toFixed(0)} kW`,
      },
    },
    legend: {
      position: "top",
      labels: { colors: "#8da3ba" },
    },
    grid: {
      borderColor: "#203650",
      strokeDashArray: 4,
    },
    tooltip: { theme: "dark" },
    dataLabels: { enabled: false },
  });

  chartInstances.energyChart = chart;
  chart.render();
}

function renderHealth(data) {
  const container = $("healthList");
  if (!container) return;

  const systems = data.infrastructure?.systems || [];

  container.innerHTML = systems.map((system) => `
    <div>
      <span>${system.name}</span>
      <strong>${system.health ?? "—"}% · ${system.status ?? "unknown"}</strong>
    </div>
  `).join("");
}

function renderConditions(data) {
  const container = $("conditions");
  if (!container) return;

  const environment = data.environment || {};

  const conditions = [
    ["Temperature", `${number(environment.external_temperature?.value)} °C`],
    ["Wind speed", `${number(environment.wind_speed?.value)} km/h`],
    ["Humidity", `${number(environment.relative_humidity?.value)}%`],
    ["Pressure", `${number(environment.atmospheric_pressure?.value)} hPa`],
  ];

  container.innerHTML = conditions.map(([label, value]) => `
    <div class="condition">
      <strong>${value}</strong>
      <span>${label}</span>
    </div>
  `).join("");
}

function renderLogistics(data) {
  const container = $("logistics");
  if (!container) return;

  const logistics = data.logistics || {};

  container.innerHTML = `
    <div class="logistics-row">
      <span>Personnel</span>
      <strong>${logistics.personnel?.current ?? "—"}</strong>
    </div>
    <div class="logistics-row">
      <span>Capacity</span>
      <strong>${logistics.personnel?.capacity ?? "—"}</strong>
    </div>
  `;
}

function render(data) {
  if (!data) return;

  currentData = data;

  $("stationName").textContent = data.station?.name || "Unknown station";
  $("stationLocation").textContent =
    `${data.station?.location?.latitude ?? "—"}°, ` +
    `${data.station?.location?.longitude ?? "—"}°`;

  $("lastUpdate").textContent = data.timestamp
    ? new Date(data.timestamp).toLocaleString()
    : "—";

  const records = history.slice(-MAX_CHART_POINTS);

  const temperatures = records.map((item) => valueFrom(item, [
    "environment.external_temperature.value",
    "environment.external_temperature",
  ]));

  const wind = records.map((item) => valueFrom(item, [
    "environment.wind_speed.value",
    "environment.wind_speed",
  ]));

  $("temperatureValue").textContent =
    number(data.environment?.external_temperature?.value);

  $("windValue").textContent =
    number(data.environment?.wind_speed?.value);

  renderMetrics(data);
  renderResources(data);
  renderEnergy(data);
  renderHealth(data);
  renderConditions(data);
  renderLogistics(data);

  updateLineChart($("temperatureChart"), temperatures, {
    name: "Temperature",
    color: "#fb7185",
    height: 170,
  });

  updateLineChart($("windChart"), wind, {
    name: "Wind speed",
    color: "#56b4ff",
    height: 170,
  });
}

function setConnection(online) {
  $("connectionDot")?.classList.toggle("offline", !online);
  $("connectionText").textContent = online
    ? "Live connection"
    : "Disconnected";
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);

  socket.onopen = () => {
    setConnection(true);
    resetDataWatchdog();
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "initial") {
      history = message.history || [];

      if (message.latest) {
        render(message.latest);
        resetDataWatchdog();
      } else {
        showDataWarning();
      }

      return;
    }

    history.push({
      timestamp: message.timestamp,
      payload: message,
    });

    history = history.slice(-MAX_CHART_POINTS);
    render(message);
    resetDataWatchdog();
  };

  socket.onclose = () => {
    clearTimeout(dataWatchdog);
    showDataWarning();
    setConnection(false);
    setTimeout(connect, 3000);
  };

  socket.onerror = () => {
    showDataWarning();
    socket.close();
  };
}

connect();