"""Display of untrusted text on the staff screens (016 section 6; 2B.4 M9). Autoescaping stays on; this filter
additionally turns every control or format character (bidirectional overrides and isolates, zero-width
characters, U+061C, U+FEFF, NUL and other C0/C1 controls) into a visible marker such as [U+202E], so hostile
mail can neither reorder the page nor hide text, and staff see that the character was there. Newlines and
tabs are kept."""

import unicodedata

from django import template

register = template.Library()


@register.filter
def visible(text) -> str:
    out = []
    for ch in str(text or ""):
        if ch in "\n\t":
            out.append(ch)
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp") or (
                unicodedata.category(ch) == "Zs" and ch != " ") or ch in "\u115f\u1160\u3164\u2800\uffa0":
            out.append(f"[U+{ord(ch):04X}]")
        else:
            out.append(ch)
    return "".join(out)  # still a plain str: the template engine escapes it
