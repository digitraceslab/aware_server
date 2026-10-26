"""Aware server endpoints.

All HTTP endpoints live in this file. Longer implementations go into their own
modules in this package and are called from here.
"""

from flask import Flask


def create_app() -> Flask:
    """Create the Flask application with all endpoints registered."""
    app = Flask(__name__)
    return app
