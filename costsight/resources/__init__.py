"""Per-resource cost attribution.

CE tells us the total for a service; these enumerators break it down to
the individual instance / volume / IP that incurred the cost. For EC2
the split is CE-driven (USAGE_TYPE ground truth scaled across running
hours); for EBS/RDS/EIP/ELB the split is pricing-formula-driven and
reconciled against the CE service total.
"""

from .base import AttributedResource
from .runner import enumerate_all

__all__ = ["AttributedResource", "enumerate_all"]
