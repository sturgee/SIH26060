// filepath: /home/Swapnanil/sih/SIH26060/frontend/static/supplies.js
let watchdog;

const $ = (id) => document.getElementById(id);

function formatDays(value) {
  return Number.isFinite(Number(value))
    ? `${Number(value).toFixed(1)} days`
    : "Unavailable";
}

function setConnection(online) {
  $("connectionDot")?.classList.toggle("offline", !online);
  $("connectionText").textContent = online
    ? "Live connection"
    : "Disconnected";
}

function resetWatchdog() {
  $("dataWarning")?.classList.remove("visible");
  clearTimeout(watchdog);

  watchdog = setTimeout(() => {
    $("dataWarning")?.classList.add("visible");
  }, 1000);
}

function render(data) {
  if (!data) return;

  const forecast = data.supply_forecast || {};

  $("stationLocation").textContent =
    `${data.station?.location?.latitude ?? "—"}°, ` +
    `${data.station?.location?.longitude ?? "—"}°`;

  $("lastUpdate").textContent = data.timestamp
    ? new Date(data.timestamp).toLocaleString()
    : "—";

  const food = forecast.food || {};
  const water = forecast.water || {};
  const fuel = forecast.fuel || {};

  $("foodDays").textContent = formatDays(food.days_remaining);
  $("waterDays").textContent = formatDays(water.days_remaining);
  $("fuelDays").textContent = formatDays(fuel.days_remaining);

  $("foodStatus").textContent = food.source || "—";
  $("waterStatus").textContent = water.source || "—";
  $("fuelStatus").textContent = fuel.source || "—";

  $("supplyDetails").innerHTML = `
    <div>
      <span>Water remaining</span>
      <strong>${water.remaining ?? "—"}</strong>
    </div>
    <div>
      <span>Water daily usage</span>
      <strong>${water.daily_usage ?? "—"}</strong>
    </div>
    <div>
      <span>Fuel remaining</span>
      <strong>${fuel.remaining ?? "—"}</strong>
    </div>
    <div>
      <span>Fuel daily usage</span>
      <strong>${fuel.daily_usage ?? "—"}</strong>
    </div>
  `;
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);

  socket.onopen = () => {
    setConnection(true);
    resetWatchdog();
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "initial") {
      render(message.latest);
    } else {
      render(message);
    }

    resetWatchdog();
  };

  socket.onclose = () => {
    setConnection(false);
    $("dataWarning")?.classList.add("visible");
    setTimeout(connect, 3000);
  };

  socket.onerror = () => socket.close();
}

connect();

const fuelTemperatureForm = $("fuelTemperatureForm");

fuelTemperatureForm?.addEventListener("submit", async (event) => {
  event.preventDefault();

  const temperature = Number(
    $("fuelTemperature").value,
  );

  if (!Number.isFinite(temperature)) {
    $("fuelForecastMessage").textContent =
      "Enter a valid temperature.";
    return;
  }

  $("fuelForecastMessage").textContent = "Calculating...";

  try {
    const response = await fetch("/api/supplies/fuel-forecast", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ temperature }),
    });

    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.detail || "Unable to calculate forecast");
    }

    $("normalFuelDays").textContent =
      formatDays(result.normal_days_remaining);

    $("adjustedFuelDays").textContent =
      formatDays(result.temperature_adjusted_days_remaining);

    $("fuelForecastMessage").textContent =
      `Estimated fuel consumption increases by ` +
      `${result.consumption_increase_percent}% at ` +
      `${result.temperature}°C.`;
  } catch (error) {
    $("fuelForecastMessage").textContent = error.message;
    $("normalFuelDays").textContent = "Unavailable";
    $("adjustedFuelDays").textContent = "Unavailable";
  }
});