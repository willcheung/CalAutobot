import compileall
from pathlib import Path


def test_source_compiles():
    project_root = Path(__file__).resolve().parents[1]
    assert compileall.compile_dir(
        str(project_root / "app"),
        quiet=1,
        maxlevels=10,
    ), "Python sources failed to compile"
