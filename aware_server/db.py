"""MySQL storage for uploaded rows.

The login is INSERT only, so the tables must already exist and nothing here can
read them back. Rows go to `<table>_https`, keeping them apart from the tables
of the same name that the app writes to directly.
"""

import re

import mysql.connector

TABLE_SUFFIX = "_https"
LABEL_TABLE = "device_label_https"
IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")


def db_config(env: dict) -> dict:
    """Build the connection arguments from the settings in .env."""
    return {
        "host": env.get("MYSQL_HOST"),
        "port": int(env.get("MYSQL_PORT") or 3306),
        "database": env.get("MYSQL_DATABASE"),
        "user": env.get("MYSQL_USER"),
        "password": env.get("MYSQL_PASSWORD"),
    }


def quote_identifier(name: str) -> str:
    """Quote a client-supplied table or column name, which cannot be a SQL parameter."""
    if not IDENTIFIER.fullmatch(name):
        raise ValueError("Invalid identifier")
    return f"`{name}`"


def group_by_columns(rows: list) -> dict:
    """Group rows that have the same columns, so each group is one insert statement."""
    if not isinstance(rows, list):
        raise ValueError("Rows must be a list")
    groups = {}
    for row in rows:
        if not isinstance(row, dict) or not row:
            raise ValueError("Each row must be a non-empty object")
        columns = tuple(sorted(row))
        groups.setdefault(columns, []).append(tuple(row[c] for c in columns))
    return groups


def insert_upload(config: dict, label: str, table: str, device_id: str, rows: list) -> None:
    """Store a batch of rows and the device's label in one transaction.

    Raises on any failure, in which case nothing is stored.
    """
    target = quote_identifier(table + TABLE_SUFFIX)
    groups = group_by_columns(rows)

    conn = mysql.connector.connect(**config)
    try:
        cursor = conn.cursor()
        # The primary key makes this a no-op for a label already stored.
        cursor.execute(
            f"INSERT IGNORE INTO `{LABEL_TABLE}` (device_id, label) VALUES (%s, %s)",
            (device_id, label),
        )
        for columns, values in groups.items():
            column_list = ", ".join(quote_identifier(c) for c in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            cursor.executemany(
                f"INSERT INTO {target} ({column_list}) VALUES ({placeholders})",
                values,
            )
        conn.commit()
    finally:
        conn.close()
