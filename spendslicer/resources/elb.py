"""Load balancer attribution (ALB / NLB / Gateway / Classic)."""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from spendslicer.core import pricing

from .base import AttributedResource, clamp_window, hours_between, tags_to_dict

# Adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

# Bound how many target groups we inspect for health to keep the
# describe_target_health fan-out from being unbounded on large accounts.
_MAX_TARGET_GROUPS = 200


def attribute_elb(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    rows: list[AttributedResource] = []

    # -- ALB / NLB / Gateway --
    try:
        elbv2 = session.client("elbv2", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
        lbs: list[dict] = []
        for page in elbv2.get_paginator("describe_load_balancers").paginate():
            lbs.extend(page.get("LoadBalancers", []))

        tag_map: dict = {}
        if lbs:
            arns = [lb["LoadBalancerArn"] for lb in lbs]
            for i in range(0, len(arns), 20):  # API max 20 ARNs per call
                resp = elbv2.describe_tags(ResourceArns=arns[i:i + 20])
                for td in resp.get("TagDescriptions", []):
                    tag_map[td["ResourceArn"]] = tags_to_dict(td.get("Tags"))

        # Healthy target count per LB, to flag "no targets" waste.
        # Call describe_target_health AT MOST ONCE per target group
        # (previously it was nested inside the per-LB-ARN loop, so a TG attached
        # to N load balancers triggered N identical health calls). Compute the
        # healthy count once and fan it out to each associated LB. Cap the number
        # of TGs inspected and rely on adaptive retries for throttling.
        healthy_by_lb: dict = {}
        try:
            tgs_seen = 0
            for page in elbv2.get_paginator("describe_target_groups").paginate():
                for tg in page.get("TargetGroups", []):
                    if tgs_seen >= _MAX_TARGET_GROUPS:
                        break
                    tgs_seen += 1
                    lb_arns = tg.get("LoadBalancerArns", [])
                    if not lb_arns:
                        continue
                    health = elbv2.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
                    healthy = sum(
                        1 for t in health.get("TargetHealthDescriptions", [])
                        if t.get("TargetHealth", {}).get("State") == "healthy"
                    )
                    for lb_arn in lb_arns:
                        healthy_by_lb[lb_arn] = healthy_by_lb.get(lb_arn, 0) + healthy
                if tgs_seen >= _MAX_TARGET_GROUPS:
                    break
        except ClientError:
            pass

        for lb in lbs:
            arn = lb["LoadBalancerArn"]
            lb_name = lb["LoadBalancerName"]
            lb_type = lb.get("Type", "application")
            state = lb.get("State", {}).get("Code", "unknown")
            created = lb.get("CreatedTime")
            tags = tag_map.get(arn, {})
            eff_s, eff_e = clamp_window(created, window_start, window_end)
            hrs = hours_between(eff_s, eff_e)
            rate = pricing.elb_rate(session, lb_type, region)
            cost = hrs * rate
            healthy = healthy_by_lb.get(arn, 0)
            waste = "no healthy targets" if arn in healthy_by_lb and healthy == 0 else None

            rows.append(AttributedResource(
                service="ELB",
                resource_id=lb_name,
                name=tags.get("Name", lb_name),
                resource_type=lb_type,
                state=state,
                cost_usd=cost,
                hours=hrs,
                region=region,
                tags=tags,
                waste_reason=waste,
                attributes={
                    "scheme": lb.get("Scheme", ""),
                    "vpc_id": lb.get("VpcId", ""),
                    "dns_name": lb.get("DNSName", ""),
                    "healthy_targets": healthy,
                    "arn": arn,
                    "rate_usd_hr": rate,
                },
            ))
    except ClientError:
        pass

    # -- Classic ELB --
    try:
        elb = session.client("elb", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
        # Paginate like the v2 path: a bare describe_load_balancers() returns at
        # most 400 CLBs and a NextMarker; without paging, CLBs beyond the first
        # page were silently dropped (and their cost redistributed onto the rest
        # via the ELB rescale).
        clbs = []
        for page in elb.get_paginator("describe_load_balancers").paginate():
            clbs.extend(page.get("LoadBalancerDescriptions", []))
        for lb in clbs:
            lb_name = lb["LoadBalancerName"]
            created = lb.get("CreatedTime")
            eff_s, eff_e = clamp_window(created, window_start, window_end)
            hrs = hours_between(eff_s, eff_e)
            rate = pricing.elb_rate(session, "classic", region)
            waste = "no instances" if not lb.get("Instances") else None
            rows.append(AttributedResource(
                service="ELB",
                resource_id=lb_name,
                name=lb_name,
                resource_type="classic",
                state="active",
                cost_usd=hrs * rate,
                hours=hrs,
                region=region,
                waste_reason=waste,
                attributes={
                    "scheme": lb.get("Scheme", ""),
                    "vpc_id": lb.get("VPCId", ""),
                    "dns_name": lb.get("DNSName", ""),
                    "instance_count": len(lb.get("Instances", [])),
                    "rate_usd_hr": rate,
                },
            ))
    except ClientError:
        pass

    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
