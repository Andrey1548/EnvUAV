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
      console.warn("Overpass повернув HTML замість JSON");
      return [];
    }

    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      console.warn("Помилка розбору JSON для Overpass", e);
      return [];
    }

    if (!data.elements || !Array.isArray(data.elements)) {
      console.warn("Неправильний формат відповіді на естакаду");
      return [];
    }

    const nodes = {};
    data.elements
      .filter(el => el.type === "node")
      .forEach(n => {
        if (n.id && typeof n.lat === "number" && typeof n.lon === "number") {
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
            if (way && Array.isArray(way.nodes)) {
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
    console.error("Фатальна помилка overpass:", err);
    return [];
  }
}

map.on("click", async (e) => {
  const { lat, lng } = e.latlng;

  if (e.originalEvent.shiftKey) {
    log("Автоматичне обґрунтування області.\n• Пошук лісів та встановлення області моніторингу...", "#f9fd00ff");

    const polys = await fetchForestPolygonsSafe(lat, lng);
    if (!polys.length) {
      log("Лісову ділянку не знайдено. Спробуйте ще раз!", "#ff4444");
      return;
    }

    let best = polys[0];
    let bestD = Infinity;
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
    drawnItems.addLayer(areaPolygon);

    log(`Ліс знайдено (кількість точок: ${best.length})`);
    help("<b>Готово!</b><br>Тепер встановите базу всередині області ЛІВИМ КЛІКОМ (якщо база не встановлена) та налаштуйте параметри БПЛА та натисніть <b>Старт</b>.");
    return;
  }

  if (baseMarker) map.removeLayer(baseMarker);

  baseMarker = L.marker([lat, lng], {
    draggable: false
  }).addTo(map);

  baseLat = lat;
  baseLon = lng;
  log(`База встановлена: ${lat.toFixed(4)}, ${lng.toFixed(4)}`);
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

  if (baseLat != null && baseLon != null && areaPolygon) {
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