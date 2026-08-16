import psycopg2
from psycopg2 import Error
from psycopg2.extras import RealDictCursor

# ============ DATABASE CONFIG ============
DB_CONFIG = {
    "host": "localhost",
    "database": "ecommerce_db",
    "user": "postgres",
    "password": "priyam2008",   # 👈 your pgAdmin password
    "port": "5432"
}


def get_db_connection():
    """Creates and returns a new database connection"""
    try:
        connection = psycopg2.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print("DATABASE CONNECTION ERROR:", e)
        return None


def close_connection(connection):
    """Safely closes a database connection"""
    if connection:
        connection.close()


# ============ HELPER FUNCTIONS ============
# These make our code much shorter in app.py

def fetch_one(query, params=None):
    """Runs a SELECT query and returns ONE row as a dictionary"""
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
    """Runs a SELECT query and returns ALL rows as a list of dictionaries"""
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
    """
    Runs INSERT / UPDATE / DELETE queries.
    If return_id=True, the query must end with 'RETURNING <column>'
    """
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())

        new_id = None
        if return_id:
            new_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        return new_id if return_id else True
    except Error as e:
        print("EXECUTE ERROR:", e)
        conn.rollback()
        return None
    finally:
        close_connection(conn)