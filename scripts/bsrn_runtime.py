"""Identify the application code loaded by a long-running dashboard server."""
import hashlib
from pathlib import Path

API_VERSION = 1


def source_version(root: Path) -> str:
    digest = hashlib.sha256()
    paths = [*root.joinpath('scripts').glob('*.py'),
             *root.joinpath('tools/qc-graphs').glob('*.py'),
             *root.joinpath('web').glob('*')]
    for path in sorted(p for p in paths if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
