const history = [];
const MAX_POINTS = 60;
let temperatureChart;
let windChart;
let watchdog;

const $ = (id) => document.getElementById(id);

function valueOf(object, path) {
  return path.split(".").reduce((value, key) => value?.[key], object);
}

function numeric(object, paths) {
  for (const path of paths) {
    const value = Number(valueOf(object, path));
    if (Number.isFinite(value)) return value;
  }

  return null;
}

function format(value, unit = "", digits = 1) {
  return Number.isFinite(value)
    ? `${value.toFixed(digits)} ${unit}`
    : "—";
}

function timestampOf(item) {
  return item.timestamp || item.payload?.timestamp;
}

function timeLabel(timestamp) {
  return timestamp
    ? new Date(timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "";
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
    tickAmount: Math.min(6, categories.length),
    axisBorder: { show: false },
    axisTicks: { show: false },
  };
}

function updateChart(existing, element, name, values, color, unit) {
  const records = history.slice(-MAX_POINTS);
  const categories = records.map((item) => timeLabel(timestampOf(item)));

  const series = [{
    name,
    data: values.slice(-MAX_POINTS),
  }];

  if (existing) {
    existing.updateOptions({
      xaxis: chartOptions(categories),
    }, false, false);

    existing.updateSeries(series, false);
    return existing;
  }

  const chart = new ApexCharts(element, {
    chart: {
      type: "area",
      height: 300,
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
    },
    series,
    colors: [color],
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
        formatter: (value) => `${Number(value).toFixed(1)} ${unit}`,
      },
    },
    grid: {
      borderColor: "#203650",
      strokeDashArray: 4,
    },
    tooltip: {
      theme: "dark",
      y: {
        formatter: (value) => `${Number(value).toFixed(1)} ${unit}`,
      },
    },
    dataLabels: { enabled: false },
  });

  chart.render();
  return chart;
}

function render(data) {
  if (!data) return;

  const environment = data.environment || {};

  $("stationName").textContent = data.station?.name || "Environment";
  $("stationLocation").textContent =
    `${data.station?.location?.latitude ?? "—"}°, ` +
    `${data.station?.location?.longitude ?? "—"}°`;

  $("lastUpdate").textContent = data.timestamp
    ? new Date(data.timestamp).toLocaleString()
    : "—";

  const temperature = numeric(data, [
    "environment.external_temperature.value",
    "environment.external_temperature",
  ]);

  const humidity = numeric(data, [
    "environment.relative_humidity.value",
    "environment.relative_humidity",
  ]);

  const currentWind = numeric(data, [
    "environment.wind_speed.value",
    "environment.wind_speed",
  ]);

  const averageWind = numeric(data, [
    "environment.average_wind_speed.value",
  ]);

  const solar = numeric(data, [
    "environment.solar_irradiance.value",
    "environment.solar_irradiance",
  ]);

  $("temperature").textContent = format(temperature, "°C");
  $("humidity").textContent = format(humidity, "%");
  $("currentWind").textContent = format(currentWind, "km/h");
  $("averageWind").textContent = format(averageWind, "km/h");
  $("solar").textContent = format(solar, "W/m²");

  $("windSamples").textContent = averageWind !== null
    ? `Rolling average · ${environment.average_wind_speed.samples ?? "—"} samples`
    : "Backend rolling average";

  $("conditionList").innerHTML = `
    <div class="condition">
      <strong>${format(numeric(data, [
        "environment.atmospheric_pressure.value",
        "environment.atmospheric_pressure",
      ]), "hPa")}</strong>
      <span>Atmospheric pressure</span>
    </div>
    <div class="condition">
      <strong>${format(humidity, "%")}</strong>
      <span>Relative humidity</span>
    </div>
  `;

  $("visibilityList").innerHTML = `
    <div class="condition">
      <strong>${format(numeric(data, [
        "environment.visibility.value",
        "environment.visibility",
      ]), "km")}</strong>
      <span>Visibility</span>
    </div>
    <div class="condition">
      <strong>${format(solar, "W/m²")}</strong>
      <span>Solar irradiance</span>
    </div>
  `;

  const records = history.slice(-MAX_POINTS);

  temperatureChart = updateChart(
    temperatureChart,
    $("temperatureChart"),
    "Temperature",
    records.map((item) => numeric(item.payload, [
      "environment.external_temperature.value",
      "environment.external_temperature",
    ])),
    "#fb7185",
    "°C",
  );

  windChart = updateChart(
    windChart,
    $("windChart"),
    "Wind speed",
    records.map((item) => numeric(item.payload, [
      "environment.wind_speed.value",
      "environment.wind_speed",
    ])),
    "#56b4ff",
    "km/h",
  );
}

function resetWatchdog() {
  $("dataWarning")?.classList.remove("visible");
  clearTimeout(watchdog);
  watchdog = setTimeout(() => {
    $("dataWarning")?.classList.add("visible");
  }, 1000);
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);

  socket.onopen = resetWatchdog;

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "initial") {
      history.splice(0, history.length, ...(message.history || []));
      render(message.latest);
    } else {
      history.push({
        timestamp: message.timestamp,
        payload: message,
      });

      if (history.length > MAX_POINTS) {
        history.splice(0, history.length - MAX_POINTS);
      }

      render(message);
    }

    resetWatchdog();
  };

  socket.onclose = () => {
    $("connectionText").textContent = "Disconnected";
    $("connectionDot").classList.add("offline");
    $("dataWarning")?.classList.add("visible");
    setTimeout(connect, 3000);
  };
}

connect();