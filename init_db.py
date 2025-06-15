import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import os


def init_db():
    # Read configuration from environment variables
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    # Ensure all required environment variables are set
    if not all([db_host, db_port, db_name, db_user, db_password]):
        raise ValueError("Missing required environment variables for DB configuration.")

    db_pool = psycopg2.pool.SimpleConnectionPool(
        1,
        10,
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        cursor_factory=RealDictCursor,
    )

    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS hyperparameter_configs (
                    id SERIAL PRIMARY KEY,
                    sweep_id VARCHAR(32) NOT NULL,
                    config JSONB NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS sweep_definitions (
                    sweep_id VARCHAR(32) PRIMARY KEY,
                    original_config JSONB NOT NULL,
                    method VARCHAR(20) NOT NULL
                );
            """)
            conn.commit()
    finally:
        db_pool.putconn(conn)
        print("Database initialized successfully.")


if __name__ == "__main__":
    init_db()
