"""spendslicer CLI dispatcher.

Subcommands:
  doctor              — why AWS credentials are not resolving
  cur status          — show CUR warehouse status
  cur ingest          — pull new CUR partitions from S3 into DuckDB
  cur reset           — wipe the local CUR database
"""

from __future__ import annotations

import sys

_USAGE = """spendslicer — self-hosted AWS cost visibility

  spendslicer doctor        check AWS credentials and show what boto3 reads
  spendslicer cur --help    CUR warehouse (status / ingest / reset)
  spendslicer-web           start the dashboard on http://127.0.0.1:8080/app
  spendslicer-desktop       start the dashboard in a native window
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] == "cur":
        from spendslicer.cur.setup import main as cur_main
        return cur_main(args[1:])
    if args and args[0] == "doctor":
        from spendslicer.doctor import main as doctor_main
        return doctor_main(args[1:])
    print(_USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
