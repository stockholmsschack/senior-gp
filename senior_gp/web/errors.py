"""Stable JSON errors for the API routes, in JGP's envelope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from ..configuration import ConfigurationValidationError, StaleConfigurationError
from ..member_system import MemberSystemUnavailable


def json_error(code: str, message_key: str, status: int, *, details: Mapping[str, Any] | None = None):
    """Return the `{"error": {code, message_key, details}}` envelope with `status`."""
    return jsonify({"error": {"code": code, "message_key": message_key, "details": dict(details or {})}}), status


def register_error_handlers(blueprint: Blueprint) -> None:
    """Answer an HTTP error raised in an API view, a member-system failure, an invalid configuration and a stale revision with a JSON error.

    Other routes, and API paths that match no route, keep Flask's HTML pages.
    """

    @blueprint.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        if request.url_rule is not None and "/api/v1/" in request.url_rule.rule:
            return json_error(f"http_{error.code}", "errors.http", error.code or 500,
                              details={"description": error.description})
        return error

    @blueprint.errorhandler(MemberSystemUnavailable)
    def handle_member_system_error(error: MemberSystemUnavailable):
        current_app.logger.warning("member system: %s", error)
        return json_error("upstream_failure", "errors.member_system.unavailable", 502)

    @blueprint.errorhandler(ConfigurationValidationError)
    def handle_invalid_configuration(error: ConfigurationValidationError):
        return json_error("invalid_configuration", "errors.configuration.invalid", 422,
                          details={"problems": list(error.problems)})

    @blueprint.errorhandler(StaleConfigurationError)
    def handle_stale_configuration(error: StaleConfigurationError):
        return json_error("stale_configuration", "errors.configuration.stale", 409,
                          details={"current_revision": error.current_revision})
