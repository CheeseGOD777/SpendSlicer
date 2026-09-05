"""spendslicer — self-hosted AWS cost visibility and FinOps audit.

Zero data custody: every AWS call runs from the user's machine against their
own local credentials. No server stores cost data or profile secrets.

Package layout:
    core/       Pure business logic (framework-free, unit-testable)
    aws/        AWS API wrappers — sessions, Cost Explorer, cost store
    resources/  Per-resource cost attribution (EC2, EBS, RDS, S3, ...)
    audit/      Waste audit engine (idle, untagged, budget breach)
    cur/        Optional CUR/Data-Exports warehouse backed by DuckDB
    exporters/  PDF / CSV / JSON / Slack / S3 / SES output
    cli/        Command-line interface
    web/        FastAPI backend + React dashboard

Public imports are kept narrow; most users should use the CLI or web UI.
"""

__version__ = "0.3.0"

__all__ = ["__version__"]
