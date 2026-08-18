"""Write docs/openapi.json from the running app definition.

The generated schema is the authoritative API contract (docs/API-CONTRACT.md).
Run inside the api container, where the dependencies live:

    make openapi
"""
import json
import os
import pathlib
import sys

# enough environment to import the app without a real deployment
os.environ.setdefault("OCEANKIND_SESSION_SECRET", "x" * 40)
os.environ.setdefault("OCEANKIND_STORAGE_BACKEND", "local")

sys.path.insert(0, "/app")
from app.main import app  # noqa: E402

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/out/openapi.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n")
print(f"wrote {out}")
