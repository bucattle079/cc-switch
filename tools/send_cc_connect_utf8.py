from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("message_file")
    parser.add_argument("--project", default="VELA")
    parser.add_argument("--session", default="")
    parser.add_argument(
        "--cc-connect",
        default=r"C:\Users\Admin\AppData\Roaming\npm\node_modules\cc-connect\bin\cc-connect.exe",
    )
    args = parser.parse_args()

    message = Path(args.message_file).read_text(encoding="utf-8")
    cmd = [args.cc_connect, "send", "--project", args.project]
    if args.session:
        cmd.extend(["--session", args.session])
    cmd.append("--stdin")
    completed = subprocess.run(
        cmd,
        input=message,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
