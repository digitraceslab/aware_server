"""Generate CREATE TABLE commands from the server log.

When an upload hits a table that does not exist, the server logs the column names
and kinds it tried to write, never the values. Pipe the log through this module to
print commands for review:

    journalctl -u aware-gunicorn --no-pager | venv/bin/python -m aware_server.table_commands

Kinds are guessed from the values seen so far, and the app sends most numbers as
strings, so a text column holding only numbers looks numeric.
"""

import json
import re
import sys

from aware_server.db import LABEL_TABLE, TABLE_SUFFIX, quote_identifier

LOG_LINE = re.compile(r"Missing table: table=(\S+) columns=(\{.*\})")
INT_TEXT = re.compile(r"-?(0|[1-9]\d*)")
FLOAT_TEXT = re.compile(r"-?(0|[1-9]\d*)\.\d+([eE][+-]?\d+)?")
# Ordered from narrowest to widest: a column takes the widest kind seen in it.
KIND_TYPES = {"int": "BIGINT", "float": "DOUBLE", "text": "TEXT"}
KINDS = list(KIND_TYPES)
# Columns with a fixed definition, which the migrations rely on.
FIXED_COLUMNS = {"_id", "timestamp", "device_id"}


def value_kind(value) -> str | None:
    """Return the kind of a value, or None if it says nothing about the column."""
    if value is None or value == "":
        return None
    if isinstance(value, (bool, int)):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str) and INT_TEXT.fullmatch(value):
        return "int"
    if isinstance(value, str) and FLOAT_TEXT.fullmatch(value):
        return "float"
    return "text"


def wider_kind(first: str | None, second: str | None) -> str | None:
    """Return the kind that can hold both kinds."""
    if first is None or second is None:
        return first or second
    return max(first, second, key=KINDS.index)


def column_kinds(rows: list) -> dict:
    """Return each column's kind over the rows. A column with no values has kind None."""
    kinds = {}
    for row in rows:
        for column, value in row.items():
            kinds[column] = wider_kind(kinds.get(column), value_kind(value))
    return kinds


def read_log(lines) -> dict:
    """Collect the tables and merged column kinds from log lines."""
    tables = {}
    for line in lines:
        match = LOG_LINE.search(line)
        if not match:
            continue
        columns = tables.setdefault(match.group(1), {})
        for column, kind in json.loads(match.group(2)).items():
            columns[column] = wider_kind(columns.get(column), kind)
    return tables


def create_table_command(table: str, columns: dict) -> str:
    """Build the CREATE TABLE command for an uploaded table.

    Raises ValueError for a table or column name that is not a plain identifier.
    """
    definitions = [
        "`_id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY",
        "`timestamp` DOUBLE NOT NULL",
        "`device_id` VARCHAR(255) NOT NULL",
    ]
    for column in sorted(set(columns) - FIXED_COLUMNS):
        # A column with no values yet could hold anything.
        column_type = KIND_TYPES[columns[column] or "text"]
        definitions.append(f"{quote_identifier(column)} {column_type}")
    definitions.append("INDEX `device_timestamp` (`device_id`, `timestamp`)")
    body = ",\n    ".join(definitions)
    target = quote_identifier(table + TABLE_SUFFIX)
    return f"CREATE TABLE IF NOT EXISTS {target} (\n    {body}\n);"


def label_table_command() -> str:
    """Build the CREATE TABLE command for the device label table."""
    return (
        f"CREATE TABLE IF NOT EXISTS `{LABEL_TABLE}` (\n"
        "    `device_id` VARCHAR(255) NOT NULL,\n"
        "    `label` VARCHAR(255) NOT NULL,\n"
        "    PRIMARY KEY (`device_id`, `label`)\n"
        ");"
    )


def main() -> None:
    """Print the commands for the tables named in the log on standard input."""
    print(label_table_command())
    for table, columns in sorted(read_log(sys.stdin).items()):
        try:
            print(f"\n{create_table_command(table, columns)}")
        except ValueError:
            # The endpoint is public, so the log can hold names sent by anyone.
            print(f"Skipped {table}: invalid table or column name", file=sys.stderr)


if __name__ == "__main__":
    main()
