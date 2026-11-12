"""Canonical hashing for reproducibility (params_hash / input_hash)."""
import hashlib
import json
import math


def _clean(o):
    if isinstance(o, float):
        return None if math.isnan(o) else round(o, 10)
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in sorted(o.items())}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def stable_hash(obj) -> str:
    payload = json.dumps(_clean(obj), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
