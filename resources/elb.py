"""Load balancer enumerator (ALB, NLB, Gateway, Classic)."""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.exceptions import ClientError

import pricing

from .base import REGION, Resource, ResourceCost, clamp_window, hours_between, tags_to_dict


def enumerate_elb(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
) -> list[ResourceCost]:
    rows: list[ResourceCost] = []

    # ALB / NLB / Gateway
    elbv2 = session.client("elbv2", region_name=REGION)
    try:
        lbs = []
        paginator = elbv2.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            lbs.extend(page.get("LoadBalancers", []))

        tag_map = {}
        if lbs:
            arns = [lb["LoadBalancerArn"] for lb in lbs]
            # API accepts max 20 arns per call
            for i in range(0, len(arns), 20):
                resp = elbv2.describe_tags(ResourceArns=arns[i:i + 20])
                for td in resp.get("TagDescriptions", []):
                    tag_map[td["ResourceArn"]] = tags_to_dict(td.get("Tags"))

        # Count healthy targets per LB to flag "no targets"
        healthy_by_lb = {}
        try:
            tg_paginator = elbv2.get_paginator("describe_target_groups")
            for page in tg_paginator.paginate():
                for tg in page.get("TargetGroups", []):
                    for lb_arn in tg.get("LoadBalancerArns", []):
                        health = elbv2.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
                        healthy = sum(
                            1 for t in health.get("TargetHealthDescriptions", [])
                            if t.get("TargetHealth", {}).get("State") == "healthy"
                        )
                        healthy_by_lb[lb_arn] = healthy_by_lb.get(lb_arn, 0) + healthy
        except ClientError:
            pass

        for lb in lbs:
            lb_arn = lb["LoadBalancerArn"]
            lb_name = lb["LoadBalancerName"]
            lb_type = lb.get("Type", "application")
            state = lb.get("State", {}).get("Code", "unknown")
            created = lb.get("CreatedTime")
            tags = tag_map.get(lb_arn, {})

            eff_start, eff_end = clamp_window(created, window_start, window_end)
            hours = hours_between(eff_start, eff_end)
            rate = pricing.elb_rate(session, lb_type, REGION)
            raw = hours * rate

            healthy = healthy_by_lb.get(lb_arn, 0)
            waste = "no healthy targets" if lb_arn in healthy_by_lb and healthy == 0 else None

            resource = Resource(
                arn=lb_arn,
                service="ELB",
                resource_id=lb_name,
                name=tags.get("Name", lb_name),
                type=lb_type,
                state=state,
                attributes={
                    "scheme": lb.get("Scheme", ""),
                    "vpc_id": lb.get("VpcId", ""),
                    "dns_name": lb.get("DNSName", ""),
                    "healthy_targets": healthy,
                },
                tags=tags,
            )
            rows.append(
                ResourceCost(
                    resource=resource,
                    cost=raw,
                    raw_cost=raw,
                    usage={"hours": round(hours, 2), "rate_usd_hr": rate},
                    waste_reason=waste,
                )
            )
    except ClientError:
        pass

    # Classic ELB
    try:
        elb = session.client("elb", region_name=REGION)
        clbs = elb.describe_load_balancers().get("LoadBalancerDescriptions", [])
        for lb in clbs:
            lb_name = lb["LoadBalancerName"]
            created = lb.get("CreatedTime")
            eff_start, eff_end = clamp_window(created, window_start, window_end)
            hours = hours_between(eff_start, eff_end)
            rate = pricing.elb_rate(session, "classic", REGION)
            raw = hours * rate

            resource = Resource(
                arn=f"arn:aws:elasticloadbalancing:{REGION}::loadbalancer/{lb_name}",
                service="ELB",
                resource_id=lb_name,
                name=lb_name,
                type="classic",
                state="active",
                attributes={
                    "scheme": lb.get("Scheme", ""),
                    "vpc_id": lb.get("VPCId", ""),
                    "dns_name": lb.get("DNSName", ""),
                    "instance_count": len(lb.get("Instances", [])),
                },
                tags={},
            )
            waste = "no instances" if not lb.get("Instances") else None
            rows.append(
                ResourceCost(
                    resource=resource,
                    cost=raw,
                    raw_cost=raw,
                    usage={"hours": round(hours, 2), "rate_usd_hr": rate},
                    waste_reason=waste,
                )
            )
    except ClientError:
        pass

    return rows
