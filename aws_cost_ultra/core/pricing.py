"""AWS Pricing API wrapper with in-memory TTL cache and regional fallback table.

Migrated verbatim from the legacy top-level ``pricing.py``. Behavior is
unchanged in Phase 1. The ap-south-1-only fallback table will be expanded
to multi-region in Phase 2.

The Pricing API is only available in us-east-1 / ap-south-1. We call
us-east-1 for stability. Rates cached 24h. If the API is unreachable or
returns nothing, fall back to a hard-coded on-demand rate table.
"""

from __future__ import annotations

import json
from datetime import datetime
from threading import Lock
from typing import Optional

import boto3
from botocore.exceptions import ClientError

_CACHE: dict[str, dict] = {}
_LOCK = Lock()
_TTL_SECONDS = 24 * 3600

# ap-south-1 (Mumbai) on-demand list prices in USD.
# Used only when the Pricing API call fails. Values taken from AWS pricing
# docs at the time of authoring.
FALLBACK_RATES: dict = {
    # EC2 instance hourly rates — ap-south-1
    "ec2": {
        "t4g.nano":    0.0028,
        "t4g.micro":   0.0056,
        "t4g.small":   0.0112,
        "t4g.medium":  0.0224,
        "t4g.large":   0.0448,
        "t4g.xlarge":  0.0896,
        "t4g.2xlarge": 0.1792,
        "t3.nano":     0.0052,
        "t3.micro":    0.0104,
        "t3.small":    0.0208,
        "t3.medium":   0.0416,
        "t3.large":    0.0832,
        "m7i.large":   0.1008,  # also covers spot fallback
        "m5.large":    0.1020,
        "m5.xlarge":   0.2040,
    },
    # EBS $/GB-month
    "ebs": {
        "gp3":      0.0912,
        "gp2":      0.114,
        "io1":      0.1425,
        "io2":      0.1425,
        "st1":      0.0513,
        "sc1":      0.0171,
        "standard": 0.08,
    },
    # RDS instance hourly rates — ap-south-1 (single-AZ, on-demand)
    "rds": {
        "db.t3.micro":   0.021,
        "db.t3.small":   0.042,
        "db.t3.medium":  0.083,
        "db.t4g.micro":  0.018,
        "db.t4g.small":  0.036,
        "db.t4g.medium": 0.073,
        "db.m5.large":   0.2,
    },
    # RDS storage $/GB-month
    "rds_storage": {
        "gp2": 0.138,
        "gp3": 0.115,
        "io1": 0.15,
    },
    # ELB hourly rates
    "elb": {
        "application": 0.0252,  # ALB per LB-hour
        "network":     0.0288,  # NLB per LB-hour
        "classic":     0.028,   # CLB per LB-hour
        "gateway":     0.0144,
    },
    # EIP $/hour when not attached
    "eip_idle": 0.005,
}


def _cache_get(key: str) -> Optional[float]:
    with _LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        if datetime.utcnow().timestamp() - entry["t"] > _TTL_SECONDS:
            return None
        return entry["v"]


def _cache_set(key: str, value: float) -> None:
    with _LOCK:
        _CACHE[key] = {"v": value, "t": datetime.utcnow().timestamp()}


def _pricing_client(session: boto3.Session):
    return session.client("pricing", region_name="us-east-1")


def _fetch_from_api(session: boto3.Session, service_code: str, filters: list[dict]) -> Optional[float]:
    try:
        client = _pricing_client(session)
        resp = client.get_products(
            ServiceCode=service_code,
            Filters=filters,
            MaxResults=1,
        )
        if not resp.get("PriceList"):
            return None
        product = json.loads(resp["PriceList"][0])
        terms = product.get("terms", {}).get("OnDemand", {})
        for _, term in terms.items():
            dims = term.get("priceDimensions", {})
            for _, dim in dims.items():
                price = dim.get("pricePerUnit", {}).get("USD")
                if price is not None:
                    return float(price)
        return None
    except (ClientError, KeyError, ValueError, json.JSONDecodeError):
        return None


def ec2_on_demand_rate(session: boto3.Session, instance_type: str, region: str = "ap-south-1") -> float:
    key = f"ec2:{region}:{instance_type}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    location = _region_to_location(region)
    price = _fetch_from_api(session, "AmazonEC2", [
        {"Type": "TERM_MATCH", "Field": "instanceType",   "Value": instance_type},
        {"Type": "TERM_MATCH", "Field": "location",       "Value": location},
        {"Type": "TERM_MATCH", "Field": "operatingSystem","Value": "Linux"},
        {"Type": "TERM_MATCH", "Field": "tenancy",        "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
        {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
    ])
    if price is None:
        price = FALLBACK_RATES["ec2"].get(instance_type, 0.0)
    _cache_set(key, price)
    return price


def ebs_rate(session: boto3.Session, volume_type: str, region: str = "ap-south-1") -> float:
    key = f"ebs:{region}:{volume_type}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    location = _region_to_location(region)
    price = _fetch_from_api(session, "AmazonEC2", [
        {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
        {"Type": "TERM_MATCH", "Field": "volumeApiName", "Value": volume_type},
        {"Type": "TERM_MATCH", "Field": "location",      "Value": location},
    ])
    if price is None:
        price = FALLBACK_RATES["ebs"].get(volume_type, FALLBACK_RATES["ebs"]["gp3"])
    _cache_set(key, price)
    return price


# describe_db_instances Engine values -> Pricing API databaseEngine values.
_RDS_ENGINE_TO_PRICING = {
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "mariadb": "MariaDB",
    "aurora-mysql": "Aurora MySQL",
    "aurora-postgresql": "Aurora PostgreSQL",
}

# describe_db_instances StorageType -> Pricing API volumeType values.
_RDS_STORAGE_TO_PRICING = {
    "gp2": "General Purpose",
    "gp3": "General Purpose-GP3",
    "io1": "Provisioned IOPS",
    "io2": "Provisioned IOPS-IO2",
    "standard": "Magnetic",
}


def _rds_engine_to_pricing(engine: str) -> Optional[str]:
    e = (engine or "").lower()
    if e in _RDS_ENGINE_TO_PRICING:
        return _RDS_ENGINE_TO_PRICING[e]
    if e.startswith("oracle"):
        return "Oracle"
    if e.startswith("sqlserver"):
        return "SQL Server"
    return None


def rds_instance_rate(session: boto3.Session, instance_class: str, engine: str, region: str = "ap-south-1") -> float:
    """Single-AZ on-demand rate. Callers double it for Multi-AZ deployments.

    The fallback table only knows 7 small classes — without the Pricing API
    every other class priced at $0.00 and its real cost either smeared onto
    siblings via the rescale or vanished past the clamp band.
    """
    key = f"rds:{region}:{instance_class}:{engine}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    location = _region_to_location(region)
    filters = [
        {"Type": "TERM_MATCH", "Field": "instanceType",     "Value": instance_class},
        {"Type": "TERM_MATCH", "Field": "location",         "Value": location},
        {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": "Single-AZ"},
    ]
    pricing_engine = _rds_engine_to_pricing(engine)
    if pricing_engine:
        filters.append({"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": pricing_engine})
    price = _fetch_from_api(session, "AmazonRDS", filters)
    if price is None:
        price = FALLBACK_RATES["rds"].get(instance_class, 0.0)
    _cache_set(key, price)
    return price


def rds_storage_rate(session: boto3.Session, storage_type: str = "gp2", region: str = "ap-south-1") -> float:
    key = f"rds_storage:{region}:{storage_type}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    location = _region_to_location(region)
    volume_type = _RDS_STORAGE_TO_PRICING.get((storage_type or "").lower())
    price = None
    if volume_type:
        price = _fetch_from_api(session, "AmazonRDS", [
            {"Type": "TERM_MATCH", "Field": "productFamily",    "Value": "Database Storage"},
            {"Type": "TERM_MATCH", "Field": "volumeType",       "Value": volume_type},
            {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": "Single-AZ"},
            {"Type": "TERM_MATCH", "Field": "location",         "Value": location},
        ])
    if price is None:
        price = FALLBACK_RATES["rds_storage"].get(storage_type, FALLBACK_RATES["rds_storage"]["gp2"])
    _cache_set(key, price)
    return price


def elb_rate(session: boto3.Session, lb_type: str, region: str = "ap-south-1") -> float:
    key = f"elb:{region}:{lb_type}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    price = FALLBACK_RATES["elb"].get(lb_type, FALLBACK_RATES["elb"]["application"])
    _cache_set(key, price)
    return price


def eip_idle_rate() -> float:
    return FALLBACK_RATES["eip_idle"]


def _region_to_location(region: str) -> str:
    return {
        "us-east-1": "US East (N. Virginia)",
        "us-east-2": "US East (Ohio)",
        "us-west-1": "US West (N. California)",
        "us-west-2": "US West (Oregon)",
        "ap-south-1": "Asia Pacific (Mumbai)",
        "ap-southeast-1": "Asia Pacific (Singapore)",
        "ap-southeast-2": "Asia Pacific (Sydney)",
        "ap-northeast-1": "Asia Pacific (Tokyo)",
        "ap-northeast-2": "Asia Pacific (Seoul)",
        "eu-west-1": "EU (Ireland)",
        "eu-west-2": "EU (London)",
        "eu-west-3": "EU (Paris)",
        "eu-central-1": "EU (Frankfurt)",
        "eu-central-2": "Europe (Zurich)",
        "eu-north-1": "EU (Stockholm)",
        "eu-south-1": "EU (Milan)",
        "eu-south-2": "Europe (Spain)",
        "ap-south-2": "Asia Pacific (Hyderabad)",
        "ap-southeast-3": "Asia Pacific (Jakarta)",
        "ap-southeast-4": "Asia Pacific (Melbourne)",
        "ap-northeast-3": "Asia Pacific (Osaka)",
        "ap-east-1": "Asia Pacific (Hong Kong)",
        "me-south-1": "Middle East (Bahrain)",
        "me-central-1": "Middle East (UAE)",
        "af-south-1": "Africa (Cape Town)",
        "il-central-1": "Israel (Tel Aviv)",
        "ca-central-1": "Canada (Central)",
        "ca-west-1": "Canada West (Calgary)",
        "sa-east-1": "South America (Sao Paulo)",
    }.get(region, region)
