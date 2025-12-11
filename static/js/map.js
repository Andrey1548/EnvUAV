window.map = L.map("map").setView([49.55, 30.55], 8);
window.socket = io();

const apiKey = "d265b3207144c2a738c18e5ed39952d6";

const baseMap = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);

const tempLayer = L.tileLayer(
  `https://tile.openweathermap.org/map/temp_new/{z}/{x}/{y}.png?appid=${apiKey}`,
  { opacity: 0.5 }
).addTo(map);

const windLayer = L.tileLayer(
  `https://tile.openweathermap.org/map/wind_new/{z}/{x}/{y}.png?appid=${apiKey}`,
  { opacity: 0.7 }
);

const cloudsLayer = L.tileLayer(
  `https://tile.openweathermap.org/map/clouds_new/{z}/{x}/{y}.png?appid=${apiKey}`,
  { opacity: 0.4 }
);

const precipLayer = L.tileLayer(
  `https://tile.openweathermap.org/map/precipitation_new/{z}/{x}/{y}.png?appid=${apiKey}`,
  { opacity: 0.5 }
);

L.control.layers(
  { "OpenStreetMap": baseMap },
  {
    "Температура": tempLayer,
    "Вітер": windLayer,
    "Хмари": cloudsLayer,
    "Опади": precipLayer
  },
  { collapsed: true }
).addTo(map);

window.logBox = document.getElementById("log") || null;

window.log = function (msg, color = "#00ff88") {
  if (!window.logBox) return;
  const line = document.createElement("div");
  line.innerHTML = `<span style="color:${color}">> ${msg}</span>`;
  window.logBox.appendChild(line);
  window.logBox.scrollTop = window.logBox.scrollHeight;
};

window.realNoFlyLayer = L.layerGroup().addTo(map);
realNoFlyLayer.setZIndex(500);

window.nfLayer   = L.layerGroup().addTo(map);
window.gridLayer = L.layerGroup().addTo(map);
window.acoLayer  = L.layerGroup().addTo(map);
window.graphLayer= L.layerGroup().addTo(map);

window.drawnItems = new L.FeatureGroup().addTo(map);
map.addControl(
  new L.Control.Draw({
    draw: { polygon: true, rectangle: true, polyline: false, circle: false, marker: false },
    edit: { featureGroup: drawnItems }
  })
);

window.baseMarker = null;
window.baseLat = null;
window.baseLon = null;

window.areaPolygon = null;
window.noflyPolys = window.noflyPolys || [];
window.realNoFlyPolys = window.realNoFlyPolys || [];

window.currentMissionId = null;

window.getAreaPolygon = function () {
  if (!areaPolygon) return null;
  const latlngs = areaPolygon.getLatLngs();
  if (!latlngs || !latlngs[0]) return null;
  return latlngs[0].map(pt => [pt.lat, pt.lng]);
};

function addCenterWeatherLabel() {
  const label = L.control({ position: "bottomleft" });
  label.onAdd = function () {
    const div = L.DomUtil.create("div", "weather-label");
    div.style.background = "rgba(255,255,255,0.9)";
    div.style.padding = "6px 10px";
    div.style.borderRadius = "8px";
    div.style.font = "14px Segoe UI, sans-serif";
    div.style.boxShadow = "0 0 5px rgba(0,0,0,0.3)";
    div.innerHTML = "🌦 Завантаження погоди...";
    return div;
  };
  label.addTo(map);
}
addCenterWeatherLabel();

async function updateWeather() {
  const center = map.getCenter();
  try {
    const resp = await fetch(
      `https://api.openweathermap.org/data/2.5/weather?lat=${center.lat}&lon=${center.lng}&units=metric&appid=${apiKey}&lang=ua`
    );
    const w = await resp.json();
    const div = document.querySelector(".weather-label");
    if (w && w.main && div) {
      div.innerHTML = `
        <b>Дані про погоду:</b><br>
        Місто: <b>${w.name || "Невідомо"}</b><br>
        Температура: ${w.main.temp.toFixed(1)}°C<br>
        Вітер: ${w.wind.speed.toFixed(1)} м/с (${w.wind.deg || 0}°)<br>
        Хмарність: ${w.weather[0].description}
      `;
    }
  } catch (e) {
    const div = document.querySelector(".weather-label");
    if (div) div.innerHTML = "Помилка погоди... Перезавантажте сторінку...";
  }
}

let weatherTimer = null;
map.on("moveend", () => {
  clearTimeout(weatherTimer);
  weatherTimer = setTimeout(updateWeather, 800);
});
updateWeather();

async function loadRealNoFlyZones() {
  try {
    const b = map.getBounds();
    const url = `/nofly/real?min_lat=${b.getSouth()}&max_lat=${b.getNorth()}&min_lon=${b.getWest()}&max_lon=${b.getEast()}`;
    const resp = await fetch(url);
    const zones = await resp.json();

    realNoFlyLayer.clearLayers();
    window.realNoFlyPolys = [];

    if (!Array.isArray(zones)) {
      log("Некоректний формат no-fly зон із бекенду", "#ffcc00");
      return;
    }

    zones.forEach(poly => {
      if (!Array.isArray(poly)) return;
      realNoFlyPolys.push(poly);
      L.polygon(poly.map(([lat, lon]) => [lat, lon]), {
        color: "red",
        weight: 1,
        fillColor: "red",
        fillOpacity: 0.25
      }).addTo(realNoFlyLayer);
    });

    log(`Завантажено ${zones.length} реальних заборонених зон...`);
  } catch (e) {
    console.error(e);
    log("Помилка завантаження реальних no-fly зон", "#ff4444");
  }
}

window.exportRoute = async function(fmt) {
    const mid = window.currentMissionId;
    if (!mid) {
        alert("Спочатку збережіть місію!");
        return;
    }

    const url = `/missions/${mid}/export?fmt=${fmt}`;

    try {
        const res = await fetch(url);
        if (!res.ok) {
            const j = await res.json().catch(() => ({}));
            alert("Помилка експорту: " + (j.error || res.statusText));
            return;
        }

        let filename = `mission_${mid}.${fmt === "qgc" ? "plan" : fmt}`;
        let content = await res.text();

        let mime =
            fmt === "dji" || fmt === "qgc" || fmt === "geojson"
                ? "application/json"
                : fmt === "csv"
                ? "text/csv"
                : fmt === "kml"
                ? "application/vnd.google-earth.kml+xml"
                : "text/plain";

        const blob = new Blob([content], { type: mime });

        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);

    } catch (err) {
        alert("Помилка завантаження: " + err);
    }
}

map.whenReady(loadRealNoFlyZones);