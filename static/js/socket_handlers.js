function readDroneParams() {
  return {
    battery_wh: parseFloat(document.getElementById("battery_wh")?.value || "222"),
    reserve_pct: parseFloat(document.getElementById("reserve_pct")?.value || "20"),
    speed_kmh: parseFloat(document.getElementById("speed")?.value || "40"),
    payload_kg: parseFloat(document.getElementById("payload")?.value || "1.5")
  };
}

function help(text) {
  const panel = document.getElementById("helpPanel");
  if (!panel) return;
  panel.innerHTML = text;
}

document.getElementById("btnStart").onclick = () => {
  if (!areaPolygon) {
    alert("Області моніторингу не знайдено! Намалюйте спочатку потрібну область моніторингу!");
    return;
  }
  if (baseLat == null || baseLon == null) {
    alert("Бази вильоту не знайдено! Вкажіть базу кліком по карті!");
    return;
  }

  document.getElementById("exportPanel").style.display = "none";

  gridLayer.clearLayers();
  acoLayer.clearLayers();
  graphLayer.clearLayers();
  nfLayer.clearLayers();
  
  if (window.logBox) window.logBox.innerHTML = "";

  log("Запуск планування... Розпочато дискретизацію області...", "#ff00ffff");

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

let iterLine = null;
let finalLine = null;
let antMarker = null;
let antAnimId = null;
let antPath = [];
let antT = 0;

function lerpLatLng(p1, p2, t) {
  const lat = p1.lat + (p2.lat - p1.lat) * t;
  const lng = p1.lng + (p2.lng - p1.lng) * t;
  return L.latLng(lat, lng);
}

function startAntOnPath(latlngs) {
  if (!Array.isArray(latlngs) || latlngs.length < 2) return;

  antPath = latlngs.map(p => L.latLng(p[0], p[1]));
  antT = 0;

  if (!antMarker) {
    antMarker = L.circleMarker(antPath[0], {
      radius: 5,
      color: "orange",
      fillColor: "yellow",
      fillOpacity: 1
    }).addTo(acoLayer);
  } else {
    antMarker.setLatLng(antPath[0]);
    if (!acoLayer.hasLayer(antMarker)) {
      antMarker.addTo(acoLayer);
    }
  }

  if (antAnimId) cancelAnimationFrame(antAnimId);
  antAnimId = requestAnimationFrame(stepAnt);
}

function stepAnt() {
  if (antPath.length < 2) return;

  antT += 0.03;

  if (antT >= antPath.length - 1) {
    antT = 0;
  }

  const idx = Math.floor(antT);
  const t = antT - idx;
  const p1 = antPath[idx];
  const p2 = antPath[idx + 1];

  const pos = lerpLatLng(p1, p2, t);
  antMarker.setLatLng(pos);

  antAnimId = requestAnimationFrame(stepAnt);
}

socket.on("weather_update", (w) => {
  if (!w) return;
  const desc = w.description || "";
  const t = (w.temp != null) ? w.temp : "?";
  const ws = (w.wind_speed != null) ? w.wind_speed : "?";
  log(`Погода: ${desc}, ${t}°C, ${ws} м/с`);
});

socket.on("planner_update", (d) => {
  if (!d || !d.event) return;

  if (d.event === "nofly_update") {
    log(
      `Оновлено заборонені зони: ${d.nofly_count || 0}. Розпочато перепланування маршруту...`,
      "#ffd27f"
    );
    gridLayer.clearLayers();
    graphLayer.clearLayers();
    acoLayer.clearLayers();
    nfLayer.clearLayers();
    return;
  }

  if (d.event === "grid") {
    gridLayer.clearLayers();
    graphLayer.clearLayers();

    const cells = Array.isArray(d.cells) ? d.cells : [];

    cells.forEach((c) => {
      if (Array.isArray(c.bbox) && c.bbox.length === 4) {
        const bb = c.bbox;
        L.rectangle(
          [
            [bb[0], bb[1]],
            [bb[2], bb[3]],
          ],
          {
            color: "#999",
            weight: 1,
            fill: false,
          }
        ).addTo(gridLayer);
      }

      if (Array.isArray(c.path) && c.path.length > 1) {
        const pl = c.path
          .filter((p) => Array.isArray(p) && p.length === 2)
          .map((p) => [p[0], p[1]]);
        if (pl.length > 1) {
          L.polyline(pl, { color: "#666", weight: 1 }).addTo(gridLayer);
        }
      }

      if (Array.isArray(c.center) && c.center.length === 2) {
        L.circleMarker([c.center[0], c.center[1]], {
          radius: 3,
          color: "black",
          fillColor: "yellow",
          fillOpacity: 1,
        }).addTo(gridLayer);
      }
    });

    if (Array.isArray(d.graph_edges) && d.graph_edges.length > 0) {
      d.graph_edges.forEach((e) => {
        if (e && Array.isArray(e.from) && Array.isArray(e.to)) {
          L.polyline(
            [
              [e.from[0], e.from[1]],
              [e.to[0], e.to[1]],
            ],
            {
              color: "purple",
              weight: 1.2,
              opacity: 0.6,
              dashArray: "4,3",
            }
          ).addTo(graphLayer);
        }
      });
    }

    const areaStr =
      typeof d.area_km2 === "number" ? d.area_km2.toFixed(2) + " км²" : "—";
    const cellStr =
      typeof d.cell_km === "number" ? d.cell_km + " км" : "невідомо";
    const gridType = d.grid_type || "SQUARE";

    log(
      "Дискретизація області завершена:\n" +
        `— Площа області: ${areaStr}\n` +
        `— Тип сітки: ${gridType}\n` +
        `— Розмір клітини: ${cellStr}\n` +
        `— Кількість клітин: ${cells.length}\n` +
        `— Ребер у графі суміжності: ${
          (d.graph_edges && d.graph_edges.length) || 0
        }`,
      "#7fffd4"
    );
    return;
  }

  if (d.event === "aco_iter") {
    const bt = Array.isArray(d.best_tour) ? d.best_tour : null;

    if (bt && bt.length > 1 && Array.isArray(bt[0])) {
      const latlngs = bt.map((p) => [p[0], p[1]]);

      if (!iterLine) {
        iterLine = L.polyline(latlngs, {
          color: "#00c2ff",
          weight: 3,
          opacity: 0.85,
        }).addTo(acoLayer);
      } else {
        iterLine.setLatLngs(latlngs);
      }

      startAntOnPath(latlngs);
    }

    const it = d.iteration ?? "?";
    const sc =
      typeof d.best_score === "number"
        ? d.best_score.toFixed(3)
        : "невідомо";
    const en =
      typeof d.best_cost === "number"
        ? d.best_cost.toFixed(1) + " Wh"
        : "невідомо";

    log(
      `Ітерація ${it} алгоритму ACO:\n` +
        `   • Найкраще охоплення (сума ваг клітин): ${sc}\n` +
        `   • Оцінка енерговитрат маршруту: ${en}`,
      "#ffde7d"
    );

    return;
  }

  if (d.event === "aco_error") {
    log(`Помилка ACO: ${d.message || "невідома"}`, "#ff4444");
    return;
  }

  if (d.event === "aco_done") {
    const sc =
      typeof d.best_score === "number"
        ? d.best_score.toFixed(3)
        : "невідомо";
    const en =
      typeof d.best_cost === "number"
        ? d.best_cost.toFixed(1) + " Wh"
        : "невідомо";

    log(
      "Оптимізацію маршрутів завершено:\n" +
        `— Найкраще досягнуте охоплення: ${sc}\n` +
        `— Оцінка енерговитрат: ${en}`,
      "#9aff9a"
    );
    return;
  }

  if (d.event === "mission_error") {
    log(`Помилка при формуванні маршруту: ${d.message || "невідома"}`, "#ff4444");
    return;
  }

  if (d.event === "done") {
    document.getElementById("exportPanel").style.display = "block";

    if (antAnimId) cancelAnimationFrame(antAnimId);
    antAnimId = null;

    acoLayer.clearLayers();

    const raw = Array.isArray(d.route) ? d.route : [];

    if (raw.length < 2) {
      log("Маршрут порожній або занадто короткий!", "#ff7777");
      return;
    }

    const STEP = 15;
    const cleaned = raw
      .filter((_, idx) => idx === 0 || idx === raw.length - 1 || idx % STEP === 0)
      .map((p) => [p[0], p[1]]);

    if (cleaned.length > 1) {
      finalLine = L.polyline(cleaned, {
        color: "blue",
        weight: 4,
        opacity: 0.95,
      }).addTo(acoLayer);

      startAntOnPath(cleaned);

      const bounds = L.latLngBounds(cleaned.map((p) => L.latLng(p[0], p[1])));
      map.fitBounds(bounds, { padding: [40, 40] });
    }

    const lenStr =
      typeof d.mission_len_km === "number"
        ? d.mission_len_km.toFixed(3) + " км"
        : "невідомо";

    log(
      "Місію сплановано та візуалізовано:\n" +
        `— Довжина логічного маршруту: ${lenStr}\n` +
        "— Маршрут готовий до експорту у формати DJI / QGroundControl.",
      "#44e3ff"
    );
    help("<b>Маршрут знайдено, місію виконано!</b><br>Тепер ви можете експортувати дану місію в панелі <b>Експорт маршруту</b>.");
    return;
  }
});