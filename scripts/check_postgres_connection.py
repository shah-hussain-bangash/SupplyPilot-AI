import os
import getpass
import psycopg

password = getpass.getpass("Enter the supplypilot_app password: ")

with psycopg.connect(
    host="127.0.0.1",
    port=int(os.environ["SUPPLYPILOT_DB_PORT"]),
    dbname="supplypilot_dev",
    user="supplypilot_app",
    password=password,
    connect_timeout=10,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT current_database(), current_user,
                   rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
        """)
        print("Connection verified:", cursor.fetchone())
