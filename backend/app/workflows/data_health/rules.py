"""The seven dimensions as plain rules: same lead in, same score out, no model involved.

Each `score_*` returns (0-100, issues). An issue is {dim, code, field?, message, fix?}; `fix`
is the value a person (or a later write-back) could set. Uniqueness needs the whole database,
so `duplicate_groups` works on every lead at once.
"""

import math
import re
from datetime import UTC, datetime
from typing import Any

# --- master lists ---------------------------------------------------------------------------

_ISO = (
    "AD Andorra|AE United Arab Emirates|AF Afghanistan|AG Antigua and Barbuda|AL Albania|"
    "AM Armenia|AO Angola|AR Argentina|AT Austria|AU Australia|AZ Azerbaijan|"
    "BA Bosnia and Herzegovina|BB Barbados|BD Bangladesh|BE Belgium|BF Burkina Faso|"
    "BG Bulgaria|BH Bahrain|BI Burundi|BJ Benin|BN Brunei|BO Bolivia|BR Brazil|BS Bahamas|"
    "BT Bhutan|BW Botswana|BY Belarus|BZ Belize|CA Canada|CD Democratic Republic of the Congo|"
    "CF Central African Republic|CG Republic of the Congo|CH Switzerland|CI Ivory Coast|"
    "CL Chile|CM Cameroon|CN China|CO Colombia|CR Costa Rica|CU Cuba|CV Cape Verde|CY Cyprus|"
    "CZ Czech Republic|DE Germany|DJ Djibouti|DK Denmark|DM Dominica|DO Dominican Republic|"
    "DZ Algeria|EC Ecuador|EE Estonia|EG Egypt|ER Eritrea|ES Spain|ET Ethiopia|FI Finland|"
    "FJ Fiji|FR France|GA Gabon|GB United Kingdom|GD Grenada|GE Georgia|GH Ghana|GM Gambia|"
    "GN Guinea|GQ Equatorial Guinea|GR Greece|GT Guatemala|GW Guinea-Bissau|GY Guyana|"
    "HK Hong Kong|HN Honduras|HR Croatia|HT Haiti|HU Hungary|ID Indonesia|IE Ireland|"
    "IL Israel|IN India|IQ Iraq|IR Iran|IS Iceland|IT Italy|JM Jamaica|JO Jordan|JP Japan|"
    "KE Kenya|KG Kyrgyzstan|KH Cambodia|KM Comoros|KN Saint Kitts and Nevis|KP North Korea|"
    "KR South Korea|KW Kuwait|KZ Kazakhstan|LA Laos|LB Lebanon|LC Saint Lucia|"
    "LI Liechtenstein|LK Sri Lanka|LR Liberia|LS Lesotho|LT Lithuania|LU Luxembourg|"
    "LV Latvia|LY Libya|MA Morocco|MC Monaco|MD Moldova|ME Montenegro|MG Madagascar|"
    "MK North Macedonia|ML Mali|MM Myanmar|MN Mongolia|MO Macau|MR Mauritania|MT Malta|"
    "MU Mauritius|MV Maldives|MW Malawi|MX Mexico|MY Malaysia|MZ Mozambique|NA Namibia|"
    "NE Niger|NG Nigeria|NI Nicaragua|NL Netherlands|NO Norway|NP Nepal|NZ New Zealand|"
    "OM Oman|PA Panama|PE Peru|PG Papua New Guinea|PH Philippines|PK Pakistan|PL Poland|"
    "PR Puerto Rico|PS Palestine|PT Portugal|PY Paraguay|QA Qatar|RO Romania|RS Serbia|"
    "RU Russia|RW Rwanda|SA Saudi Arabia|SB Solomon Islands|SC Seychelles|SD Sudan|SE Sweden|"
    "SG Singapore|SI Slovenia|SK Slovakia|SL Sierra Leone|SM San Marino|SN Senegal|"
    "SO Somalia|SR Suriname|SS South Sudan|SV El Salvador|SY Syria|SZ Eswatini|TD Chad|"
    "TG Togo|TH Thailand|TJ Tajikistan|TL Timor-Leste|TM Turkmenistan|TN Tunisia|TO Tonga|"
    "TR Turkey|TT Trinidad and Tobago|TW Taiwan|TZ Tanzania|UA Ukraine|UG Uganda|"
    "US United States|UY Uruguay|UZ Uzbekistan|VA Vatican City|VC Saint Vincent and the "
    "Grenadines|VE Venezuela|VN Vietnam|VU Vanuatu|WS Samoa|YE Yemen|ZA South Africa|"
    "ZM Zambia|ZW Zimbabwe"
)
COUNTRY_BY_CODE = {e[:2]: e[3:] for e in _ISO.split("|")}
COUNTRIES = set(COUNTRY_BY_CODE.values())
_COUNTRY_ALIASES = {
    "usa": "United States", "u.s.": "United States", "u.s.a.": "United States",
    "united states of america": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "great britain": "United Kingdom",
    "britain": "United Kingdom", "england": "United Kingdom", "scotland": "United Kingdom",
    "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "deutschland": "Germany", "españa": "Spain", "espana": "Spain", "méxico": "Mexico",
    "brasil": "Brazil", "italia": "Italy", "nederland": "Netherlands", "holland": "Netherlands",
    "the netherlands": "Netherlands", "schweiz": "Switzerland", "suisse": "Switzerland",
    "österreich": "Austria", "danmark": "Denmark", "sverige": "Sweden", "norge": "Norway",
    "suomi": "Finland", "polska": "Poland", "uae": "United Arab Emirates",
    "korea": "South Korea", "republic of korea": "South Korea", "czechia": "Czech Republic",
    "côte d'ivoire": "Ivory Coast", "russian federation": "Russia", "viet nam": "Vietnam",
    "türkiye": "Turkey", "turkiye": "Turkey", "prc": "China", "p.r. china": "China",
}

# LinkedIn-style industries, plus common CRM values.
INDUSTRIES = {
    "Accounting", "Airlines/Aviation", "Automotive", "Aviation & Aerospace", "Banking",
    "Biotechnology", "Chemicals", "Civil Engineering", "Computer Software", "Construction",
    "Consumer Goods", "Defense & Space", "Education", "Electrical/Electronic Manufacturing",
    "Financial Services", "Food & Beverages", "Government", "Hospital & Health Care",
    "Hospitality", "Information Technology and Services", "Insurance", "Legal Services",
    "Leisure, Travel & Tourism", "Logistics and Supply Chain", "Machinery", "Management Consulting",
    "Manufacturing", "Maritime", "Marketing and Advertising", "Media", "Mining & Metals",
    "Non-Profit", "Oil & Energy", "Pharmaceuticals", "Real Estate", "Renewables & Environment",
    "Retail", "Software", "Telecommunications", "Transportation", "Utilities", "Other",
}
_INDUSTRY_ALIASES = {
    "it": "Information Technology and Services", "tech": "Information Technology and Services",
    "technology": "Information Technology and Services", "saas": "Software",
    "healthcare": "Hospital & Health Care", "health care": "Hospital & Health Care",
    "oil and gas": "Oil & Energy", "oil & gas": "Oil & Energy", "energy": "Oil & Energy",
    "aviation": "Aviation & Aerospace", "aerospace": "Aviation & Aerospace",
    "travel": "Leisure, Travel & Tourism", "logistics": "Logistics and Supply Chain",
    "finance": "Financial Services", "mining": "Mining & Metals", "nonprofit": "Non-Profit",
    "not for profit": "Non-Profit", "food and beverage": "Food & Beverages",
}
FREE_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com",
    "msn.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "gmx.com", "gmx.de", "web.de", "proton.me", "protonmail.com", "zoho.com",
    "mail.com", "yandex.com", "yandex.ru", "qq.com", "163.com", "126.com", "naver.com",
}
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "temp-mail.org",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com", "dispostable.com",
    "throwawaymail.com", "maildrop.cc", "fakeinbox.com",
}
_RESERVED_TLDS = {"example", "test", "invalid", "localhost", "local"}
_RESERVED_DOMAINS = {"example.com", "example.org", "example.net", "test.com", "domain.com",
                     "email.com", "abc.com", "xyz.com"}
_FAKE_WORDS = {"test", "testing", "asdf", "asdfg", "qwerty", "xxx", "xx", "x", "aaa", "abc",
               "none", "na", "n/a", "null", "fake", "sample", "dummy", "unknown", "no", "nobody",
               "noreply", "no-reply", "donotreply", "spam", "first", "last", "name", "-", "."}
_FAKE_PAIRS = {("mickey", "mouse"), ("donald", "duck"), ("john", "doe"), ("jane", "doe"),
               ("first", "last"), ("bugs", "bunny"), ("homer", "simpson")}
JUNK_TEXT = {"", "-", ".", "n/a", "na", "none", "null", "asdf", "test", "x", "xxx", "?",
             "unknown"}
ROLE_LOCALS = {"info", "sales", "admin", "support", "contact", "hello", "office", "marketing",
               "team", "enquiries", "inquiries", "billing", "hr", "jobs", "careers"}
_CCTLD = {code.lower(): name for code, name in COUNTRY_BY_CODE.items()} | {"uk": "United Kingdom"}
_CCTLD.pop("us", None)  # .us is rare and often vanity; don't infer from it
_GENERIC_CCTLDS = {"co", "io", "ai", "me", "tv", "ly", "to", "fm", "gg", "sh", "ws"}
_DIAL = {"United States": "1", "Canada": "1", "United Kingdom": "44", "Germany": "49",
         "France": "33", "Spain": "34", "Italy": "39", "Netherlands": "31", "Belgium": "32",
         "Switzerland": "41", "Austria": "43", "Sweden": "46", "Norway": "47", "Denmark": "45",
         "Finland": "358", "Ireland": "353", "Portugal": "351", "Poland": "48",
         "Australia": "61", "New Zealand": "64", "India": "91", "Singapore": "65",
         "Japan": "81", "China": "86", "Hong Kong": "852", "Brazil": "55", "Mexico": "52",
         "South Africa": "27", "United Arab Emirates": "971", "Saudi Arabia": "966",
         "Qatar": "974", "Israel": "972", "Thailand": "66", "Malaysia": "60",
         "Philippines": "63", "Indonesia": "62", "Vietnam": "84", "South Korea": "82"}

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")
_COMPANY_SUFFIX = re.compile(r"\b(inc|incorporated|ltd|limited|llc|plc|gmbh|ag|sa|bv|corp|"
                             r"corporation|co|company|group|holdings)\b\.?", re.I)


# --- small helpers ----------------------------------------------------------------------------


def text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def filled(v: Any) -> bool:
    return text(v).lower() not in JUNK_TEXT if not isinstance(v, bool) else True


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[1].lower() if "@" in email else ""


def name_key(lead: dict[str, Any]) -> str:
    key = re.sub(r"[^a-z]", "", (text(lead.get("firstName")) + text(lead.get("lastName"))).lower())
    return key if len(key) >= 4 else ""


def company_key(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _COMPANY_SUFFIX.sub("", text(v).lower()))


def phone_digits(v: Any) -> str:
    return re.sub(r"\D", "", text(v))


def parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def months_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / (30.44 * 86400)


def standard_country(raw: Any, mapped: dict[str, str] | None = None) -> str | None:
    """The standard name, "" when known to have none, None when unknown."""
    v = text(raw)
    if v in COUNTRIES:
        return v
    low = v.lower()
    if len(v) == 2 and v.upper() in COUNTRY_BY_CODE:
        return COUNTRY_BY_CODE[v.upper()]
    for name in COUNTRIES:
        if name.lower() == low:
            return name
    if low in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[low]
    return (mapped or {}).get(low)


def standard_industry(raw: Any, mapped: dict[str, str] | None = None) -> str | None:
    v = text(raw)
    if v in INDUSTRIES:
        return v
    low = v.lower()
    for name in INDUSTRIES:
        if name.lower() == low:
            return name
    if low in _INDUSTRY_ALIASES:
        return _INDUSTRY_ALIASES[low]
    return (mapped or {}).get(low)


def e164(phone: Any, country: str | None) -> str | None:
    """+<digits> when the number (or its country) says which country it's in."""
    raw, digits = text(phone), phone_digits(phone)
    if not digits:
        return None
    if raw.startswith("+") or raw.startswith("00"):
        digits = digits[2:] if raw.startswith("00") else digits
        return f"+{digits}"
    dial = _DIAL.get(country or "")
    if dial is None:
        return None
    if dial == "1" and len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{dial}{digits.lstrip('0')}"


def phone_problem(phone: Any, country: str | None) -> str | None:
    """Why a phone number can't be right, or None."""
    digits = phone_digits(phone)
    if not digits:
        return "no digits"
    if len(set(digits)) == 1 or digits in "01234567890123456789" or digits in "9876543210":
        return "placeholder digits"
    number = e164(phone, country) or ("+" + digits)
    n = number[1:]
    if n.startswith("1") and (country in (None, "", "United States", "Canada")
                              or text(phone).startswith("+")):
        if len(n) != 11:
            return f"North American numbers have 11 digits with the 1 (this has {len(n)})"
        if n[1] in "01" or n[4] in "01":
            return "not a valid North American area code / exchange"
        if n[4:7] == "555" and n[7:9] == "01":
            return "fictional 555-01xx number"
        return None
    if not 8 <= len(n) <= 15:
        return f"{len(n)} digits; international numbers have 8 to 15"
    return None


# --- context the rules read -----------------------------------------------------------------


class Context:
    """Lookups gathered before scoring: value mappings, DNS results, AI checks, verification
    results and activity aggregates."""

    def __init__(self, *, now: datetime, relevant_fields: list[str], engagement_months: int,
                 corporate_email_required: bool = True,
                 countries: dict[str, str] | None = None,
                 industries: dict[str, str] | None = None,
                 domains: dict[str, bool] | None = None,
                 fake_names: dict[str, bool] | None = None,
                 emails: dict[str, dict] | None = None,
                 phones: dict[str, dict] | None = None,
                 activity: dict[int, dict] | None = None):
        self.now, self.relevant_fields = now, relevant_fields
        self.engagement_months = engagement_months
        self.corporate_email_required = corporate_email_required
        self.countries, self.industries = countries or {}, industries or {}
        self.domains = domains or {}  # domain -> resolves (missing = not checked)
        self.fake_names = fake_names or {}  # name check key -> confirmed fake
        self.emails, self.phones = emails or {}, phones or {}  # paid verification results
        self.activity = activity or {}


def issue(dim: str, code: str, message: str, field: str | None = None,
          fix: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"dim": dim, "code": code, "message": message}
    if field:
        out["field"] = field
    if fix is not None:
        out["fix"] = fix
    return out


def name_check_key(lead: dict[str, Any]) -> str:
    return f"{text(lead.get('firstName')).lower()}|{text(lead.get('lastName')).lower()}"


def name_suspicion(lead: dict[str, Any]) -> str | None:
    """'fake' when a rule is sure, 'suspect' when a person (or the model) should look."""
    first, last = text(lead.get("firstName")).lower(), text(lead.get("lastName")).lower()
    if not first and not last:
        return None
    if first in _FAKE_WORDS or last in _FAKE_WORDS or (first, last) in _FAKE_PAIRS:
        return "fake"
    if re.search(r"\d", first + last) or re.search(r"(.)\1\1", first + last):
        return "fake"
    if (first and first == last) or len(first) == 1 or len(last) == 1:
        return "suspect"
    if re.fullmatch(r"[^aeiouy]{5,}", first) or re.fullmatch(r"[^aeiouy]{5,}", last):
        return "suspect"
    return None


# --- dimensions --------------------------------------------------------------------------------


def score_completeness(lead: dict[str, Any], ctx: Context) -> tuple[int, list[dict]]:
    issues, have = [], 0
    for entry in ctx.relevant_fields:
        alts = entry.split("|")
        if any(filled(lead.get(f)) for f in alts):
            have += 1
            continue
        fix = fill_hint(lead, alts[0])
        issues.append(issue("completeness", "fillable" if fix else "missing",
                            f"{' / '.join(alts)} is empty"
                            + (f"; could be filled with {fix!r} from the email domain"
                               if fix else ""), alts[0], fix))
    total = len(ctx.relevant_fields) or 1
    return round(100 * have / total), issues


def fill_hint(lead: dict[str, Any], field: str) -> str | None:
    """Values derivable from data already on the lead (internal rules, no paid enrichment)."""
    domain = email_domain(text(lead.get("email")))
    if not domain or domain in FREE_DOMAINS or domain.split(".")[-1] in _RESERVED_TLDS:
        return None
    if field == "country":
        tld = domain.rsplit(".", 1)[-1]
        if tld not in _GENERIC_CCTLDS:
            return _CCTLD.get(tld)
    if field == "company":
        label = domain.split(".")[-3] if domain.count(".") >= 2 and domain.split(".")[-2] in (
            "co", "com", "org", "net", "ac") else domain.split(".")[0]
        return label.replace("-", " ").title() if len(label) > 2 else None
    return None


def score_normalization(lead: dict[str, Any], ctx: Context) -> tuple[int, list[dict]]:
    checks, issues = 0, []

    def check(ok: bool, field: str, message: str, fix: Any = None):
        nonlocal checks
        checks += 1
        if not ok:
            issues.append(issue("normalization", f"format_{field}", message, field, fix))

    if filled(lead.get("country")):
        raw = text(lead.get("country"))
        std = standard_country(raw, ctx.countries)
        if std is None or std == "":
            check(False, "country", f"country {raw!r} isn't a recognised country")
        else:
            check(raw == std, "country", f"country {raw!r} should be {std!r}", std)
    if filled(lead.get("industry")):
        raw = text(lead.get("industry"))
        std = standard_industry(raw, ctx.industries)
        if std is None or std == "":
            check(False, "industry", f"industry {raw!r} isn't on the industry list")
        else:
            check(raw == std, "industry", f"industry {raw!r} should be {std!r}", std)
    for f in ("firstName", "lastName"):
        raw = lead.get(f)
        if filled(raw):
            v = str(raw)
            fixed = " ".join(w[:1].upper() + w[1:].lower() if (w.isupper() or w.islower())
                             and len(w) > 1 else w for w in v.split())
            check(v == fixed, f, f"{f} {v!r} should be {fixed!r}", fixed)
    email = lead.get("email")
    if filled(email) and EMAIL_RE.match(text(email)):
        v = str(email)
        check(v == v.strip().lower(), "email", f"email {v!r} should be lowercase, no spaces",
              v.strip().lower())
    for f in ("phone", "mobilePhone"):
        raw = lead.get(f)
        if filled(raw):
            country = standard_country(lead.get("country"), ctx.countries)
            std = e164(raw, country)
            ok = bool(re.fullmatch(r"\+\d{8,15}", text(raw)))
            check(ok, f, f"{f} {text(raw)!r} isn't in international format (+country number)"
                  + (f"; suggested {std}" if std and not ok else ""), std if not ok else None)
    size = lead.get("numberOfEmployees")
    if filled(size):
        check(isinstance(size, int) or text(size).isdigit(), "numberOfEmployees",
              f"numberOfEmployees {text(size)!r} isn't a whole number")
    return (round(100 * (checks - len(issues)) / checks) if checks else 100), issues


def email_problem(lead: dict[str, Any], ctx: Context) -> str | None:
    """Why the email can't be a real, reachable address (accuracy), or None."""
    email = text(lead.get("email")).lower()
    if not EMAIL_RE.match(email):
        return "not a valid email address"
    local, domain = email.rsplit("@", 1)
    if domain.rsplit(".", 1)[-1] in _RESERVED_TLDS or domain in _RESERVED_DOMAINS:
        return f"{domain} is a placeholder domain"
    if domain in DISPOSABLE_DOMAINS:
        return f"{domain} is a disposable mailbox"
    if local in _FAKE_WORDS or re.fullmatch(r"(.)\1{2,}|\d+|asdf\w*|qwer\w*|test\d*", local):
        return f"{local!r} looks like a placeholder"
    if ctx.domains.get(domain) is False:
        return f"{domain} can't receive email (no mail server in DNS)"
    return None


def score_accuracy(lead: dict[str, Any], ctx: Context) -> tuple[int, list[dict]]:
    checks, issues = 0, []

    def check(problem: str | None, field: str, code: str):
        nonlocal checks
        checks += 1
        if problem:
            issues.append(issue("accuracy", code, f"{field}: {problem}", field, ""))

    if filled(lead.get("email")):
        check(email_problem(lead, ctx), "email", "bad_email")
    if text(lead.get("firstName")) or text(lead.get("lastName")):
        s = name_suspicion(lead)
        confirmed = ctx.fake_names.get(name_check_key(lead))
        fake = s == "fake" or (s == "suspect" and confirmed)
        check("looks fake" + (" (confirmed by AI review)" if s == "suspect" else "")
              if fake else None, "name", "fake_name")
    country = standard_country(lead.get("country"), ctx.countries)
    for f in ("phone", "mobilePhone"):
        if filled(lead.get(f)):
            check(phone_problem(lead.get(f), country), f, "bad_phone")
    for f in ("company", "title"):
        if text(lead.get(f)):
            check("placeholder value" if text(lead.get(f)).lower() in JUNK_TEXT | _FAKE_WORDS
                  else None, f, f"junk_{f}")
    return (round(100 * (checks - len(issues)) / checks) if checks else 100), issues


def _flag(lead: dict[str, Any], f: str) -> bool:
    v = lead.get(f)
    return v is True or text(v).lower() in ("true", "1", "yes")


def email_reachability(lead: dict[str, Any], ctx: Context) -> tuple[bool, str]:
    email = text(lead.get("email")).lower()
    if not email:
        return False, "no email"
    if problem := email_problem(lead, ctx):
        return False, problem
    for f, why in (("unsubscribed", "unsubscribed"), ("emailInvalid", "marked email invalid"),
                   ("emailSuspended", "email suspended"), ("blackListed", "blocklisted"),
                   ("marketingSuspended", "marketing suspended")):
        if _flag(lead, f):
            return False, why
    if ctx.activity.get(int(lead["id"]), {}).get("hard_bounces"):
        return False, "hard bounced"
    verified = ctx.emails.get(email)
    if verified is not None and not verified.get("usable"):
        return False, f"verification: {verified.get('status')}"
    return True, ""


def phone_reachability(lead: dict[str, Any], ctx: Context) -> tuple[bool, str]:
    country = standard_country(lead.get("country"), ctx.countries)
    numbers = [lead.get(f) for f in ("phone", "mobilePhone") if filled(lead.get(f))]
    if not numbers:
        return False, "no phone"
    if _flag(lead, "doNotCall"):
        return False, "do not call"
    why = ""
    for n in numbers:
        if problem := phone_problem(n, country):
            why = problem
            continue
        verified = ctx.phones.get(e164(n, country) or "")
        if verified is not None and not verified.get("usable"):
            why = f"verification: {verified.get('status')}"
            continue
        return True, ""
    return False, why


def score_contactability(lead: dict[str, Any], ctx: Context) -> tuple[int, list[dict], dict]:
    email_ok, email_why = email_reachability(lead, ctx)
    phone_ok, phone_why = phone_reachability(lead, ctx)
    free = email_domain(text(lead.get("email"))) in FREE_DOMAINS
    local = text(lead.get("email")).lower().split("@")[0]
    issues = []
    if not email_ok:
        issues.append(issue("contactability", "unreachable_email",
                            f"can't be emailed: {email_why}", "email"))
    elif free:
        issues.append(issue("contactability", "free_email_only",
                            "only a free email address (no corporate email)", "email"))
    elif local in ROLE_LOCALS:
        issues.append(issue("contactability", "role_email",
                            f"{local}@ is a shared role mailbox, not a person", "email"))
    if not phone_ok and phone_why != "no phone":
        issues.append(issue("contactability", "invalid_phone",
                            f"phone can't be used: {phone_why}", "phone"))
    corporate = email_ok and not free
    score = (60 if email_ok else 0) + (25 if phone_ok else 0) + \
        (15 if corporate or (email_ok and not ctx.corporate_email_required) else 0)
    flags = {"email_ok": email_ok, "phone_ok": phone_ok, "free_only": email_ok and free,
             "phone_invalid": not phone_ok and phone_why not in ("no phone", "do not call")}
    return score, issues, flags


def _step(months: float, steps: list[tuple[float, int]]) -> int:
    for limit, value in steps:
        if months <= limit:
            return value
    return 0


def score_recency(lead: dict[str, Any], ctx: Context) -> tuple[int, list[dict]]:
    created = parse_dt(lead.get("createdAt"))
    last = (ctx.activity.get(int(lead["id"])) or {}).get("last_activity_at")
    if last:
        months = months_between(last, ctx.now)
    elif created:
        months = max(months_between(created, ctx.now), 0)
    else:
        return 0, [issue("recency", "no_dates", "no created date or activity")]
    score = _step(months, [(3, 100), (6, 80), (12, 60), (18, 40), (36, 20)])
    issues = []
    if score <= 20:
        since = f"last active {last:%b %Y}" if last else \
            f"no activity in the last {ctx.engagement_months} months"
        issues.append(issue("recency", "stale",
                            f"created {created:%b %Y}, {since}" if created else since))
    return score, issues


def engagement_points(a: dict[str, Any]) -> int:
    return a.get("opens", 0) + 3 * a.get("clicks", 0) + 5 * a.get("forms", 0) + \
        a.get("visits", 0)


def score_engagement(lead: dict[str, Any], ctx: Context) -> tuple[int, str, list[dict]]:
    a = ctx.activity.get(int(lead["id"])) or {}
    last = a.get("last_engaged_at")
    if not last:
        return 0, "dormant", [issue("engagement", "dormant",
                                    f"no opens, clicks, form fills or visits in "
                                    f"{ctx.engagement_months} months")]
    rec = _step(months_between(last, ctx.now), [(1, 100), (3, 80), (6, 60), (12, 40),
                                                (18, 20), (36, 10)]) / 100
    vol = min(1.0, math.log10(1 + engagement_points(a)) / math.log10(51))
    score = round(100 * (0.6 * rec + 0.4 * vol))
    level = "hot" if score >= 60 else "warm" if score >= 30 else "cold" if score > 0 else \
        "dormant"
    return score, level, []


def duplicate_groups(leads: list[dict[str, Any]],
                     completeness: dict[int, int]) -> dict[int, tuple[str, str, str, int]]:
    """{lead_id: (group id, survivor | duplicate, matched on, survivor id)} for every lead
    that shares an email, name + phone, or name + company with another lead. The survivor is
    the most complete record, then the most recently updated."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    matched: dict[int, set[str]] = {}
    buckets: dict[tuple[str, str], list[int]] = {}
    for lead in leads:
        lid = int(lead["id"])
        email = text(lead.get("email")).lower()
        name = name_key(lead)
        if name_suspicion(lead) == "fake":
            name = ""  # "Test Test" placeholders aren't one person
        keys = []
        if EMAIL_RE.match(email):
            keys.append(("email", email))
        digits = phone_digits(lead.get("phone") or lead.get("mobilePhone"))
        if name and len(digits) >= 7:
            keys.append(("name + phone", f"{name}|{digits[-9:]}"))
        company = company_key(lead.get("company"))
        if name and company and company not in JUNK_TEXT:
            keys.append(("name + company", f"{name}|{company}"))
        for k in keys:
            buckets.setdefault(k, []).append(lid)
    for (kind, _), ids in buckets.items():
        if len(ids) < 2:
            continue
        for lid in ids:
            matched.setdefault(lid, set()).add(kind)
            parent[find(lid)] = find(ids[0])
    groups: dict[int, list[int]] = {}
    for lid in matched:
        groups.setdefault(find(lid), []).append(lid)
    by_id = {int(x["id"]): x for x in leads}
    out: dict[int, tuple[str, str, str, int]] = {}
    for members in groups.values():
        def rank(i: int) -> tuple:
            updated = parse_dt(by_id[i].get("updatedAt"))
            return (completeness.get(i, 0), updated.timestamp() if updated else 0, -i)
        survivor = max(members, key=rank)
        gid = f"dup-{min(members)}"
        for lid in members:
            out[lid] = (gid, "survivor" if lid == survivor else "duplicate",
                        ", ".join(sorted(matched[lid])), survivor)
    return out


def score_uniqueness(lead_id: int, groups: dict[int, tuple[str, str, str, int]],
                     sizes: dict[str, int]) -> tuple[int, list[dict]]:
    if lead_id not in groups:
        return 100, []
    gid, role, on, survivor = groups[lead_id]
    if role == "survivor":
        return 70, [issue("uniqueness", "has_duplicates",
                          f"best record of {sizes[gid]} for the same person (matched on {on}); "
                          f"merge the others into it")]
    return 0, [issue("uniqueness", "duplicate",
                     f"duplicate of lead {survivor} (matched on {on})", fix=survivor)]


def overall(scores: dict[str, int], weights: dict[str, float]) -> int:
    total = sum(weights.get(d, 0) for d in scores)
    return round(sum(scores[d] * weights.get(d, 0) for d in scores) / total) if total else 0
