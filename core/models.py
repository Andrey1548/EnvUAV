from core.extensions import db
from geoalchemy2 import Geometry

class MonitoringArea(db.Model):
    __tablename__ = "monitoring_areas"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    geom = db.Column(Geometry("POLYGON", srid=4326))


class NoFlyZone(db.Model):
    __tablename__ = "nofly_zones"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    geom = db.Column(Geometry("POLYGON", srid=4326))


class DroneBase(db.Model):
    __tablename__ = "drone_bases"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    geom = db.Column(Geometry("POINT", srid=4326))


class Mission(db.Model):
    __tablename__ = "missions"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    description = db.Column(db.String)
    battery_wh = db.Column(db.Float)
    reserve_pct = db.Column(db.Float)
    speed_kmh = db.Column(db.Float)
    payload_kg = db.Column(db.Float)


class MissionArea(db.Model):
    __tablename__ = "areas"
    id = db.Column(db.Integer, primary_key=True)
    mission_id = db.Column(db.Integer, db.ForeignKey("missions.id", ondelete="CASCADE"))
    geom = db.Column(Geometry("POLYGON", srid=4326))


class MissionNoFly(db.Model):
    __tablename__ = "mission_nofly"
    id = db.Column(db.Integer, primary_key=True)
    mission_id = db.Column(db.Integer, db.ForeignKey("missions.id", ondelete="CASCADE"))
    geom = db.Column(Geometry("POLYGON", srid=4326))
    source = db.Column(db.String, default="user")


class MissionRoute(db.Model):
    __tablename__ = "routes"
    id = db.Column(db.Integer, primary_key=True)
    mission_id = db.Column(db.Integer, db.ForeignKey("missions.id", ondelete="CASCADE"))
    geom = db.Column(Geometry("LINESTRING", srid=4326))
    length_km = db.Column(db.Float)
    energy_wh = db.Column(db.Float)
    created_at = db.Column(db.DateTime, server_default=db.func.now())