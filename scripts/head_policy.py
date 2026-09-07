"""A lone stale OR ahead-of-chain endpoint must not pick our fresh common block."""
def select_heads(heads: dict[str, int], max_spread: int = 128) -> dict[str, int]:
    if len(heads) < 2 or any(type(n) is not int or n < 64 for n in heads.values()):
        raise ValueError("INVALID_HEAD_OBSERVATIONS")
    for highest in sorted(set(heads.values()), reverse=True):
        cluster = {name: n for name, n in heads.items() if 0 <= highest - n <= max_spread}
        if len(cluster) >= 2:
            return cluster
    raise ValueError("NO_FRESH_HEAD_QUORUM")
