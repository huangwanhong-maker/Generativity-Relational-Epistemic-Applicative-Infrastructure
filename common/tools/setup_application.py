"""Recreate an independent application's environment; source and data stay separate."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

INFRA = Path(__file__).resolve().parents[2]


def windows_path(path):
    absolute = str(Path(path).resolve())
    # Pip then keeps an extended sys.prefix for long nested wheel resources.
    if os.name == "nt" and not absolute.startswith("\\\\?\\"):
        return "\\\\?\\" + absolute
    return absolute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", choices=("generalized", "academia"))
    parser.add_argument("--dev", action="store_true", help="Install Python test dependencies as well")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or later is required.")
    environment = INFRA / ".runtime" / "environments" / args.application
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.exists():
        venv.EnvBuilder(with_pip=True).create(windows_path(environment))
    command = [windows_path(interpreter), "-m", "pip", "install"]
    if args.application == "generalized":
        web = INFRA / "gr_generalized_application/web_application"
        command += ["-r", str(web / "requirements.lock"),
                    "-e", str(INFRA / "common/packages/gsp_record_protocol"),
                    "-e", str(INFRA / "common/packages/gsp_git_store")]
        if args.dev:
            command += ["-r", str(web / "requirements-dev.txt")]
    else:
        package = INFRA / "gr_academia_application/domain_packages/grrp"
        command += ["-e", str(package) + ("[dev]" if args.dev else "")]
    subprocess.run(command, check=True, cwd=INFRA.parent)
    if args.application == "academia":
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            parser.error("Install Node.js and npm before building academia.")
        web = INFRA / "gr_academia_application/web_application"
        subprocess.run([npm, "ci"], check=True, cwd=web)
        subprocess.run([npm, "run", "build"], check=True, cwd=web)
    print(f"Environment ready. Run: python applicative_infrastructure/common/tools/run_application.py {args.application}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
