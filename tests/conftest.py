"""Shared pytest fixtures for the aware server tests."""

import pytest

from aware_server.app import create_app


@pytest.fixture
def client():
    """A Flask test client for a freshly created app."""
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
