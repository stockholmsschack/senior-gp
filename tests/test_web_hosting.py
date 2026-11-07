"""Senior registered into a host's own Flask application, under the manifest's prefix."""

import re

from flask import Blueprint, Flask, abort, request
import pytest

from senior_gp.configuration import save_configuration
from senior_gp.web import MANIFEST, register
from senior_gp.web.routes import _actor

from tests.test_web_shell import CLOCK, CONFIGURATION

PREFIX = MANIFEST["url_prefix"]
HOST_SHELL = """<html lang="{{ locale }}"><head><title>{% block title %}{% endblock %}</title>
{% block head %}<link href="/host/bootstrap.css" rel="stylesheet">{% endblock %}</head>
<body><nav>Host navbar</nav>{% block content %}{% endblock %}
{% block scripts %}<script src="/host/bootstrap.bundle.js"></script>{% endblock %}</body></html>"""
HOST_USER = "X-Host-User"
ADMINISTRATOR = "admin@example.com"


def _host(tmp_path, **settings):
    """A host that lets only its administrator reach the mount, as Verktyg's guard does.

    Its own `pages` Blueprint makes registration fail if Senior's endpoints leave the `senior` namespace.
    """
    state_directory = tmp_path / "state"
    save_configuration(state_directory, CONFIGURATION)
    (tmp_path / "host_shell.jinja2").write_text(HOST_SHELL)
    host = Flask("host", template_folder=tmp_path)
    host.config["SECRET_KEY"] = "host"
    host.register_blueprint(Blueprint("pages", "host"))

    @host.before_request
    def guard_the_mount():
        if request.path == PREFIX or request.path.startswith(f"{PREFIX}/"):
            user = request.headers.get(HOST_USER)
            if user is None:
                abort(401)
            if user != ADMINISTRATOR:
                abort(403)

    register(host, {
        "STATE_DIRECTORY": state_directory,
        "OUTPUT_DIRECTORY": tmp_path / "output",
        "FILES_PUBLIC_ORIGIN": "/files/senior",
        "CLOCK": CLOCK,
        **settings,
    })
    return host


def _signed_in(host, user=ADMINISTRATOR):
    client = host.test_client()
    client.environ_base[f"HTTP_{HOST_USER.upper().replace('-', '_')}"] = user
    return client


@pytest.mark.parametrize("shell", [None, "host_shell.jinja2"])
@pytest.mark.parametrize("lang, title", [("sv", "Senior GP-ställning"), ("en", "Senior GP standings")])
def test_the_overview_renders_under_the_prefix_in_the_host_locale(tmp_path, shell, lang, title):
    host = _host(tmp_path, LOCALE=lambda: lang, **({"BASE_TEMPLATE": shell} if shell else {}))
    client = _signed_in(host)

    # The host's locale overrides the `lang` query.
    response = client.get(f"{PREFIX}/?lang={'en' if lang == 'sv' else 'sv'}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'<html lang="{lang}">' in body
    assert "<h1>Senior GP 2025</h1>" in body
    assert ("Host navbar" in body) == bool(shell)
    assert f"<title>Senior GP 2025 · {title}</title>" in body
    if shell:
        assert '<link href="/host/bootstrap.css"' in body
        assert body.index('href="/host/bootstrap.css"') < body.index("/static/css/app.css")
        assert '<script src="/host/bootstrap.bundle.js"></script>' in body
    else:
        assert f'href="{PREFIX}/?lang={lang}"' in body
    assets = re.findall(r'(?:href|src)="(/[^"]*/static/[^"]+)"', body)
    assert assets and all(asset.startswith(f"{PREFIX}/static/") for asset in assets)
    assert all(client.get(asset).status_code == 200 for asset in assets)


def test_the_host_guard_covers_senior_pages_and_static_files(tmp_path):
    host = _host(tmp_path)
    signed_out, without_access = host.test_client(), _signed_in(host, "visitor@example.com")

    for path in (f"{PREFIX}/", f"{PREFIX}/static/css/app.css"):
        assert signed_out.get(path).status_code == 401
        assert without_access.get(path).status_code == 403


@pytest.mark.parametrize("protection, status", [(None, 200), (lambda: True, 200), (lambda: False, 403)])
def test_the_host_mutation_protection_decides_a_senior_post_but_not_a_get(tmp_path, protection, status):
    host = _host(tmp_path, **({"MUTATION_PROTECTION": protection} if protection else {}))
    # Senior has no editor actions yet. A POST route in Senior's namespace runs Senior's request hooks.
    host.add_url_rule(f"{PREFIX}/probe", "senior.probe", lambda: "changed", methods=["POST"])
    client = _signed_in(host)

    assert client.post(f"{PREFIX}/probe").status_code == status
    assert client.get(f"{PREFIX}/").status_code == 200


def test_the_actor_comes_from_the_host_or_is_none(tmp_path):
    identity = {"email": "admin@example.com", "name": "Admin"}

    with _host(tmp_path, ACTOR=lambda: identity).test_request_context(f"{PREFIX}/"):
        assert _actor() == identity
    with _host(tmp_path / "without-actor").test_request_context(f"{PREFIX}/"):
        assert _actor() is None


def test_the_host_keeps_its_own_files_origin(tmp_path):
    host = _host(tmp_path)

    assert host.extensions["senior"]["settings"]["FILES_PUBLIC_ORIGIN"] == "/files/senior"


@pytest.mark.parametrize("missing", ["STATE_DIRECTORY", "OUTPUT_DIRECTORY", "FILES_PUBLIC_ORIGIN"])
def test_registration_names_a_missing_setting(tmp_path, missing):
    settings = {"STATE_DIRECTORY": tmp_path, "OUTPUT_DIRECTORY": tmp_path, "FILES_PUBLIC_ORIGIN": "/files"}
    del settings[missing]

    with pytest.raises(KeyError, match=missing):
        register(Flask("host"), settings)
