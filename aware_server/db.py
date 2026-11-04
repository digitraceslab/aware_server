"""MySQL storage for uploaded rows.

The login can INSERT into the data tables and also SELECT from aware_device;
the tables must already exist. Rows go to the table named in the upload, the
same tables the app writes to directly. Every upload also makes sure aware_device
maps the device_id to its label, which is how devices are matched to participants.
"""

import re
import time

import mysql.connector

DEVICE_TABLE = "aware_device"
# The aware_device columns describing the hardware, copied from another device
# with the same label. Quoted because `release` is a MySQL keyword.
DEVICE_FACT_COLUMNS = (
    "board", "brand", "device", "build_id", "hardware", "manufacturer",
    "model", "product", "serial", "release", "release_type", "sdk",
)
# Column kinds of aware_device, logged in place of the upload's columns when
# aware_device is the missing table. All are needed: the copy reads every fact.
DEVICE_COLUMN_KINDS = {
    "timestamp": "float", "device_id": "text", "label": "text",
    **{column: "text" for column in DEVICE_FACT_COLUMNS},
}
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


def ensure_device_label(cursor, device_id: str, label: str) -> None:
    """Add an aware_device row for a device_id and label pair not stored yet.

    The new row copies the hardware columns of the latest row with the same
    label, or holds only the device_id and label when the label is new.
    """
    cursor.execute(
        f"SELECT 1 FROM `{DEVICE_TABLE}` WHERE device_id = %s AND label = %s LIMIT 1",
        (device_id, label),
    )
    if cursor.fetchone():
        return
    now = time.time() * 1000
    facts = ", ".join(quote_identifier(c) for c in DEVICE_FACT_COLUMNS)
    cursor.execute(
        f"INSERT INTO `{DEVICE_TABLE}` (`timestamp`, device_id, label, {facts}) "
        f"SELECT %s, %s, label, {facts} FROM `{DEVICE_TABLE}` "
        "WHERE label = %s ORDER BY _id DESC LIMIT 1",
        (now, device_id, label),
    )
    if cursor.rowcount == 0:
        cursor.execute(
            f"INSERT INTO `{DEVICE_TABLE}` (`timestamp`, device_id, label) VALUES (%s, %s, %s)",
            (now, device_id, label),
        )


def insert_upload(config: dict, label: str, table: str, device_id: str, rows: list) -> None:
    """Store a batch of rows and the device's label in one transaction.

    Raises on any failure, in which case nothing is stored. A database error from
    the aware_device step carries `table` set to aware_device, so the caller can
    tell which table failed.
    """
    target = quote_identifier(table)
    groups = group_by_columns(rows)

    conn = mysql.connector.connect(**config)
    try:
        cursor = conn.cursor()
        try:
            ensure_device_label(cursor, device_id, label)
        except mysql.connector.Error as err:
            err.table = DEVICE_TABLE
            raise
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
