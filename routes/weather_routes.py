from flask import jsonify, request
from app import app
from core.utils import get_weather
import numpy as np

@app.route("/get_weather")
def get_weather_endpoint():
    lat = float(request.args.get("lat", 50.45))
    lon = float(request.args.get("lon", 30.52))
    w = get_weather(lat, lon)
    if not w:
        return jsonify({"error": "Не вдалося отримати погоду"}), 500
    return jsonify(w)

@app.route("/weather/grid")
def weather_grid():
    min_lat = float(request.args.get("min_lat", 49.0))
    max_lat = float(request.args.get("max_lat", 50.0))
    min_lon = float(request.args.get("min_lon", 29.0))
    max_lon = float(request.args.get("max_lon", 31.0))
    step = float(request.args.get("step", 0.05))
    points = []
    for lat in np.arange(min_lat, max_lat, step):
        for lon in np.arange(min_lon, max_lon, step):
            w = get_weather(lat, lon)
            if w:
                points.append({
                    "lat": lat, "lon": lon,
                    "temp": w["temp"],
                    "wind_speed": w["wind_speed"],
                    "wind_deg": w["wind_deg"],
                    "desc": w["description"]
                })
    return jsonify(points)