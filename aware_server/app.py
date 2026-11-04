"""Aware server endpoints.

All HTTP endpoints live in this file. Longer implementations go into their own
modules in this package and are called from here.
"""

import json
import logging
from pathlib import Path

from dotenv import dotenv_values
from flask import Flask, request, send_from_directory

from aware_server.db import DEVICE_COLUMN_KINDS, DEVICE_TABLE, db_config, insert_upload
from aware_server.table_commands import column_kinds

CONFIG_DIR = Path(__file__).resolve().parent.parent / "static"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
CATCH_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
# MySQL errors for a missing table: 1146 is no such table, and a login without a
# grant on the table gets 1142 whether or not the table exists.
MISSING_TABLE_ERRNOS = (1142, 1146)


def create_app() -> Flask:
    """Create the Flask application with all endpoints registered."""
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)
    env = dotenv_values(ENV_FILE)
    config = db_config(env)

    @app.get("/v<int:version>/<label>/")
    def study_config(version: int, label: str):
        """Serve the study config for a config version.

        The label in the participant's magic link is not used yet; it identifies
        the participant once uploads are added.
        """
        app.logger.info(
            "Config request: version=%d label=%s from %s",
            version, label, request.remote_addr,
        )
        response = send_from_directory(
            CONFIG_DIR, f"config_v{version}.json", mimetype="application/json"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/v<int:version>/<label>/<table>/insert")
    def insert(version: int, label: str, table: str):
        """Store uploaded rows.

        Any failure answers 500, which makes the app keep the rows and retry. Only
        the error type and number are logged: database messages can quote row values.
        With DEBUG on, stored uploads are logged too, without their rows, and a
        failed upload's full request is logged.
        """
        try:
            rows = json.loads(request.form["data"])
            insert_upload(config, label, table, request.form["device_id"], rows)
        except Exception as err:
            app.logger.error(
                "Insert failed: version=%d label=%s table=%s error=%s errno=%s",
                version, label, table, type(err).__name__, getattr(err, "errno", None),
            )
            if env.get("DEBUG") == "True":
                app.logger.info("Failed insert request: form=%s", request.form.to_dict())
            # Read by table_commands. These errors only come from the database, so
            # the rows have been parsed by then. The aware_device step marks its
            # errors, and that table's columns are fixed rather than uploaded.
            if getattr(err, "errno", None) in MISSING_TABLE_ERRNOS:
                if getattr(err, "table", None) == DEVICE_TABLE:
                    missing, kinds = DEVICE_TABLE, DEVICE_COLUMN_KINDS
                else:
                    missing, kinds = table, column_kinds(rows)
                app.logger.info(
                    "Missing table: table=%s columns=%s", missing, json.dumps(kinds),
                )
            return "", 500
        if env.get("DEBUG") == "True":
            app.logger.info(
                "Insert stored: version=%d label=%s table=%s rows=%d",
                version, label, table, len(rows),
            )
        return "", 200

    @app.get("/")
    def health():
        """Answer the monitoring probe with an empty 200."""
        return "", 200

    if env.get("DEBUG") == "True":

        @app.route("/", defaults={"path": ""}, methods=CATCH_ALL_METHODS)
        @app.route("/<path:path>", methods=CATCH_ALL_METHODS)
        def catch_all(path: str):
            """Log any other request and answer 404 without storing anything.

            The error makes the app keep the rows and retry, so nothing sent to an
            unhandled route is lost. Development only: the log holds full request
            contents.
            """
            app.logger.info(
                "Unhandled request: %s /%s from %s args=%s form=%s body=%s",
                request.method, path, request.remote_addr, request.args.to_dict(),
                request.form.to_dict(), request.get_data(as_text=True) if not request.form else "",
            )
            return "", 404

    return app
