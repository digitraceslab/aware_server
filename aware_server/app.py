"""Aware server endpoints.

All HTTP endpoints live in this file. Longer implementations go into their own
modules in this package and are called from here.
"""

from pathlib import Path

from flask import Flask, send_from_directory

CONFIG_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app() -> Flask:
    """Create the Flask application with all endpoints registered."""
    app = Flask(__name__)

    @app.get("/v<int:version>/<label>/")
    def study_config(version: int, label: str):
        """Serve the study config for a config version.

        The label in the participant's magic link is not used yet; it identifies
        the participant once uploads are added.
        """
        response = send_from_directory(
            CONFIG_DIR, f"config_v{version}.json", mimetype="application/json"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
