"""Normalisation of URLs, names and tags. Covered by contract/v1/cases/normalize."""
import ipaddress
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "_ga", "playsessionid", "listenerid", "userid", "user_hash",
    "uid", "amsparams", "aggregator", "aw_0_1st.playerid", "origine", "origem",
    "ref", "referer", "referrer",
})
# Other directories: their redirects, pages and images are not the station's own.
THIRD_PARTY_DIRECTORIES = (
    "radio.garden", "streema.com", "tunein.com", "radioguide.fm", "onlineradiobox.com",
    "liveonlineradio.net", "mytuner-radio.com",
)
PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".arpa")
TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
QUALITY_SUFFIX = re.compile(
    r"\s*[\(\[][^\)\]]*\b(?:aac|mp3|ogg|opus|flac|hifi|midfi|lofi|kbps|\d+\s?k)\b[^\)\]]*[\)\]]\s*$",
    re.IGNORECASE,
)
CHANNEL_NOISE = re.compile(
    r"hifi|midfi|lofi|aacp?|mp3|ogg|opus|flac|stream|listen|live|icecast|audio|radio|\d+k?|[^a-z0-9]"
)
SECOND_LEVEL = frozenset({"co", "com", "org", "net", "ac", "gov", "edu", "or", "ne"})


def is_public_host(host):
    """False for loopback, private, link-local and other non-routable hosts."""
    host = (host or "").strip("[]").lower().rstrip(".")
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if host == "localhost" or host.endswith(PRIVATE_SUFFIXES):
        return False
    labels = host.split(".")
    return len(labels) >= 2 and bool(TLD.match(labels[-1]))


def is_third_party_directory(host):
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in THIRD_PARTY_DIRECTORIES)


def web_url(raw):
    """Return a clean public http(s) URL, or None when it must be refused."""
    raw = (raw or "").strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    if parts.username or parts.password or not is_public_host(parts.hostname):
        return None
    if is_third_party_directory(parts.hostname):
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    default = {"http": 80, "https": 443}[scheme]
    netloc = host if port in (None, default) else f"{host}:{port}"
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit((scheme, netloc, parts.path, urlencode(query), ""))


def stream_key(url):
    """Identity of a stream: the same address over http and https is one stream."""
    return re.sub(r"^https?://", "", url).rstrip("/;")


def stream_protocol(url):
    path = urlsplit(url).path.lower()
    if path.endswith(".m3u8"):
        return "hls"
    if path.endswith(".mpd"):
        return "dash"
    return "http"


def stream_channel(url):
    """Channel named by the path, without quality words: fip_hifi.m3u8 gives fip."""
    segments = [s for s in urlsplit(url).path.lower().split("/") if s]
    if not segments:
        return ""
    return CHANNEL_NOISE.sub("", segments[-1].rsplit(".", 1)[0])


def registrable_domain(url):
    """Approximate registrable domain, or None for an IP address."""
    host = urlsplit(url).hostname or ""
    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def clean_name(raw):
    """Display name: no control characters, single spaces, no quality suffix."""
    text = "".join(c for c in (raw or "") if unicodedata.category(c)[0] != "C")
    text = re.sub(r"\s+", " ", text).strip()
    return QUALITY_SUFFIX.sub("", text).strip()[:200]


def name_key(raw):
    """Comparison key, for every script: letters and digits, case folded."""
    text = unicodedata.normalize("NFKC", clean_name(raw)).casefold()
    return "".join(c for c in text if unicodedata.category(c)[0] in "LN")
