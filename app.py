import os
import sys
import psycopg
from flask import Flask, render_template
from core.extensions import db, socketio
from routes.mission_routes import mission_bp
from routes.forest_routes import forest_bp
from core.export import export_bp

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql+psycopg://postgres:12345@localhost:5433/uav_db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.register_blueprint(export_bp)
db.init_app(app)
socketio.init_app(app, cors_allowed_origins="*")

app.register_blueprint(forest_bp)

def check_db_connection():
    try:
        print("Перевірка з’єднання з PostgreSQL...")
        conn = psycopg.connect(
            dbname="uav_db",
            user="postgres",
            password="12345",
            host="localhost",
            port=5433,
            connect_timeout=5
        )
        conn.close()
        print("Підключення до бази даних успішне!")
        return True
    except psycopg.OperationalError as e:
        print("Помилка підключення до PostgreSQL:")
        print(e)
        sys.exit(1)

def init_postgis():
    sql_path = os.path.join(os.path.dirname(__file__), "db/init_postgis.sql")
    if not os.path.exists(sql_path):
        print("Файл init_postgis.sql не знайдено — пропускаю ініціалізацію.")
        return

    try:
        with open(sql_path, "r", encoding="utf-8") as f:
            sql_script = f.read()

        print("Виконую ініціалізацію бази даних PostGIS...")
        with psycopg.connect(
            dbname="uav_db",
            user="postgres",
            password="12345",
            host="localhost",
            port=5433
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(sql_script)
            conn.commit()

        print("PostGIS, таблиці та тестові дані успішно створені.")
    except Exception as e:
        print(f"Помилка під час ініціалізації PostGIS: {e}")

app.register_blueprint(mission_bp)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    check_db_connection()
    init_postgis()

    print("Сервер запущено: http://127.0.0.1:5000")
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)