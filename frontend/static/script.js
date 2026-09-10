let currentData = null;
let history = [];

const MAX_CHART_POINTS = 7;
const chartInstances = {};

const $ = (id) => document.getElementById(id);

function number(value, digits = 1) {
  return value === undefined || value === null
    ? "—"
    : Number(value).toFixed(digits);
}

function percent(value, capacity) {
  return capacity ? Math.min(100, value / capacity * 100) : 0;
}

// function drawChart(element, values, options = {}) {
//   const id = element.id;

//   const validValues = values
//     .map(Number)
//     .filter(Number.isFinite)
//     .slice(-MAX_CHART_POINTS);

//   if (!validValues.length) {
//     if (chartInstances[id]) {
//       chartInstances[id].destroy();
//       delete chartInstances[id];
//     }

//     element.innerHTML = `<div class="chart-empty">No data</div>`;
//     return;
//   }

//   // 1. Correctly extract times from the telemetry history array
//   const categories = history
//     .slice(-MAX_CHART_POINTS)
//     .map(item => {
//       if (!item.timestamp) return '';
//       const date = new Date(item.timestamp);
//       return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
//     });

//   const series = [{
//     name: options.name || "Value",
//     data: validValues,
//   }];

//   // 2. Safely push axis updates during runtime updates
//  if (chartInstances[id]) {
//     chartInstances[id].updateOptions({
//       xaxis: { 
//         categories: categories,
//         tickAmount: 4 // ⭐ Make sure this is added here too!
//       },
//       yaxis: {
//         tickAmount: 3 // ⭐ Make sure this is added here too!
//       }
//     }, false, false);

//     chartInstances[id].updateSeries(series, false);
//     return;
//   }

//   element.innerHTML = "";

//   // 3. Initialize ApexCharts with strict color and display visibility rules
//   const chart = new ApexCharts(element, {
//     chart: {
//       type: options.type || "area",
//       height: options.height || 130,
//       toolbar: { show: false },
//       zoom: { enabled: false },
//       animations: {
//         enabled: false,
//       },
//       background: "transparent",
//     },
//     series,
//     colors: [options.color || "#56b4ff"],
//     stroke: {
//       curve: "smooth",
//       width: 3,
//     },
//     fill: {
//       type: "gradient",
//       gradient: {
//         shadeIntensity: 1,
//         opacityFrom: 0.35,
//         opacityTo: 0.03,
//       },
//     },
//     markers: {
//       size: 0,
//       hover: { size: 5 },
//     },
//     xaxis: {
//       categories: categories,
//       type: 'category',
//       labels: { 
//         show: true,
//         style: {
//           colors: "#8da3ba",
//           fontSize: "10px"
//         }
//       },
//       axisBorder: { show: false },
//       axisTicks: { show: false },
//     },
//     yaxis: {
//       labels: {
//         style: { colors: "#8da3ba" },
//         formatter: value => Number(value).toFixed(1),
//       },
//     },
//     grid: {
//       borderColor: "#203650",
//       strokeDashArray: 4,
//     },
//     tooltip: {
//       theme: "dark",
//       x: { show: true },
//       y: {
//         formatter: value => Number(value).toFixed(2),
//       },
//     },
//     dataLabels: { enabled: false },
//   });

//   chartInstances[id] = chart;
//   chart.render();
// }
function drawChart(element, values, options = {}) {
  const id = element.id;

  // 1. Map values and take recent points cleanly
  const validValues = values
    .map(Number)
    .filter(Number.isFinite)
    .slice(-MAX_CHART_POINTS);

  if (!validValues.length) {
    if (chartInstances[id]) {
      chartInstances[id].destroy();
      delete chartInstances[id];
    }
    element.innerHTML = `<div class="chart-empty">No data</div>`;
    return;
  }

  // 2. Extract RAW UNIX Timestamps (Numbers) for the chart engine
  const recentHistory = history.slice(-MAX_CHART_POINTS);
  const chartData = validValues.map((val, idx) => {
    const historyItem = recentHistory[idx];
    // Fallback to current time if historical timestamps aren't generated yet
    const timestamp = historyItem ? new Date(historyItem.timestamp).getTime() : new Date().getTime();
    return [timestamp, val];
  });

  // 3. If chart exists, perform a unified single layout refresh update
  if (chartInstances[id]) {
    chartInstances[id].updateSeries([{
      name: options.name || "Value",
      data: chartData
    }], true);
    return;
  }

  element.innerHTML = "";

  // 4. Construct the initial chart instance with absolute layout protection
  const chart = new ApexCharts(element, {
    chart: {
      type: options.type || "area",
      height: options.height || 140, // Increased slightly to give text breathing room
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
      background: "transparent",
      foreColor: "#8da3ba" // Colors labels globally
    },
    series: [{
      name: options.name || "Value",
      data: chartData
    }],
    colors: [options.color || "#56b4ff"],
    stroke: { curve: "smooth", width: 3 },
    fill: {
      type: "gradient",
      gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.03 }
    },
    xaxis: {
      type: 'datetime', // Changed to datetime to activate intelligent text spacing
      labels: {
        show: true,
        style: { fontSize: "10px", colors: "#8da3ba" },
        datetimeUTC: false, // Uses your local machine time structure
        format: 'hh:mm:ss TT' // Formats text neatly (e.g., 12:25:31 AM)
      },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      tickAmount: 3, // Enforces clean, non-stacking vertical gaps
      labels: {
        style: { colors: "#8da3ba" },
        formatter: value => Number(value).toFixed(1)
      }
    },
    grid: { borderColor: "#203650", strokeDashArray: 4 },
    tooltip: {
      theme: "dark",
      x: { format: 'hh:mm:ss TT' }
    },
    dataLabels: { enabled: false }
  });

  chartInstances[id] = chart;
  chart.render();
}


function drawEnergyChart(element, generators) {
  const id = element.id;

  const series = generators.map((generator, generatorIndex) => ({
    name: generator.name || `Generator ${generatorIndex + 1}`,
    data: history
      .map(item =>
        Number(
          item.payload?.energy?.generators?.[generatorIndex]?.output_power
        )
      )
      .filter(Number.isFinite)
      .slice(-MAX_CHART_POINTS),
  }));

  if (!series.some(item => item.data.length)) {
    generators.forEach((generator, index) => {
      series[index].data = [
        Number(generator.output_power) || 0,
      ];
    });
  }

  const categories = history
    .slice(-MAX_CHART_POINTS)
    .map(item => {
      if (!item.timestamp) return '';
      const date = new Date(item.timestamp);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    });

  if (chartInstances[id]) {
    chartInstances[id].updateOptions({
      xaxis: { categories },
    }, false, false);

    chartInstances[id].updateSeries(series, false);
    return;
  }

  element.innerHTML = "";

  const chart = new ApexCharts(element, {
    chart: {
      type: "area",
      height: 170,
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: {
        enabled: false,
      },
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
    markers: {
      size: 0,
      hover: { size: 5 },
    },
    legend: {
      position: "top",
      labels: { colors: "#8da3ba" },
    },
    xaxis: {
      categories,
      labels: { 
        show: true,
        style: {
          colors: "#8da3ba",
          fontSize: "10px"
        }
      },
      axisBorder: { show: false },
      axisTicks: { show: false },
    },
    yaxis: {
      labels: {
        style: { colors: "#8da3ba" },
        formatter: value => `${Number(value).toFixed(0)} kW`,
      },
    },
    grid: {
      borderColor: "#203650",
      strokeDashArray: 4,
    },
    tooltip: {
      theme: "dark",
      y: {
        formatter: value => `${Number(value).toFixed(1)} kW`,
      },
    },
    dataLabels: { enabled: false },
  });

  chartInstances[id] = chart;
  chart.render();
}

function renderMetrics(data) {
  const energy = data.energy || {};
  const water = data.water?.fresh_water || {};
  const food = data.food || {};
  const logistics = data.logistics || {};

  $("metrics").innerHTML = [
    ["⚡", "Power load", `${number(energy.consumption?.total_power)} kW`],
    ["⛽", "Fuel remaining", `${number(logistics.fuel?.total_remaining, 0)} L`],
    ["💧", "Fresh water", `${number(water.remaining, 0)} L`],
    ["🍱", "Food supply", `${number(food.estimated_days_remaining)} days`],
    ["👥", "Personnel", `${logistics.personnel?.current ?? "—"} / ${logistics.personnel?.capacity ?? "—"}`],
  ].map(([icon, label, value]) => `
    <div class="metric">
      <div class="metric-label">${icon} ${label}</div>
      <div class="metric-value">${value}</div>
    </div>
  `).join("");
}

function renderResources(data) {
  const water = data.water || {};
  const food = data.food || {};
  const fuel = data.logistics?.fuel || {};

  const resources = [
    ["Fuel", fuel.total_remaining, "L", 20000],
    ["Fresh water", water.fresh_water?.remaining, "L", water.fresh_water?.capacity],
    ["Meltwater", water.meltwater_reservoir?.remaining, "L", water.meltwater_reservoir?.capacity],
    ["Food", food.total_remaining, "kg", 5000],
  ];

  $("resourceList").innerHTML = resources.map(([name, value, unit, capacity]) => `
    <div class="resource-row">
      <div class="resource-info">
        <span>${name}</span>
        <strong>${number(value, 0)} ${unit}</strong>
      </div>
      <div class="progress">
        <i style="width:${percent(value || 0, capacity)}%"></i>
      </div>
    </div>
  `).join("");
}

function renderEnergy(data) {
  const energy = data.energy || {};
  const generators = energy.generators || [];

  $("batteryValue").textContent =
    `Battery ${number(energy.battery?.state_of_charge)}%`;

  drawEnergyChart($("energyChart"), generators);

  $("generatorList").innerHTML = generators.map((generator) => `
    <div>
      <span>${generator.name}</span>
      <strong class="${generator.status === "running" ? "good" : ""}">
        ${generator.status} · ${number(generator.output_power)} kW
      </strong>
    </div>
  `).join("");
}

function renderHealth(data) {
  const systems = data.infrastructure?.systems || [];

  $("healthList").innerHTML = systems.map((system) => `
    <div>
      <span>${system.name}</span>
      <strong class="${system.health >= 80 ? "good" : "warning"}">
        ${system.health}% · ${system.status}
      </strong>
    </div>
  `).join("");
}

function renderConditions(data) {
  const environment = data.environment || {};

  const conditions = [
    ["Temperature", `${number(environment.external_temperature?.value)} °C`],
    ["Wind speed", `${number(environment.wind_speed?.value)} km/h`],
    ["Humidity", `${number(environment.relative_humidity?.value)}%`],
    ["Pressure", `${number(environment.atmospheric_pressure?.value)} hPa`],
    ["Visibility", `${number(environment.visibility?.value)} km`],
    ["Solar irradiance", `${number(environment.solar_irradiance?.value)} W/m²`],
  ];

  $("conditions").innerHTML = conditions.map(([name, value]) => `
    <div class="condition">
      <strong>${value}</strong>
      <span>${name}</span>
    </div>
  `).join("");
}

function renderLogistics(data) {
  const logistics = data.logistics || {};
  const personnel = logistics.personnel || {};
  const resupply = logistics.next_resupply || {};

  $("logistics").innerHTML = `
    <div class="logistics-row">
      <span>Personnel</span>
      <strong>${personnel.current ?? "—"} / ${personnel.capacity ?? "—"}</strong>
    </div>
    <div class="logistics-row">
      <span>Next resupply</span>
      <strong>${resupply.scheduled_at
        ? new Date(resupply.scheduled_at).toLocaleDateString()
        : "—"}</strong>
    </div>
    <div class="logistics-row">
      <span>Fuel delivery</span>
      <strong>${number(resupply.fuel_delivery, 0)} L</strong>
    </div>
    <div class="logistics-row">
      <span>Food delivery</span>
      <strong>${number(resupply.food_delivery, 0)} kg</strong>
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

//   const temperatures = history.map(
//     item => item.payload?.environment?.external_temperature?.value
//   ).filter(Number.isFinite);

//   const wind = history.map(
//     item => item.payload?.environment?.wind_speed?.value
//   ).filter(Number.isFinite);

//   drawChart($("temperatureChart"), temperatures, {
//     name: "Temperature",
//     color: "#fb7185",
//     height: 110,
//   });

//   drawChart($("windChart"), wind, {
//     name: "Wind speed",
//     color: "#56b4ff",
//     height: 110,
//   });
// }
const recentHistory = history.slice(-MAX_CHART_POINTS);

  const temperatures = recentHistory.map(
    item => item.payload?.environment?.external_temperature?.value ?? item.payload?.environment?.value ?? item.payload?.value
  ).filter(Number.isFinite);

  const wind = recentHistory.map(
    item => item.payload?.environment?.wind_speed?.value ?? item.payload?.wind_speed?.value ?? item.payload?.value
  ).filter(Number.isFinite);

  drawChart($("temperatureChart"), temperatures, {
    name: "Temperature",
    color: "#fb7185",
    height: 120,
  });

  drawChart($("windChart"), wind, {
    name: "Wind speed",
    color: "#56b4ff",
    height: 120,
  });
}

function setConnection(online) {
  $("connectionDot").classList.toggle("offline", !online);
  $("connectionText").textContent = online ? "Live connection" : "Disconnected";
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);

  socket.onopen = () => setConnection(true);

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "initial") {
      history = message.history || [];
      render(message.latest);
      return;
    }

    history.push({
      timestamp: message.timestamp,
      payload: message,
    });

    history = history.slice(-100);
    render(message);
  };

  socket.onclose = () => {
    setConnection(false);
    setTimeout(connect, 3000);
  };

  socket.onerror = () => socket.close();
}

connect();