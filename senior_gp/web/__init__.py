"""Flask application setup and host registration for Senior GP."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import secrets
from typing import Any

from flask import Flask

from ..chess_results import fetch_tunx
from ..member_system import MemberSystemDiscovery
from ..seasons import utc_now
from .localization import load_catalogues
from .operations import GenerationOperationManager
from .routes import pages


MANIFEST = {"id": "senior", "name": "Senior GP standings", "url_prefix": "/tools/senior"}
REQUIRED_SETTINGS = ("STATE_DIRECTORY", "OUTPUT_DIRECTORY", "FILES_PUBLIC_ORIGIN")


def register(app: Flask, settings: Mapping[str, Any], *, url_prefix: str = MANIFEST["url_prefix"]) -> None:
    """Set up Senior's services and Blueprint in `app`, reading Senior's settings from `settings` only."""
    for key in REQUIRED_SETTINGS:
        if key not in settings:
            raise KeyError(f"Senior needs the {key} setting")
    settings = {
        "DEFAULT_LOCALE": "sv",
        "BASE_TEMPLATE": "senior/senior_shell.jinja2",
        "CLOCK": utc_now,
        "DEVELOPMENT": False,
        **settings,
    }
    rilton_fetch = settings.get("RILTON_FETCH") or fetch_tunx
    app.extensions["senior"] = {
        "settings": settings,
        "catalogues": load_catalogues(),
        "member_system": settings.get("MEMBER_SYSTEM") or MemberSystemDiscovery(),
        "rilton_fetch": rilton_fetch,
        "generation_operations": GenerationOperationManager(
            Path(settings["STATE_DIRECTORY"]),
            Path(settings["OUTPUT_DIRECTORY"]),
            rilton_fetch=rilton_fetch,
            executor=settings.get("GENERATION_EXECUTOR"),
            runner=settings.get("GENERATION_RUNNER"),
            url_prefix=url_prefix,
            publisher=settings.get("MERCURE_PUBLISHER"),
        ),
    }
    app.register_blueprint(pages, url_prefix=url_prefix)


def create_app(configuration: dict[str, Any] | None = None) -> Flask:
    """Create the standalone Flask application.

    `configuration` overrides the defaults, such as the `state/` and `output/`
    directories in the working directory.
    """
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        STATE_DIRECTORY=Path("state"),
        OUTPUT_DIRECTORY=Path("output"),
        SECRET_KEY=secrets.token_hex(32),
        FILES_PUBLIC_ORIGIN=os.getenv(
            "SENIOR_FILES_PUBLIC_ORIGIN",
            "http://senior.localhost:5000",
        ),
    )
    if configuration:
        app.config.update(configuration)
    register(app, app.config, url_prefix="")
    return app


__all__ = ["MANIFEST", "create_app", "register"]
