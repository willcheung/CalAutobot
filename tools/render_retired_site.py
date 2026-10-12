"""Render public pages without importing the application or database.

Run with Jinja2 installed after template edits, then commit public HTML.
Production builds only use Node to copy the static assets.
"""
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public"
OUT.mkdir(exist_ok=True)
env = Environment(loader=FileSystemLoader(ROOT / "app/templates"),
                  autoescape=select_autoescape(["html"]))

def url_for(endpoint, **values):
    if endpoint == "static":
        path = "/static/" + values["filename"]
    else:
        path = {"main_routes.index": "/", "main_routes.terms": "/terms",
                "main_routes.privacy": "/privacy"}.get(endpoint, "/retired")
    return "https://calautobot.com" + path if values.get("_external") else path

env.globals.update(url_for=url_for, current_user=SimpleNamespace(is_authenticated=False),
                   get_flashed_messages=lambda **kwargs: [])
for template, filename, path, endpoint in [
    ("index.html", "index.html", "/", "main_routes.index"),
    ("terms.html", "terms.html", "/terms", "main_routes.terms"),
    ("privacy.html", "privacy.html", "/privacy", "main_routes.privacy"),
    ("image_to_calendar.html", "image-to-calendar.html", "/image-to-calendar", "main_routes.image_to_calendar"),
    ("signup_closed.html", "retired.html", "/retired", "main_routes.signup"),
]:
    html = env.get_template(template).render(
        request=SimpleNamespace(base_url="https://calautobot.com" + path, endpoint=endpoint),
        show_landing_header=True, display_sidebar=False)
    (OUT / filename).write_text(html)
(OUT / "health.json").write_text('{"status":"ok","service":"retired","database":"disabled"}\n')
