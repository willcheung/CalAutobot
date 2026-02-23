import os
import pathlib
from jinja2 import FileSystemLoader
from app import app  # noqa: F401

# Vercel's vendored Flask patches the template loader and doesn't recurse into
# subdirectories. Override with an explicit FileSystemLoader using an absolute path.
_template_dir = pathlib.Path(__file__).parent / 'app' / 'templates'
if _template_dir.exists():
    app.jinja_loader = FileSystemLoader(str(_template_dir))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
