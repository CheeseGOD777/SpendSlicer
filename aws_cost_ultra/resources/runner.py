"""Parallel enumerator — all CE services, all regions (account-wide accuracy)."""

from __future__ import annotations

import contextvars
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import boto3

log = logging.getLogger(__name__)

from aws_cost_ultra.aws.cost_explorer import CostExplorerClient
from aws_cost_ultra.aws.session import accessible_regions
from aws_cost_ultra.core.filters import CostFilterSpec, pre_credit_gross
from aws_cost_ultra.core.types import TimeWindow

from .base import AttributedResource
from .dynamodb import attribute_dynamodb
from .ebs import attribute_ebs
from .ec2 import attribute_ec2_account, describe_instances_raw, live_instance_names
from .eip import attribute_eip
from .elb import attribute_elb
from .lambda_fn import attribute_lambda
from .rds import attribute_rds
from .s3 import attribute_s3, attribute_s3_all

# FINDINGS 17 & 34: a single shared bounded executor caps total threads
# regardless of how many (service x region) work units we generate. Previously
# an outer pool (up to 16) submitted per-service jobs that each opened their
# OWN inner pool (up to 12), multiplying into ~70+ concurrent threads.
_MAX_WORKERS = 16

# FINDING 18: rescaling per-resource costs up to the CE total is only safe when
# the raw attributed sum is in the same ballpark as the CE total. A tiny raw_sum
# yields a huge factor that inflates every row. Only rescale inside this band.
_RESCALE_MIN_FACTOR = 0.2
_RESCALE_MAX_FACTOR = 5.0

SERVICE_TO_CE: dict[str, str] = {
    "EC2": "Amazon Elastic Compute Cloud - Compute",
    "EBS": "EC2 - Other",
    "EIP": "EC2 - Other",
    "RDS": "Amazon Relational Database Service",
    "ELB": "Amazon Elastic Load Balancing",
    "Lambda": "AWS Lambda",
    "S3": "Amazon Simple Storage Service",
    "DynamoDB": "Amazon DynamoDB",
}

ENUMERATED_CE_SERVICES: set[str] = set(SERVICE_TO_CE.values())

ALL_REGIONS = "all"

# (bucket label, CE service name, display service for the remainder row).
# EIP is absent on purpose: its rows are exact-rate and reconcile against the
# VPC aggregate instead (see _reconcile_pools).
_REMAINDER_POOLS: list[tuple[str, str, str]] = [
    ("EC2", "Amazon Elastic Compute Cloud - Compute", "EC2"),
    ("EBS", "EC2 - Other", "EC2-Other"),
    ("RDS", "Amazon Relational Database Service", "RDS"),
    ("ELB", "Amazon Elastic Load Balancing", "ELB"),
    ("Lambda", "AWS Lambda", "Lambda"),
    ("DynamoDB", "Amazon DynamoDB", "DynamoDB"),
    ("S3", "Amazon Simple Storage Service", "S3"),
]


def _resolve_regions(session: boto3.Session, region: str) -> list[str]:
    if region == ALL_REGIONS:
        return accessible_regions(session)
    return [region]


def _frozen_session(base: boto3.Session, region: str) -> boto3.Session:
    """Return a new Session with frozen credentials safe to use in a thread."""
    creds = base.get_credentials()
    if creds is not None:
        c = creds.get_frozen_credentials()
        return boto3.Session(
            aws_access_key_id=c.access_key,
            aws_secret_access_key=c.secret_key,
            aws_session_token=c.token,
            region_name=region,
        )
    return boto3.Session(region_name=region)


def _rescale_rows(
    rows: list[AttributedResource],
    ce_tot: float,
    what: str,
    incomplete: bool = False,
) -> None:
    """Scale per-resource costs up/down to match a CE total — FINDING 18.

    Clamp the factor to a sane band so a tiny raw_sum (near-zero) can't blow up
    into a huge multiplier that inflates every row. Outside the band we leave the
    raw attributed costs untouched and log a drift warning.

    FINDING 24: when this service's attribution was ``incomplete`` (a region or
    work unit failed after retries), do NOT rescale — scaling partial rows up to
    the full CE total would silently misattribute the missing regions' cost onto
    the rows we did manage to fetch.
    """
    if not rows or not ce_tot or ce_tot <= 0:
        return
    if incomplete:
        log.warning(
            "%s attribution incomplete (a region/work unit failed); skipping rescale "
            "to avoid attributing missing cost onto the rows we did fetch",
            what,
        )
        return
    raw_sum = sum(r.cost_usd for r in rows)
    if raw_sum <= 0:
        return
    factor = ce_tot / raw_sum
    if not (_RESCALE_MIN_FACTOR <= factor <= _RESCALE_MAX_FACTOR):
        log.warning(
            "%s rescale factor %.3f outside [%.2f, %.2f] (raw_sum=%.4f, ce_total=%.4f); "
            "leaving raw attributed costs unscaled",
            what, factor, _RESCALE_MIN_FACTOR, _RESCALE_MAX_FACTOR, raw_sum, ce_tot,
        )
        return
    for r in rows:
        r.cost_usd *= factor
        # FINDING (audit): the "EC2 - Other" pool EBS/EIP rescale to also covers
        # NAT/data-transfer/snapshots, so a factor far from 1.0 means volume
        # costs absorbed non-volume spend. Record it so the number is auditable
        # rather than a silent multiplier.
        try:
            if isinstance(r.attributes, dict):
                r.attributes["rescale_factor"] = round(factor, 4)
                r.attributes["rescaled_to"] = what
        except Exception:
            pass


def _service_region_totals(
    ce_client,
    window_start,
    window_end,
    spec: CostFilterSpec,
    service_names: list[str],
) -> dict[tuple[str, str], float]:
    """One CE call grouped by [SERVICE, REGION] for the given services.

    Lambda/DynamoDB attribution splits a CE total across each region's own
    resources; handing every region the ACCOUNT-WIDE total meant each region
    ended up with exactly total/region_count regardless of real usage. This
    region-scopes those totals the same way EC2's per-region queries do.
    """
    from aws_cost_ultra.core.filters import build_ce_filter

    filt_parts = []
    base_filter = build_ce_filter(spec)
    if base_filter:
        filt_parts.append(base_filter)
    filt_parts.append({"Dimensions": {"Key": "SERVICE", "Values": service_names}})
    combined = {"And": filt_parts} if len(filt_parts) > 1 else filt_parts[0]

    out: dict[tuple[str, str], float] = {}
    token = None
    while True:
        kwargs = {
            "TimePeriod": {
                "Start": window_start.strftime("%Y-%m-%d"),
                "End": window_end.strftime("%Y-%m-%d"),
            },
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [
                {"Type": "DIMENSION", "Key": "SERVICE"},
                {"Type": "DIMENSION", "Key": "REGION"},
            ],
            "Filter": combined,
        }
        if token:
            kwargs["NextPageToken"] = token
        resp = ce_client.get_cost_and_usage(**kwargs)
        try:
            from aws_cost_ultra.web.middleware import get_current_counter
            _results = resp.get("ResultsByTime", [])
            get_current_counter().add(
                pages=1,
                records=sum(len(p.get("Groups", []) or []) for p in _results),
            )
        except Exception:
            pass
        for period in resp.get("ResultsByTime", []):
            for g in period.get("Groups", []):
                svc, reg = g["Keys"][0], g["Keys"][1]
                amount = float(g["Metrics"]["UnblendedCost"]["Amount"])
                out[(svc, reg)] = out.get((svc, reg), 0.0) + amount
        token = resp.get("NextPageToken")
        if not token:
            break
    return out


def _reconcile_pools(
    buckets: dict[str, list[AttributedResource]],
    ce_total_by_service: dict[str, float],
    failed_services: set[str],
    want: Optional[set[str]],
    display_region: str,
    lambda_ddb_region_scoped: bool = False,
) -> list[AttributedResource]:
    """Post-fan-out reconciliation: pool rescales + CE service aggregate rows.

    EIP rows are deliberately NOT rescaled: since Feb 2024 every public IPv4
    address bills at exactly $0.005/hr under "Amazon Virtual Private Cloud"
    (PublicIPv4:InUseAddress / IdleAddress), so the raw priced cost is already
    exact. Squashing them into the "EC2 - Other" pool (the pre-2024 model)
    under-priced every address. To avoid double counting, the VPC aggregate
    row is reduced by whatever the EIP rows already attribute.
    """
    # FINDING 18: EBS rescaled to the shared "EC2 - Other" CE pool, clamped.
    _rescale_rows(
        buckets.get("EBS", []), ce_total_by_service.get("EC2 - Other", 0.0),
        "EBS", incomplete="EBS" in failed_services,
    )

    # FINDING 18: RDS / ELB rescaled to their own CE totals, clamped.
    for label, ce_name in [
        ("RDS", "Amazon Relational Database Service"),
        ("ELB", "Amazon Elastic Load Balancing"),
    ]:
        _rescale_rows(
            buckets.get(label, []), ce_total_by_service.get(ce_name, 0.0), label,
            incomplete=label in failed_services,
        )

    # AUDIT (critical): Lambda and DynamoDB are attributed *per region*, but the
    # CE service total handed to each region's work unit is account-wide (no
    # REGION grouping/filter). Each region therefore splits the FULL total
    # across only its own functions/tables, so the combined cross-region sum is
    # roughly (region_count x true_total) — Lambda/DynamoDB cost inflates by the
    # number of active regions. Unlike EC2 (per-region CE scoping) these have no
    # such scoping, so reconcile the COMBINED rows back down to the single CE
    # total here. A factor of ~1/region_count is expected and legitimate, so we
    # normalise directly rather than via _rescale_rows' tiny-raw-sum clamp
    # [0.2, 5.0] (which would otherwise SKIP the correction past 5 regions and
    # leave the inflation in place). Skip when partial (FINDING 24) — scaling
    # incomplete rows up would misattribute the missing regions' cost.
    # When the totals were already REGION-scoped (``lambda_ddb_region_scoped``),
    # each region split its own bill and the combined sum is already right —
    # renormalizing here would smear it back to total/region_count.
    for label in () if lambda_ddb_region_scoped else ("Lambda", "DynamoDB"):
        rows = buckets.get(label, [])
        ce_tot = ce_total_by_service.get(SERVICE_TO_CE.get(label, ""), 0.0)
        if not rows or ce_tot <= 0 or label in failed_services:
            continue
        raw_sum = sum(r.cost_usd for r in rows)
        if raw_sum <= 0:
            continue
        factor = ce_tot / raw_sum
        for r in rows:
            r.cost_usd *= factor

    eip_attributed = sum(r.cost_usd for r in buckets.get("EIP", []))

    other_rows: list[AttributedResource] = []
    for ce_name, total in ce_total_by_service.items():
        if ce_name in ENUMERATED_CE_SERVICES:
            continue
        attrs = {
            "aggregate": True,
            "ce_service_name": ce_name,
            "note": "CE total — per-resource breakdown not yet available",
        }
        if ce_name == "Amazon Virtual Private Cloud" and eip_attributed > 0:
            # The per-address EIP/public-IP rows already carry this much of the
            # VPC bill; only the remainder (NAT gateways, endpoints, …) stays
            # in the aggregate.
            total = total - eip_attributed
            attrs["reduced_by_attributed_eip_usd"] = round(eip_attributed, 4)
            attrs["note"] = (
                "CE total minus the public-IPv4 cost shown as per-address "
                "rows (NAT gateways, endpoints and other VPC charges remain)"
            )
        if total <= 0.001:
            continue
        label = _short_label(ce_name)
        if want is not None and label not in want:
            continue
        other_rows.append(AttributedResource(
            service=label,
            resource_id=f"ce:{ce_name}",
            name=ce_name,
            resource_type="service aggregate",
            state="active",
            cost_usd=total,
            hours=0.0,
            region=display_region,
            attributes=attrs,
        ))

    # Remainder rows: whenever an ENUMERATED service's attributed rows sum to
    # less than its CE total (rescale clamp tripped, inventory deleted since a
    # closed month, unpriced instance classes, partial scans), the difference
    # used to vanish — the service is excluded from the aggregate loop above,
    # so CE-vs-Resources drift silently swallowed real dollars. Surface the
    # gap as one labelled row per pool, mirroring the EC2 unmatched-bucket fix.
    for bucket_label, ce_name, display_service in _REMAINDER_POOLS:
        ce_tot = ce_total_by_service.get(ce_name, 0.0)
        if ce_tot <= 0.01:
            continue
        if want is not None and bucket_label not in want:
            continue
        attributed = sum(r.cost_usd for r in buckets.get(bucket_label, []))
        remainder = ce_tot - attributed
        if remainder <= 0.01:
            continue
        note = (
            "CE bills this much for the service in the window beyond what the "
            "per-resource rows cover — commonly resources deleted/replaced "
            "after the period, instance classes without a known rate, or a "
            "pool shared with non-enumerable charges (NAT, snapshots, data "
            "transfer for EC2 - Other)."
        )
        if bucket_label in failed_services:
            note += " This service's scan also failed partway, so rows are partial."
        other_rows.append(AttributedResource(
            service=display_service,
            resource_id=f"ce-remainder:{ce_name}",
            name=f"{ce_name} — unattributed remainder",
            resource_type="service remainder",
            state="unattributed",
            cost_usd=remainder,
            hours=0.0,
            region=display_region,
            attributes={
                "aggregate": True,
                "ce_service_name": ce_name,
                "attributed_usd": round(attributed, 4),
                "note": note,
            },
        ))
    return other_rows


def enumerate_all(
    session: boto3.Session,
    window: TimeWindow,
    region: str = ALL_REGIONS,
    spec: Optional[CostFilterSpec] = None,
    services: Optional[list[str]] = None,
    top_n: Optional[int] = None,
    errors: Optional[list[dict]] = None,
) -> list[AttributedResource]:
    """Per-resource rows + CE aggregate rows for every active service.

    ``region`` may be a single region code or ``"all"`` (default) to scan
    every opted-in region — required for account-wide CE totals to match
    attributed resource sums.

    ``top_n`` (optional): when set, only the top ``top_n`` rows by cost are
    returned and the long tail is collapsed into a single synthetic
    "other resources" aggregate row (mirroring ``other_rows``). Default
    ``None`` preserves the original behaviour of returning every row.

    ``errors`` (optional): if a list is passed, one ``{"service", "error"}``
    dict is appended for every work unit that failed after retries (FINDING
    24), so callers can surface "results may be incomplete" to the user.
    """
    spec = spec or pre_credit_gross()
    regions = _resolve_regions(session, region)
    display_region = region if region != ALL_REGIONS else ALL_REGIONS

    ws = window.start.replace(tzinfo=None) if window.start.tzinfo else window.start
    we = window.end.replace(tzinfo=None) if window.end.tzinfo else window.end

    ce_raw = session.client("ce", region_name="us-east-1")
    ce_hl = CostExplorerClient(session=session, ce_client=ce_raw)

    # AUDIT (high): the per-service CE totals drive the rescale/aggregate rows.
    # When a SINGLE region is requested, those totals must be REGION-scoped —
    # otherwise account-wide service spend is rescaled onto (and aggregated for)
    # one region's resources, inflating a single-region view by the cost of
    # every other region. When viewing "all", no region filter is applied.
    totals_spec = spec
    if region != ALL_REGIONS:
        from dataclasses import replace as _dc_replace
        totals_spec = _dc_replace(spec, region=region)

    try:
        ce_groups = ce_hl.get_cost_by_service(window, spec=totals_spec)
        ce_total_by_service = {g.primary_key(): g.value.amount_usd for g in ce_groups}
    except Exception as exc:
        log.warning("enumerate_all: CE get_cost_by_service failed, continuing without CE totals: %s", type(exc).__name__, exc_info=True)
        ce_total_by_service = {}

    def ce_total(label: str) -> float:
        return ce_total_by_service.get(SERVICE_TO_CE.get(label, ""), 0.0)

    want = set(services) if services else None

    def want_it(label: str) -> bool:
        return want is None or label in want

    buckets: dict[str, list[AttributedResource]] = {}

    # FINDINGS 17 & 34: reuse ONE frozen Session per region across every service
    # so we don't re-freeze creds / open redundant client stacks per (svc, region).
    frozen_by_region: dict[str, boto3.Session] = {
        reg: _frozen_session(session, reg) for reg in regions
    }
    # FINDING (audit, concurrency): a boto3 Session is not thread-safe for the
    # FIRST client() creation (it lazily initialises a shared data loader /
    # endpoint resolver / event system); concurrent first-creations on the same
    # Session race. Each per-region frozen Session is shared by up to ~6 work
    # units that run concurrently, so warm each Session once here in the
    # submitting thread — after warm-up, concurrent client() calls are safe.
    for _reg, _sess in frozen_by_region.items():
        try:
            _sess.client("ec2", region_name=_reg, config=None)
        except Exception:
            pass

    # FINDING 21: do ONE describe_instances scan per region, shared by BOTH EC2
    # attribution and EBS's id->name lookup, instead of each paginating it
    # separately. Cache lazily, locked per region so concurrent EC2/EBS work
    # units for the same region don't both scan (different regions still run
    # in parallel).
    instances_by_region: dict[str, list[dict]] = {}
    region_locks: dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def _instances_for(reg: str) -> list[dict]:
        if reg in instances_by_region:
            return instances_by_region[reg]
        with _locks_guard:
            lk = region_locks.setdefault(reg, threading.Lock())
        with lk:
            if reg not in instances_by_region:
                try:
                    instances_by_region[reg] = describe_instances_raw(frozen_by_region[reg], reg)
                except Exception as exc:
                    log.warning("describe_instances failed for region=%s: %s", reg, type(exc).__name__, exc_info=True)
                    instances_by_region[reg] = []
        return instances_by_region[reg]

    def _names_for(reg: str) -> dict[str, str]:
        return live_instance_names(frozen_by_region[reg], reg, instances=_instances_for(reg))

    # FINDINGS 17, 20, 34: build a FLAT list of (label, thunk) work units across
    # every (service x region), plus EC2 (one account-wide call) and S3 (one
    # account-wide call, FINDING 3). Submit them all to a single bounded pool —
    # no nested executors. EBS (FINDING 20) is parallelized as one unit per region.
    work: list[tuple[str, callable]] = []

    # A warmed frozen Session for account-wide / us-east-1 work (S3, EC2 CE).
    frozen_global = _frozen_session(session, "us-east-1")
    try:
        frozen_global.client("sts")
    except Exception:
        pass

    if want_it("EC2"):
        # FINDING (audit, scale): submit ONE EC2 work unit PER REGION instead of
        # a single unit that loops every region serially on one thread (each
        # region is a paginated CE call + bucketing — the old single unit was
        # the long pole while 16 workers sat idle). Each unit uses that region's
        # frozen Session (FINDING 11: not the shared raw base session) and the
        # shared ce_raw client (boto3 clients are thread-safe to call).
        def _mk_ec2(reg):
            ts = frozen_by_region[reg]
            return lambda: attribute_ec2_account(
                ts, ce_raw, ws, we, [reg], spec, instances_provider=_instances_for,
            )
        for reg in regions:
            work.append(("EC2", _mk_ec2(reg)))

    if want_it("S3"):
        # FINDING 3: list buckets + resolve bucket regions ONCE, account-wide,
        # instead of per-region fan-out of attribute_s3. FINDING 11: use a frozen
        # session, not the shared raw base session that the submitting thread and
        # other work units also touch.
        work.append(("S3", lambda: attribute_s3_all(frozen_global, ws, we, regions, ce_total("S3"))))

    def _mk(fn, reg, *extra):
        ts = frozen_by_region[reg]
        return lambda: fn(ts, ws, we, reg, *extra)

    def _mk_ebs(reg):
        ts = frozen_by_region[reg]
        return lambda: attribute_ebs(ts, ws, we, reg, _names_for(reg))

    # Region-scope the Lambda/DynamoDB totals with one extra CE call so each
    # region splits ITS OWN bill (handing every region the account-wide total
    # made each region show exactly total/region_count regardless of usage).
    # Falls back to the account-wide totals + post-fan-out normalization when
    # the call fails or only one region is scanned (already correctly scoped).
    lambda_ddb_regional: dict[tuple[str, str], float] = {}
    if (want_it("Lambda") or want_it("DynamoDB")) and len(regions) > 1:
        try:
            lambda_ddb_regional = _service_region_totals(
                ce_raw, ws, we, totals_spec, ["AWS Lambda", "Amazon DynamoDB"],
            )
        except Exception as exc:
            log.warning(
                "SERVICE x REGION totals for Lambda/DynamoDB failed (%s); "
                "falling back to account-wide totals + normalization",
                type(exc).__name__,
            )
            lambda_ddb_regional = {}
    region_scoped = bool(lambda_ddb_regional)

    def _regional_total(ce_name: str, reg: str, label: str) -> float:
        if lambda_ddb_regional:
            return lambda_ddb_regional.get((ce_name, reg), 0.0)
        # Fallback: account-wide total (single region, or the regional CE
        # call failed) — the post-fan-out normalization reconciles the sum.
        return ce_total(label)

    for reg in regions:
        if want_it("RDS"):
            work.append(("RDS", _mk(attribute_rds, reg)))
        if want_it("EIP"):
            work.append(("EIP", _mk(attribute_eip, reg)))
        if want_it("ELB"):
            work.append(("ELB", _mk(attribute_elb, reg)))
        if want_it("Lambda"):
            work.append(("Lambda", _mk(
                attribute_lambda, reg, _regional_total("AWS Lambda", reg, "Lambda"),
            )))
        if want_it("DynamoDB"):
            work.append(("DynamoDB", _mk(
                attribute_dynamodb, reg, _regional_total("Amazon DynamoDB", reg, "DynamoDB"),
            )))
        if want_it("EBS"):
            work.append(("EBS", _mk_ebs(reg)))

    for label, _ in work:
        buckets.setdefault(label, [])

    failed_services: set[str] = set()
    if work:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(work))) as pool:
            # Run each thunk inside a copied context (fresh per submit) so the
            # per-request CE call-counter ContextVar propagates into the worker
            # threads — otherwise instrumented CE calls in the pool hit a
            # throwaway counter and X-CE-Calls-Spent under-reports resource spend.
            futs = {
                pool.submit(contextvars.copy_context().run, thunk): label
                for label, thunk in work
            }
            for fut in as_completed(futs):
                label = futs[fut]
                try:
                    buckets[label].extend(fut.result())
                except Exception as exc:
                    # FINDING 24: adaptive retries on the clients above absorb
                    # most throttling before it reaches here. A unit that still
                    # fails leaves this service's attribution incomplete — record
                    # it so we (a) skip rescaling partial data and (b) can tell
                    # the caller the results may be incomplete.
                    failed_services.add(label)
                    if errors is not None:
                        errors.append({"service": label, "error": type(exc).__name__})
                    log.warning(
                        "resource work unit failed for service=%s: %s",
                        label, type(exc).__name__, exc_info=True,
                    )

    # Public IPv4 addresses auto-assigned to instances (not EIPs) bill at the
    # same $0.005/hr under VPC but never appear in describe_addresses — add
    # per-address rows from the instance scans we already have, excluding IPs
    # an associated EIP row already covers.
    if want_it("EIP") and "EIP" not in failed_services:
        from .eip import auto_assigned_ip_rows
        eip_ips = frozenset(
            (r.attributes or {}).get("public_ip", "")
            for r in buckets.get("EIP", [])
        )
        for reg, insts in instances_by_region.items():
            if insts:
                buckets.setdefault("EIP", []).extend(
                    auto_assigned_ip_rows(insts, reg, ws, we, exclude_ips=eip_ips)
                )

    other_rows = _reconcile_pools(
        buckets, ce_total_by_service, failed_services, want, display_region,
        lambda_ddb_region_scoped=region_scoped,
    )

    flat: list[AttributedResource] = []
    for svc_rows in buckets.values():
        flat.extend(svc_rows)
    flat.extend(other_rows)
    flat.sort(key=lambda r: r.cost_usd, reverse=True)

    # FINDING 22: optional server-side top-N cap. When requested, keep the
    # top_n highest-cost rows and collapse the long tail into one synthetic
    # "other resources" aggregate row so the returned total is preserved.
    if top_n is not None and top_n >= 0 and len(flat) > top_n:
        head = flat[:top_n]
        tail = flat[top_n:]
        tail_cost = sum(r.cost_usd for r in tail)
        if tail_cost > 0.001:
            head.append(AttributedResource(
                service="Other",
                resource_id="other:long-tail",
                name=f"Other resources ({len(tail)} rows)",
                resource_type="aggregate",
                state="active",
                cost_usd=tail_cost,
                hours=0.0,
                region=display_region,
                attributes={
                    "aggregate": True,
                    "rolled_up_rows": len(tail),
                    "note": f"long tail beyond top {top_n} rows",
                },
            ))
        flat = head
    return flat


_SHORT_LABEL_MAP = {
    "Amazon Virtual Private Cloud": "VPC",
    "AmazonCloudWatch": "CloudWatch",
    "Amazon CloudWatch": "CloudWatch",
    "AWS Cost Explorer": "CostExplorer",
    "AWS CloudTrail": "CloudTrail",
    "AWS CloudFormation": "CloudFormation",
    "AWS CodePipeline": "CodePipeline",
    "CodeBuild": "CodeBuild",
    "AWS Step Functions": "StepFunctions",
    "AWS Key Management Service": "KMS",
    "AWS Secrets Manager": "SecretsMgr",
    "Amazon Simple Notification Service": "SNS",
    "Amazon Simple Queue Service": "SQS",
    "Amazon Route 53": "Route53",
    "Amazon API Gateway": "APIGateway",
    "Amazon ElastiCache": "ElastiCache",
    "Amazon Elasticsearch Service": "OpenSearch",
    "Amazon OpenSearch Service": "OpenSearch",
    "Amazon EC2 Container Registry (ECR)": "ECR",
    "Amazon Elastic Container Service": "ECS",
    "Amazon Elastic Container Service for Kubernetes": "EKS",
    "Amazon Elastic Kubernetes Service": "EKS",
    "Amazon CloudFront": "CloudFront",
    "Amazon Athena": "Athena",
    "Amazon Kinesis": "Kinesis",
    "AWS Glue": "Glue",
    "AWS Backup": "Backup",
    "AWS WAF": "WAF",
    "AWS Shield": "Shield",
    "AWS Lambda": "Lambda",
    "AWS Systems Manager": "SSM",
    "AWS CloudShell": "CloudShell",
    "AmazonS3 Glacier": "S3 Glacier",
}


def _short_label(ce_service_name: str) -> str:
    if ce_service_name in _SHORT_LABEL_MAP:
        return _SHORT_LABEL_MAP[ce_service_name]
    for prefix in ("Amazon ", "AWS "):
        if ce_service_name.startswith(prefix):
            return ce_service_name[len(prefix):]
    return ce_service_name
