import psycopg
import os
import sys
from psycopg import OperationalError

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
    except OperationalError as e:
        print("Помилка підключення до PostgreSQL:")
        print(e)
        print("\nПереконайтесь, що сервер PostgreSQL запущений та порт 5433 відкритий.")
        sys.exit(1)

def init_postgis():
    sql_path = os.path.join(os.path.dirname(__file__), "../db/init_postgis.sql")
    if not os.path.exists(sql_path):
        print("Файл init_postgis.sql не знайдено, пропускаю ініціалізацію.")
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