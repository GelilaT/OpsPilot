"""The worker process must boot on its own (it does not import the API, so it needs every model)."""

import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]


def test_worker_app_configures_all_mappers():
    code = (
        "import app.workers.app, app.workers.tasks\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "configure_mappers()\n"
        "from app.core.jobs import JobRun\n"
        "assert JobRun.__table__.c.organisation_id.foreign_keys\n"
        "[fk.column for fk in JobRun.__table__.foreign_keys]\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=API_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
