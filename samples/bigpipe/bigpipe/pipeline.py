"""A deliberately large single-function module: ``normalize`` has one body that
exceeds a modest rebuild byte budget, exercising decompose -> reconstruct ->
recompose. The body is a long sequential pipeline over one carry variable, so
each contiguous segment is independently reconstructable and the recomposed
function is behaviorally identical to the original."""


def normalize(text: str) -> str:
    s = text
    s = s.strip()
    s = s.lower()
    s = s.replace("\t", " ")
    s = s.replace("\r", " ")
    s = s.replace("\n", " ")
    s = s.replace("_", " ")
    s = s.replace("-", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    parts = s.split(" ")
    parts = [p for p in parts if p]
    cleaned = []
    for p in parts:
        q = "".join(ch for ch in p if ch.isalnum())
        if q:
            cleaned.append(q)
    parts = cleaned
    s = " ".join(parts)
    s = s.replace(" .", ".")
    s = s.replace(" ,", ",")
    words = s.split(" ")
    words = [w for w in words if w]
    titled = []
    for w in words:
        if len(w) > 2:
            titled.append(w[0].upper() + w[1:])
        else:
            titled.append(w)
    s = " ".join(titled)
    if not s:
        return ""
    if not s.endswith("."):
        s = s + "."
    s = s[0].upper() + s[1:]
    return s
