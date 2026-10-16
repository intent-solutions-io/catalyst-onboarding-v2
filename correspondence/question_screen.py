"""The screen every applicant-specific question passes before it can exist (018 section 5.3 and 15; 019 section 5;
P3 3B.2 and 3B.3). One screen for model-proposed and staff-authored questions alike: no link, contact detail,
markup or control character, no request for credentials, personal data or confidential material, English only.
It fails closed: legitimate technical wording ("token", "wallet") may be refused; staff then rephrase.

`assessments` imports these patterns (for its output checks and its scrubbing); `correspondence` never imports
`assessments` (003 ADR-01).
"""

import re
import unicodedata

EMAIL = re.compile(r"(?:mailto:)?[\w.+-]{1,64}\s*(?:@|\(at\)|\[at\]|\s+at\s+)\s*[\w-]{1,63}"
                   r"(?:\s*(?:\.|\(dot\)|\[dot\]|\s+dot\s+)\s*[\w-]{1,63}){1,6}", re.I)
UNSAFE_TEXT = re.compile(
    r"https?://|www\.|mailto:|javascript:|data:|\]\(|<[a-z/!?]|@|\b[a-z0-9-]+\.(com|org|net|io|dev|app|ai|co|ly|me|sh|fr|ca|in|us|eu|tv|cloud|tech|test)\b",
    re.I)
NUMBER = re.compile(r"\+?\d[\d ()./-]{6,24}\d")
REFUSED_QUESTION = re.compile(
    r"\b(pass(word|phrase|code)\w*|credential\w*|log-?in\w*|sign-?in\w*|api[ _-]?keys?|ssh[ _-]?keys?|private[ _-]?keys?"
    r"|tokens?|secrets?|seed[ _-]?phrases?|recovery[ _-]?(codes?|phrases?)|pins?|2fa|mfa|one-?time[ _-]?codes?|otp"
    r"|wallets?|bank\w*|account[ _-]?numbers?|card[ _-]?numbers?|salar\w*|income|ssn|social security"
    r"|passports?|driv\w*[ _-]?licen[cs]e|national[ _-]?id|id[ _-]?(cards?|documents?)|identity[ _-]?documents?"
    r"|date[ _-]?of[ _-]?birth|birth\w*|age|how old|nationalit\w*|citizenship|religio\w*|health|medical|disabilit\w*"
    r"|pregnan\w*|famil\w*|married|marital|children|home[ _-]?address|address|phone|ethnic\w*|race|sexual\w*"
    r"|source[ _-]?code|customer[ _-]?(lists?|data|names?)|client[ _-]?(data|secrets?|names?|lists?)|confidential\w*"
    r"|nda|contracts?|proprietary|pass[ _-]?words?|credit[ _-]?cards?|cvv|visas?|immigration\w*|gender\w*"
    r"|politic\w*|union\w*|criminal\w*|tax\w*)\b", re.I)
_TYPOGRAPHY = str.maketrans("‘’“”–—", "''\"\"--")


def unsafe(text: str) -> bool:
    """A link, contact detail, markup or control character in free text."""
    phone = any(sum(ch.isdigit() for ch in m.group(0)) >= 9 for m in NUMBER.finditer(text))  # not a year range
    return phone or bool(UNSAFE_TEXT.search(text)) or any(
        unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs") for ch in text if ch not in "\n\t")


def question_problems(text: str) -> list[str]:
    """Reason codes; empty means the question may be stored for approval."""
    if not text.strip():
        return ["question_empty"]
    if unsafe(text) or EMAIL.search(text) or REFUSED_QUESTION.search(text) or not text.translate(_TYPOGRAPHY).isascii():
        return ["question_refused"]
    return []


def text_key(text: str) -> str:
    """The normalized form used to deduplicate questions per application (018 section 4 step 5)."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w]+", " ", folded).strip()
