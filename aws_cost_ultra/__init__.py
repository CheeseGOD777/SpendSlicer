"""aws_cost_ultra — self-hosted unified FinOps tool for AWS.

Zero data custody: every AWS call runs from the user's machine against their
own local credentials. No server stores cost data or profile secrets.

Package layout:
    core/       Pure business logic (framework-free, unit-testable)
    aws/        AWS API wrappers — sessions, Cost Explorer, resource enumerators
    audit/      FinOps audit engine (untagged, idle, unused, budget breach)
    exporters/  PDF / CSV / JSON / Slack / S3 / SES output
    cli/        Typer + Rich command-line interface
    web/        FastAPI + Jinja + HTMX dashboard

Public imports are kept narrow; most users should use the CLI or web UI.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
