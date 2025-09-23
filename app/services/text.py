import logging
log = logging.getLogger("erp_ai.text")

def flatten_text(di_json: dict) -> str:
    try:
        ar = di_json.get("analyzeResult", {})
        docs = ar.get("documents", []) or []
        lines = []
        for d in docs:
            fields = d.get("fields", {}) or {}
            for k, v in fields.items():
                if isinstance(v, dict) and v.get("content"):
                    lines.append(f"{k}: {v['content']}")
        for page in ar.get("pages", []) or []:
            for line in page.get("lines", []) or []:
                if line.get("content"):
                    lines.append(line["content"])
        return "\n".join(lines).strip()
    except Exception as e:
        log.exception("flatten_text failed: %s", e)
        return ""
