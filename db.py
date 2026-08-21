import os
import psycopg2
from psycopg2 import Error
from psycopg2.extras import RealDictCursor


def get_db_connection():
    try:
        if os.environ.get("DATABASE_URL"):
            # Cloud (Render + Neon)
            return psycopg2.connect(
                os.environ["DATABASE_URL"],
                connect_timeout=10
            )
        else:
            # Local laptop
            return psycopg2.connect(
                host="localhost",
                database="ecommerce_db",
                user="postgres",
                password="YOUR_LOCAL_PG_PASSWORD",
                port="5432"
            )
    except Error as e:
        print("DB ERROR:", e)
        return None


def close_connection(conn):
    if conn:
        conn.close()


def fetch_one(query, params=None):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        result = cur.fetchone()
        cur.close()
        return result
    except Error as e:
        print("QUERY ERROR:", e)
        return None
    finally:
        close_connection(conn)


def fetch_all(query, params=None):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        results = cur.fetchall()
        cur.close()
        return results
    except Error as e:
        print("QUERY ERROR:", e)
        return []
    finally:
        close_connection(conn)


def execute_query(query, params=None, return_id=False):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        new_id = cur.fetchone()[0] if return_id else None
        conn.commit()
        cur.close()
        return new_id if return_id else True
    except Error as e:
        print("EXECUTE ERROR:", e)
        conn.rollback()
        return None
    finally:
        close_connection(conn)