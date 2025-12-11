CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS monitoring_areas CASCADE;
DROP TABLE IF EXISTS nofly_zones CASCADE;
DROP TABLE IF EXISTS drone_bases CASCADE;

CREATE TABLE monitoring_areas (
    id SERIAL PRIMARY KEY,
    name TEXT,
    geom GEOMETRY(POLYGON, 4326)
);

CREATE TABLE nofly_zones (
    id SERIAL PRIMARY KEY,
    name TEXT,
    geom GEOMETRY(POLYGON, 4326)
);

CREATE TABLE drone_bases (
    id SERIAL PRIMARY KEY,
    name TEXT,
    geom GEOMETRY(POINT, 4326)
);

CREATE INDEX idx_area_geom ON monitoring_areas USING GIST (geom);
CREATE INDEX idx_nofly_geom ON nofly_zones USING GIST (geom);
CREATE INDEX idx_base_geom ON drone_bases USING GIST (geom);

INSERT INTO monitoring_areas (name, geom)
VALUES (
  'Test Monitoring Area',
  ST_GeomFromText(
    'POLYGON((
      29.8960 50.0610,
      29.8960 50.0710,
      29.9160 50.0710,
      29.9160 50.0610,
      29.8960 50.0610
    ))', 4326)
);

INSERT INTO nofly_zones (name, geom)
VALUES (
  'Test No-Fly Zone',
  ST_GeomFromText(
    'POLYGON((
      29.9025 50.0650,
      29.9025 50.0670,
      29.9075 50.0670,
      29.9075 50.0650,
      29.9025 50.0650
    ))', 4326)
);

INSERT INTO drone_bases (name, geom)
VALUES (
  'Main UAV Base',
  ST_SetSRID(ST_MakePoint(29.9100, 50.0680), 4326)
);

SELECT id, name, ST_Area(geom::geography)/1000000 AS area_km2 FROM monitoring_areas;

SELECT name, ST_AsText(geom) FROM drone_bases;

SELECT name, ST_AsText(geom) FROM nofly_zones;






CREATE TABLE IF NOT EXISTS mission_route (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    geom GEOMETRY(LineString, 4326)
);

CREATE TABLE IF NOT EXISTS missions (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    description TEXT,
    battery_wh FLOAT,
    reserve_pct FLOAT,
    speed_kmh FLOAT,
    payload_kg FLOAT
);

CREATE TABLE IF NOT EXISTS areas (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    geom GEOMETRY(POLYGON, 4326)
);

CREATE TABLE IF NOT EXISTS mission_nofly (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    geom GEOMETRY(POLYGON, 4326),
    source TEXT DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS routes (
    id SERIAL PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
    geom GEOMETRY(LINESTRING, 4326),
    length_km FLOAT,
    energy_wh FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);