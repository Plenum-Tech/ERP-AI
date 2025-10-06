from typing import Any, Dict, List

def kv(value_obj: Any) -> Dict[str, Any]:
    """Return sample-like dict: {'value': <typed value>, 'confidence': <float>}"""
    if value_obj is None:
        return {"value": None, "confidence": None}
    val = getattr(value_obj, "value", None)
    conf = getattr(value_obj, "confidence", None)
    # fallback for legacy convenience getters if present
    if val is None:
        for attr in ("value_string", "value_number", "value_currency", "value_address", "value_date"):
            if hasattr(value_obj, attr):
                val = getattr(value_obj, attr)
                break
    if hasattr(val, "amount"):  # unwrap currency
        val = getattr(val, "amount", val)
    return {"value": val, "confidence": conf}

def print_kv(label: str, obj: Any):
    k = kv(obj)
    if k["value"] is not None:
        print(f"{label}: {k['value']} (conf: {k['confidence']})")

def items_from_array(field_obj: Any) -> List[dict]:
    """Turn a DI array of object fields into a list of {key:{value,confidence}} dicts."""
    out: List[dict] = []
    if not field_obj or not getattr(field_obj, "value", None):
        return out
    for it in field_obj.value:
        props = getattr(it, "properties", {}) or {}
        out.append({k: kv(v) for k, v in props.items()})
    return out
