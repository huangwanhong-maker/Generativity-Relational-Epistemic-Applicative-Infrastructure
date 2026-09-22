"""Start either independent application using explicit, CWD-independent locations."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

INFRA = Path(__file__).resolve().parents[2]


def python_for(application):
    environment = INFRA / ".runtime" / "environments" / application
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def launch_config(application, host="127.0.0.1", port=None, environ=None):
    env = dict(os.environ if environ is None else environ)
    runtime = INFRA / ".runtime" / application
    if application == "generalized":
        entry = INFRA / "gr_generalized_application/web_application/run.py"
        env.setdefault("GSP_DATA_DIR", str(runtime))
        command = [str(python_for(application)), str(entry), "--host", host, "--port", str(port or 8000)]
    elif application == "academia":
        runtime = Path(env.get("GRA_RUNTIME", runtime)).expanduser()
        web = INFRA / "gr_academia_application/web_application"
        entry = web / "packages/server/dist/main.js"
        env.setdefault("GRA_RECORDS", str(runtime / "records"))
        env.setdefault("GRA_DB", str(runtime / "index.sqlite"))
        env.setdefault("GRA_CLIENT", str(web / "packages/client/dist"))
        env.setdefault("GRA_PYTHON", str(python_for(application)))
        env["GRA_HOST"], env["GRA_PORT"] = host, str(port or 8001)
        command = [shutil.which("node") or "node", str(entry)]
    else:
        raise ValueError("Unknown application")
    # Explicit overrides are allowed, but cannot acquire a different meaning
    # merely because an npm workspace or terminal changes directory.
    for key in ("GSP_DATA_DIR", "GRA_RUNTIME", "GRA_RECORDS", "GRA_DB", "GRA_CLIENT", "GRA_PYTHON"):
        if key in env:
            path = Path(env[key]).expanduser()
            if not path.is_absolute():
                raise ValueError(f"{key} must be an absolute path.")
            env[key] = str(path.resolve())
    return command, env, entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", choices=("generalized", "academia"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    try:
        command, env, entry = launch_config(args.application, args.host, args.port)
    except ValueError as error:
        parser.error(str(error))
    if not python_for(args.application).is_file() or not entry.is_file():
        parser.error("Application environment or build is missing. Follow applicative_infrastructure/README.md.")
    try:
        return subprocess.call(command, cwd=INFRA.parent, env=env)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
