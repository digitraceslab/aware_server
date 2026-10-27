"""Aware server endpoints.

All HTTP endpoints live in this file. Longer implementations go into their own
modules in this package and are called from here.
"""

import logging
from pathlib import Path

from dotenv import dotenv_values
from flask import Flask, request, send_from_directory

CONFIG_DIR = Path(__file__).resolve().parent.parent / "static"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
CATCH_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def create_app() -> Flask:
    """Create the Flask application with all endpoints registered."""
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)

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

    @app.get("/")
    def health():
        """Answer the monitoring probe with an empty 200."""
        return "", 200

    if dotenv_values(ENV_FILE).get("DEBUG") == "True":

        @app.route("/", defaults={"path": ""}, methods=CATCH_ALL_METHODS)
        @app.route("/<path:path>", methods=CATCH_ALL_METHODS)
        def catch_all(path: str):
            """Log any other request and answer 200 without storing anything.

            Development only: the log holds full request contents.
            """
            app.logger.info(
                "Unhandled request: %s /%s from %s args=%s form=%s body=%s",
                request.method, path, request.remote_addr, request.args.to_dict(),
                request.form.to_dict(), request.get_data(as_text=True) if not request.form else "",
            )
            return "", 200

    return app
