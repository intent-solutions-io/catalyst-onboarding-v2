"""Cumulative usage quotas; None explicitly means unlimited, zero means no allowance."""


def exceeds(value: int, limit: int | None) -> bool:
    return limit is not None and value > limit
