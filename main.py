import os
import pathlib
from jinja2 import FileSystemLoader
from app import app  # noqa: F401

# Vercel's vendored Flask patches the template loader and doesn't recurse into
# subdirectories. Override with an explicit FileSystemLoader using an absolute path.
_template_dir = pathlib.Path(__file__).parent / 'app' / 'templates'
if _template_dir.exists():
    app.jinja_loader = FileSystemLoader(str(_template_dir))

@app.route('/_debug/fs')
def debug_fs():
    import json
    result = {
        '__file__': str(pathlib.Path(__file__).parent),
        'template_dir_exists': _template_dir.exists(),
        'template_dir': str(_template_dir),
        'var_task': os.listdir('/var/task') if os.path.exists('/var/task') else 'N/A',
        'app_dir': os.listdir(str(pathlib.Path(__file__).parent / 'app')) if (pathlib.Path(__file__).parent / 'app').exists() else 'N/A',
        'templates_dir': os.listdir(str(_template_dir)) if _template_dir.exists() else 'N/A',
    }
    return json.dumps(result, indent=2), 200, {'Content-Type': 'application/json'}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
