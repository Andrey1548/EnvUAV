async function saveMission() {
  if (baseLat == null || baseLon == null || !areaPolygon) {
    alert("Потрібні база та область моніторингу для збереження місії.");
    return;
  }

  const missionName = prompt("Введіть назву місії:", "Еко-моніторинг");
  if (!missionName) return;

  const drone = {
    battery_wh: Number(document.getElementById("battery_wh")?.value || 222),
    reserve_pct: Number(document.getElementById("reserve_pct")?.value || 20),
    speed_kmh: Number(document.getElementById("speed")?.value || 40),
    payload_kg: Number(document.getElementById("payload")?.value || 1.5)
  };

  const payload = {
    name: missionName,
    description: "Автоматично збережена місія!",
    lat: baseLat,
    lon: baseLon,
    area_poly: getAreaPolygon(),
    nofly: [...noflyPolys, ...realNoFlyPolys],
    drone
  };

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
    alert("Помилка: " + res.message);
  }
}


async function loadMission() {
  try {
    const resp = await fetch("/missions/list");
    const missions = await resp.json();

    if (!Array.isArray(missions) || missions.length === 0) {
      alert("Немає збережених місій.");
      return;
    }

    const id = prompt(
      "Введіть ID місії:\n" +
      missions.map(m => `${m.id}: ${m.name}`).join("\n")
    );
    if (!id) return;

    const res = await fetch(`/missions/${id}`);
    const data = await res.json();

    gridLayer.clearLayers();
    nfLayer.clearLayers();
    acoLayer.clearLayers();
    drawnItems.clearLayers();
    realNoFlyLayer.clearLayers();

    let allPoints = [];

    function normalize(poly) {
      if (!poly) return [];
      if (typeof poly[0][0] === "number") return [poly];
      return poly;
    }

    if (Array.isArray(data.areas)) {
      data.areas.forEach(area => {
        normalize(area).forEach(ring => {
          const polygon = L.polygon(
            ring.map(p => [p[0], p[1]]),
            { color: "green", fillColor: "lime", fillOpacity: 0.3 }
          ).addTo(drawnItems);

          allPoints.push(...polygon.getLatLngs()[0]);
        });
      });
    }

    if (Array.isArray(data.nofly)) {
      data.nofly.forEach(zone => {
        normalize(zone).forEach(ring => {
          const polygon = L.polygon(
            ring.map(p => [p[0], p[1]]),
            { color: "red", fillOpacity: 0.3 }
          ).addTo(nfLayer);

          allPoints.push(...polygon.getLatLngs()[0]);
        });
      });
    }

    if (Array.isArray(data.route) && data.route.length > 0) {
      const line = L.polyline(
        data.route.map(pt => [pt[0], pt[1]]),
        { color: "blue", weight: 3 }
      ).addTo(acoLayer);

      allPoints.push(...line.getLatLngs());
    }

    if (allPoints.length > 0) {
      map.fitBounds(L.latLngBounds(allPoints), { padding: [50, 50] });
      log("Автоматичне масштабування карти");
    }

    window.currentMissionId = data.id;
    log(`Завантажено місію "${data.name}"`);
    document.getElementById("exportPanel").style.display = "block";

  } catch (e) {
    console.error(e);
    alert("Помилка завантаження місії.");
  }
}

document.getElementById("btnSave").onclick = saveMission;
document.getElementById("btnLoad").onclick = loadMission;