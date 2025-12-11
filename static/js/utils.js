const map = L.map("map").setView([49.55, 30.55], 8);
const socket = io();
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

const realNoFlyLayer = L.layerGroup().addTo(map);
realNoFlyLayer.setZIndex(500);
const nfLayer = L.layerGroup().addTo(map);
const gridLayer = L.layerGroup().addTo(map);
const acoLayer = L.layerGroup().addTo(map);
const graphLayer = L.layerGroup().addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
map.addControl(
  new L.Control.Draw({
    draw: { polygon: true, rectangle: true, polyline: false, circle: false, marker: false },
    edit: { featureGroup: drawnItems }
  })
);

async function fetchForestPolygonsSafe(lat, lon) {
  const query = `
  [out:json][timeout:20];
  (
    way(around:2000, ${lat}, ${lon})["landuse"="forest"];
    way(around:2000, ${lat}, ${lon})["natural"="wood"];
    relation(around:2000, ${lat}, ${lon})["landuse"="forest"];
    relation(around:2000, ${lat}, ${lon})["natural"="wood"];
  );
  (._;>;);
  out body;
  `;

  try {
    const resp = await fetch("https://overpass-api.de/api/interpreter", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: query
    });

    const text = await resp.text();
    if (text.trim().startsWith("<")) {
      console.warn("Overpass returned HTML instead of JSON");
      return [];
    }

    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      console.warn("JSON parse error for Overpass", e);
      return [];
    }

    if (!data.elements || !Array.isArray(data.elements)) {
      console.warn("Bad Overpass response format");
      return [];
    }

    const nodes = {};
    data.elements
      .filter(el => el.type === "node")
      .forEach(n => {
        if (n.id && n.lat && n.lon) {
          nodes[n.id] = [n.lat, n.lon];
        }
      });

    const polys = [];

    data.elements
      .filter(el => el.type === "relation")
      .forEach(rel => {
        if (!rel.members) return;
        const outline = [];

        rel.members
          .filter(m => m.role === "outer" && m.type === "way")
          .forEach(m => {
            const way = data.elements.find(w => w.id === m.ref && w.type === "way");
            if (way && way.nodes) {
              way.nodes.forEach(nid => {
                if (nodes[nid]) outline.push(nodes[nid]);
              });
            }
          });

        if (outline.length >= 4) polys.push(outline);
      });

    data.elements
      .filter(el => el.type === "way" && Array.isArray(el.nodes))
      .forEach(way => {
        const poly = [];
        way.nodes.forEach(nid => {
          if (nodes[nid]) poly.push(nodes[nid]);
        });

        if (poly.length >= 4) polys.push(poly);
      });

    return polys;
  } catch (err) {
    console.error("Overpass fatal error:", err);
    return [];
  }
}

const logBox = document.getElementById("log");

function log(msg, color = "#00ff88") {
  if (!logBox) return;
  const line = document.createElement("div");
  line.innerHTML = `<span style="color:${color}">> ${msg}</span>`;
  logBox.appendChild(line);
  logBox.scrollTop = logBox.scrollHeight;
}

let baseMarker = null;
let baseLat = null;
let baseLon = null;
let areaPolygon = null;
let noflyPolys = [];
let realNoFlyPolys = [];

let missionLayer = null;
let debugLayer = null;

function clearMission() {
    if (missionLayer) {
        map.removeLayer(missionLayer);
    }
    missionLayer = L.layerGroup().addTo(map);
}

function clearDebug() {
    if (debugLayer) {
        map.removeLayer(debugLayer);
    }
    debugLayer = L.layerGroup().addTo(map);
}

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
    if (div) div.innerHTML = "Помилка погоди";
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
    realNoFlyPolys = [];

    if (!Array.isArray(zones)) {
      log("Некоректний формат запретних зон із бекенду", "#ffcc00");
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
    log("Помилка завантаження реальних запретних зон", "#ff4444");
  }
}

map.whenReady(loadRealNoFlyZones);

map.on("click", async (e) => {
  const { lat, lng } = e.latlng;

  if (e.originalEvent.shiftKey) {
    log("Пошук лісових ділянок...");

    const polys = await fetchForestPolygonsSafe(lat, lng);

    if (polys.length === 0) {
      log("Лісову ділянку не знайдено");
      return;
    }

    let best = polys[0];
    let bestD = 999999;

    polys.forEach(poly => {
      poly.forEach(([plat, plon]) => {
        const d = Math.hypot(lat - plat, lng - plon);
        if (d < bestD) {
          bestD = d;
          best = poly;
        }
      });
    });

    if (areaPolygon) map.removeLayer(areaPolygon);

    areaPolygon = L.polygon(best.map(([la, lo]) => [la, lo]), {
      color: "green",
      fillColor: "lime",
      fillOpacity: 0.3
    }).addTo(map);

    log(`Ліс знайдено (полігон точок: ${best.length})`);
    return;
  }

  if (baseMarker) map.removeLayer(baseMarker);
  baseMarker = L.marker([lat, lng]).addTo(map);
  baseLat = lat;
  baseLon = lng;
  log(`База встановлена`);
});

map.on(L.Draw.Event.CREATED, (e) => {
  const layer = e.layer;
  const latlngs = layer.getLatLngs();
  if (!latlngs || !latlngs[0]) return;

  const coords = latlngs[0].map(pt => [pt.lat, pt.lng]);

  if (!areaPolygon) {
    layer.setStyle({ color: "green", fillColor: "lime", fillOpacity: 0.2 });
    areaPolygon = layer;
    log("Область моніторингу додана...");
  } else {
    layer.setStyle({ color: "red", fillOpacity: 0.3 });
    noflyPolys.push(coords);
    log("Додано заборонену зону...");
  }

  drawnItems.addLayer(layer);

  if (baseLat && baseLon && areaPolygon) {
    socket.emit("update_nofly", {
      lat: baseLat,
      lon: baseLon,
      nofly: noflyPolys,
      area_poly: getAreaPolygon()
    });
    log("Оновлення заборонених зон на сервері...");
    gridLayer.clearLayers();
    acoLayer.clearLayers();
    graphLayer.clearLayers();
    nfLayer.clearLayers();
  }
});

function getAreaPolygon() {
  if (!areaPolygon) return null;
  const latlngs = areaPolygon.getLatLngs();
  if (!latlngs || !latlngs[0]) return null;
  return latlngs[0].map(pt => [pt.lat, pt.lng]);
}

function readDroneParams() {
  return {
    battery_wh: parseFloat(document.getElementById("battery_wh")?.value || "222"),
    reserve_pct: parseFloat(document.getElementById("reserve_pct")?.value || "20"),
    speed_kmh: parseFloat(document.getElementById("speed")?.value || "40"),
    payload_kg: parseFloat(document.getElementById("payload")?.value || "1.5"),
  };
}

document.getElementById("btnStart").onclick = () => {
  if (!areaPolygon) {
    alert("Намалюйте область моніторингу!");
    return;
  }
  if (baseLat == null || baseLon == null) {
    alert("Вкажіть базу кліком по карті!");
    return;
  }

  gridLayer.clearLayers();
  acoLayer.clearLayers();
  graphLayer.clearLayers();
  nfLayer.clearLayers();
  if (logBox) logBox.innerHTML = "";

  log("Запуск планування...");

  const drone = readDroneParams();
  const cellSize = parseFloat(document.getElementById("cell")?.value || "0.5");
  const ants = parseInt(document.getElementById("ants")?.value || "20", 10);
  const iters = parseInt(document.getElementById("iters")?.value || "10", 10);
  const gridType = String(document.getElementById("grid_type")?.value || "SQUARE").toUpperCase();

  const allNoFlyZones = [...noflyPolys, ...realNoFlyPolys].filter(Array.isArray);

  socket.emit("start_planning", {
    lat: baseLat,
    lon: baseLon,
    area_poly: getAreaPolygon(),
    nofly: allNoFlyZones,
    cell: cellSize,
    ants,
    iters,
    drone,
    grid_type: gridType,
    mission_id: window.currentMissionId || null
  });
};

document.getElementById("btnSave").onclick = async () => {
  if (!baseLat || !baseLon || !areaPolygon) {
    alert("Потрібні база та область моніторингу для збереження місії.");
    return;
  }

  const missionName = prompt("Введіть назву місії:", "Еко-моніторинг");
  if (!missionName) return;

  const drone = readDroneParams();

  const payload = {
    name: missionName,
    description: "Автоматично збережена місія!",
    lat: baseLat,
    lon: baseLon,
    area_poly: getAreaPolygon(),
    nofly: [...noflyPolys, ...realNoFlyPolys],
    drone
  };

  try {
    const resp = await fetch("/missions/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const res = await resp.json();
    if (res.status === "ok") {
      window.currentMissionId = res.mission_id;
      log(`Місію збережено (ID=${res.mission_id})`);
    } else {
      alert("Помилка: " + (res.message || "невідома"));
    }
  } catch (e) {
    console.error(e);
    alert("Помилка запиту при збереженні місії.");
  }
};

document.getElementById("btnLoad").onclick = async () => {
  try {
    const resp = await fetch("/missions/list");
    const missions = await resp.json();

    if (!Array.isArray(missions) || missions.length === 0) {
      alert("Немає збережених місій.");
      return;
    }

    const names = missions.map(m => `${m.id}: ${m.name}`).join("\n");
    const id = prompt("Введіть ID місії для завантаження:\n" + names);
    if (!id) return;

    const res = await fetch(`/missions/${id}`);
    const data = await res.json();

    gridLayer.clearLayers();
    nfLayer.clearLayers();
    acoLayer.clearLayers();
    drawnItems.clearLayers();
    realNoFlyLayer.clearLayers();

    let allPoints = [];

    if (Array.isArray(data.areas) && data.areas.length > 0) {
      data.areas.forEach(poly => {
        if (!Array.isArray(poly)) return;
        const polygon = L.polygon(poly.map(([lat, lon]) => [lat, lon]), {
          color: "green",
          fillColor: "lime",
          fillOpacity: 0.3
        }).addTo(map);
        drawnItems.addLayer(polygon);
        areaPolygon = polygon;
        polygon.getLatLngs()[0].forEach(p => allPoints.push(p));
      });
    } else {
      areaPolygon = null;
    }

    noflyPolys = [];
    if (Array.isArray(data.nofly) && data.nofly.length > 0) {
      data.nofly.forEach(poly => {
        if (!Array.isArray(poly)) return;
        noflyPolys.push(poly);
        const polygon = L.polygon(poly.map(([lat, lon]) => [lat, lon]), {
          color: "red",
          fillOpacity: 0.3
        }).addTo(nfLayer);
        drawnItems.addLayer(polygon);
        polygon.getLatLngs()[0].forEach(p => allPoints.push(p));
      });
    }

    if (Array.isArray(data.routes) && data.routes.length > 0) {
      data.routes.forEach(route => {
        if (!Array.isArray(route)) return;
        const line = L.polyline(route.map(([lat, lon]) => [lat, lon]), {
          color: "blue",
          weight: 3
        }).addTo(acoLayer);
        line.getLatLngs().forEach(p => allPoints.push(p));
      });
    }

    if (allPoints.length > 0) {
      const bounds = L.latLngBounds(allPoints);
      map.fitBounds(bounds, { padding: [50, 50] });
      log("Автоматичне масштабування карти до меж місії");
    }

    log(`Завантажено місію "${data.name}"`);
  } catch (e) {
    console.error(e);
    alert("Помилка завантаження місії.");
  }
};

socket.on("weather_update", (w) => {
  if (!w) return;
  const desc = w.description || "";
  const t = (w.temp != null) ? w.temp : "?";
  const ws = (w.wind_speed != null) ? w.wind_speed : "?";
  log(`Погода: ${desc}, ${t}°C, ${ws} м/с`);
});