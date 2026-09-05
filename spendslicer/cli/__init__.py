"""spendslicer CLI dispatcher.

Currently implemented subcommands:
  cur status          — show CUR warehouse status
  cur ingest          — pull new CUR partitions from S3 into DuckDB
  cur reset           — wipe the local CUR database
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] == "cur":
        from spendslicer.cur.setup import main as cur_main
        return cur_main(args[1:])
    print("spendslicer: available subcommands: cur")
    print("Run `spendslicer cur --help` for usage.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
