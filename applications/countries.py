"""Countries and telephone calling codes for the request form (parity track 034 row 3; bead catalyst-v2-bgl.3).

The country of residence is stored as its ISO 3166-1 alpha-2 code and the phone number in E.164 form (`+` and 8 to
15 digits), so neither depends on a display language or a formatting habit. The table below is the ISO 3166-1
assigned set (249 codes) with each territory's ITU-T E.164 calling code, kept here as data rather than taken from a
library: the dependency set is hash-locked and has no country or phone package, and nothing here needs more than a
lookup. Shared codes (`1` for the North American plan, `7`, `44`, `47`, `61`, `262`, `590`, `599`, `672`) are
real: a number is checked against the calling code of the country the applicant chose, never the other way round.

`normalize_phone` is pure and offline: no carrier lookup, no external service (the form must never call out). It
accepts the ways people type a number (spaces, dots, hyphens, parentheses, a `+` or `00` prefix, or the national form
for the chosen country) and refuses anything it cannot read as one number for that country.
"""

import re

# (ISO 3166-1 alpha-2, English short name, E.164 calling code without the plus)
COUNTRIES = (
    ("AD", "Andorra", "376"), ("AE", "United Arab Emirates", "971"), ("AF", "Afghanistan", "93"),
    ("AG", "Antigua and Barbuda", "1"), ("AI", "Anguilla", "1"), ("AL", "Albania", "355"), ("AM", "Armenia", "374"),
    ("AO", "Angola", "244"), ("AQ", "Antarctica", "672"), ("AR", "Argentina", "54"), ("AS", "American Samoa", "1"),
    ("AT", "Austria", "43"), ("AU", "Australia", "61"), ("AW", "Aruba", "297"), ("AX", "Åland Islands", "358"),
    ("AZ", "Azerbaijan", "994"), ("BA", "Bosnia and Herzegovina", "387"), ("BB", "Barbados", "1"),
    ("BD", "Bangladesh", "880"), ("BE", "Belgium", "32"), ("BF", "Burkina Faso", "226"), ("BG", "Bulgaria", "359"),
    ("BH", "Bahrain", "973"), ("BI", "Burundi", "257"), ("BJ", "Benin", "229"), ("BL", "Saint Barthélemy", "590"),
    ("BM", "Bermuda", "1"), ("BN", "Brunei Darussalam", "673"), ("BO", "Bolivia", "591"),
    ("BQ", "Bonaire, Sint Eustatius and Saba", "599"), ("BR", "Brazil", "55"), ("BS", "Bahamas", "1"),
    ("BT", "Bhutan", "975"), ("BV", "Bouvet Island", "47"), ("BW", "Botswana", "267"), ("BY", "Belarus", "375"),
    ("BZ", "Belize", "501"), ("CA", "Canada", "1"), ("CC", "Cocos (Keeling) Islands", "61"),
    ("CD", "Congo, Democratic Republic of the", "243"), ("CF", "Central African Republic", "236"),
    ("CG", "Congo", "242"), ("CH", "Switzerland", "41"), ("CI", "Côte d'Ivoire", "225"), ("CK", "Cook Islands", "682"),
    ("CL", "Chile", "56"), ("CM", "Cameroon", "237"), ("CN", "China", "86"), ("CO", "Colombia", "57"),
    ("CR", "Costa Rica", "506"), ("CU", "Cuba", "53"), ("CV", "Cabo Verde", "238"), ("CW", "Curaçao", "599"),
    ("CX", "Christmas Island", "61"), ("CY", "Cyprus", "357"), ("CZ", "Czechia", "420"), ("DE", "Germany", "49"),
    ("DJ", "Djibouti", "253"), ("DK", "Denmark", "45"), ("DM", "Dominica", "1"), ("DO", "Dominican Republic", "1"),
    ("DZ", "Algeria", "213"), ("EC", "Ecuador", "593"), ("EE", "Estonia", "372"), ("EG", "Egypt", "20"),
    ("EH", "Western Sahara", "212"), ("ER", "Eritrea", "291"), ("ES", "Spain", "34"), ("ET", "Ethiopia", "251"),
    ("FI", "Finland", "358"), ("FJ", "Fiji", "679"), ("FK", "Falkland Islands (Malvinas)", "500"),
    ("FM", "Micronesia, Federated States of", "691"), ("FO", "Faroe Islands", "298"), ("FR", "France", "33"),
    ("GA", "Gabon", "241"), ("GB", "United Kingdom", "44"), ("GD", "Grenada", "1"), ("GE", "Georgia", "995"),
    ("GF", "French Guiana", "594"), ("GG", "Guernsey", "44"), ("GH", "Ghana", "233"), ("GI", "Gibraltar", "350"),
    ("GL", "Greenland", "299"), ("GM", "Gambia", "220"), ("GN", "Guinea", "224"), ("GP", "Guadeloupe", "590"),
    ("GQ", "Equatorial Guinea", "240"), ("GR", "Greece", "30"),
    ("GS", "South Georgia and the South Sandwich Islands", "500"), ("GT", "Guatemala", "502"), ("GU", "Guam", "1"),
    ("GW", "Guinea-Bissau", "245"), ("GY", "Guyana", "592"), ("HK", "Hong Kong", "852"),
    ("HM", "Heard Island and McDonald Islands", "672"), ("HN", "Honduras", "504"), ("HR", "Croatia", "385"),
    ("HT", "Haiti", "509"), ("HU", "Hungary", "36"), ("ID", "Indonesia", "62"), ("IE", "Ireland", "353"),
    ("IL", "Israel", "972"), ("IM", "Isle of Man", "44"), ("IN", "India", "91"),
    ("IO", "British Indian Ocean Territory", "246"), ("IQ", "Iraq", "964"), ("IR", "Iran", "98"),
    ("IS", "Iceland", "354"), ("IT", "Italy", "39"), ("JE", "Jersey", "44"), ("JM", "Jamaica", "1"),
    ("JO", "Jordan", "962"), ("JP", "Japan", "81"), ("KE", "Kenya", "254"), ("KG", "Kyrgyzstan", "996"),
    ("KH", "Cambodia", "855"), ("KI", "Kiribati", "686"), ("KM", "Comoros", "269"),
    ("KN", "Saint Kitts and Nevis", "1"), ("KP", "Korea, Democratic People's Republic of", "850"),
    ("KR", "Korea, Republic of", "82"), ("KW", "Kuwait", "965"), ("KY", "Cayman Islands", "1"),
    ("KZ", "Kazakhstan", "7"), ("LA", "Lao People's Democratic Republic", "856"), ("LB", "Lebanon", "961"),
    ("LC", "Saint Lucia", "1"), ("LI", "Liechtenstein", "423"), ("LK", "Sri Lanka", "94"), ("LR", "Liberia", "231"),
    ("LS", "Lesotho", "266"), ("LT", "Lithuania", "370"), ("LU", "Luxembourg", "352"), ("LV", "Latvia", "371"),
    ("LY", "Libya", "218"), ("MA", "Morocco", "212"), ("MC", "Monaco", "377"), ("MD", "Moldova", "373"),
    ("ME", "Montenegro", "382"), ("MF", "Saint Martin (French part)", "590"), ("MG", "Madagascar", "261"),
    ("MH", "Marshall Islands", "692"), ("MK", "North Macedonia", "389"), ("ML", "Mali", "223"),
    ("MM", "Myanmar", "95"), ("MN", "Mongolia", "976"), ("MO", "Macao", "853"),
    ("MP", "Northern Mariana Islands", "1"), ("MQ", "Martinique", "596"), ("MR", "Mauritania", "222"),
    ("MS", "Montserrat", "1"), ("MT", "Malta", "356"), ("MU", "Mauritius", "230"), ("MV", "Maldives", "960"),
    ("MW", "Malawi", "265"), ("MX", "Mexico", "52"), ("MY", "Malaysia", "60"), ("MZ", "Mozambique", "258"),
    ("NA", "Namibia", "264"), ("NC", "New Caledonia", "687"), ("NE", "Niger", "227"), ("NF", "Norfolk Island", "672"),
    ("NG", "Nigeria", "234"), ("NI", "Nicaragua", "505"), ("NL", "Netherlands", "31"), ("NO", "Norway", "47"),
    ("NP", "Nepal", "977"), ("NR", "Nauru", "674"), ("NU", "Niue", "683"), ("NZ", "New Zealand", "64"),
    ("OM", "Oman", "968"), ("PA", "Panama", "507"), ("PE", "Peru", "51"), ("PF", "French Polynesia", "689"),
    ("PG", "Papua New Guinea", "675"), ("PH", "Philippines", "63"), ("PK", "Pakistan", "92"), ("PL", "Poland", "48"),
    ("PM", "Saint Pierre and Miquelon", "508"), ("PN", "Pitcairn", "64"), ("PR", "Puerto Rico", "1"),
    ("PS", "Palestine, State of", "970"), ("PT", "Portugal", "351"), ("PW", "Palau", "680"), ("PY", "Paraguay", "595"),
    ("QA", "Qatar", "974"), ("RE", "Réunion", "262"), ("RO", "Romania", "40"), ("RS", "Serbia", "381"),
    ("RU", "Russian Federation", "7"), ("RW", "Rwanda", "250"), ("SA", "Saudi Arabia", "966"),
    ("SB", "Solomon Islands", "677"), ("SC", "Seychelles", "248"), ("SD", "Sudan", "249"), ("SE", "Sweden", "46"),
    ("SG", "Singapore", "65"), ("SH", "Saint Helena, Ascension and Tristan da Cunha", "290"),
    ("SI", "Slovenia", "386"), ("SJ", "Svalbard and Jan Mayen", "47"), ("SK", "Slovakia", "421"),
    ("SL", "Sierra Leone", "232"), ("SM", "San Marino", "378"), ("SN", "Senegal", "221"), ("SO", "Somalia", "252"),
    ("SR", "Suriname", "597"), ("SS", "South Sudan", "211"), ("ST", "Sao Tome and Principe", "239"),
    ("SV", "El Salvador", "503"), ("SX", "Sint Maarten (Dutch part)", "1"), ("SY", "Syrian Arab Republic", "963"),
    ("SZ", "Eswatini", "268"), ("TC", "Turks and Caicos Islands", "1"), ("TD", "Chad", "235"),
    ("TF", "French Southern Territories", "262"), ("TG", "Togo", "228"), ("TH", "Thailand", "66"),
    ("TJ", "Tajikistan", "992"), ("TK", "Tokelau", "690"), ("TL", "Timor-Leste", "670"),
    ("TM", "Turkmenistan", "993"), ("TN", "Tunisia", "216"), ("TO", "Tonga", "676"), ("TR", "Türkiye", "90"),
    ("TT", "Trinidad and Tobago", "1"), ("TV", "Tuvalu", "688"), ("TW", "Taiwan", "886"), ("TZ", "Tanzania", "255"),
    ("UA", "Ukraine", "380"), ("UG", "Uganda", "256"), ("UM", "United States Minor Outlying Islands", "1"),
    ("US", "United States of America", "1"), ("UY", "Uruguay", "598"), ("UZ", "Uzbekistan", "998"),
    ("VA", "Holy See", "39"), ("VC", "Saint Vincent and the Grenadines", "1"), ("VE", "Venezuela", "58"),
    ("VG", "Virgin Islands (British)", "1"), ("VI", "Virgin Islands (U.S.)", "1"), ("VN", "Viet Nam", "84"),
    ("VU", "Vanuatu", "678"), ("WF", "Wallis and Futuna", "681"), ("WS", "Samoa", "685"), ("YE", "Yemen", "967"),
    ("YT", "Mayotte", "262"), ("ZA", "South Africa", "27"), ("ZM", "Zambia", "260"), ("ZW", "Zimbabwe", "263"),
)
NAMES = {code: name for code, name, _ in COUNTRIES}
CALLING_CODES = {code: calling for code, _, calling in COUNTRIES}
CODES = frozenset(NAMES)
E164_MIN_DIGITS, E164_MAX_DIGITS = 8, 15
_TYPED = re.compile(r"\+?[0-9 ().\-]+")


def choices():
    """Select options sorted by name, each value the ISO code."""
    return sorted(((code, name) for code, name, _ in COUNTRIES), key=lambda pair: pair[1].casefold())


def phone_choices():
    """Select options for the phone's country, each labelled with its calling code."""
    return [(code, f"{name} (+{CALLING_CODES[code]})") for code, name in choices()]


def name(code: str) -> str:
    return NAMES.get(code, code)


def normalize_phone(raw: str, country: str) -> str:
    """The E.164 form of a typed number for `country` (an ISO code in CODES), or ValueError with a reason code:
    `characters` (not a phone number), `international` (no `+` or `00` prefix outside the North American plan,
    where a trunk prefix cannot be told from the number), `country` (the number carries another country's calling
    code) or `length` (outside 8 to 15 digits, or too short to carry a number after the calling code).

    A national-format number is read only for a North American plan country (ten digits, or eleven with the trunk
    `1`): elsewhere the trunk prefix is country-specific (Italy keeps its `0`, most countries drop it), so guessing
    would store a wrong number silently; the applicant is asked for the international form instead."""
    text = " ".join((raw or "").split())
    if not text or not _TYPED.fullmatch(text) or text.count("+") > 1:
        raise ValueError("characters")
    calling = CALLING_CODES[country]
    digits = re.sub(r"\D", "", text)
    international = text.startswith("+")
    if not international and digits.startswith("00"):
        digits, international = digits[2:], True
    if international:
        if not digits.startswith(calling):
            raise ValueError("country")
        national = digits[len(calling):]
    elif calling == "1":
        national = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
        if len(national) != 10 or national.startswith(("0", "1")):
            raise ValueError("length")
    else:
        raise ValueError("international")
    digits = calling + national
    if len(national) < 4 or not E164_MIN_DIGITS <= len(digits) <= E164_MAX_DIGITS:
        raise ValueError("length")
    return "+" + digits
