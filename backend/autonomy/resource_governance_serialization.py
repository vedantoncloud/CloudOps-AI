from dataclasses import asdict

from autonomy.resource_governance_summary import ResourceGovernanceSummary


def serialize_governance_summary(
    summary: ResourceGovernanceSummary,
) -> dict:
    return asdict(summary)
