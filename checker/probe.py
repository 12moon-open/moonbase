"""Probe one stream: reach it, read a few seconds at most, describe what it sends.

Nothing is recorded or kept: the bytes read are described by ffprobe from memory,
then dropped. A now-playing title is only detected, never stored.

Every address is untrusted. Each host is resolved here and refused unless every
address is public; the connection goes to the checked address, so a second DNS
answer cannot point it elsewhere. Redirects and playlists are checked the same way.
"""
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import time
from urllib.parse import urljoin, urlsplit

USER_AGENT = "12moon-checker/1.0 (+https://github.com/12moon-open/moonbase)"
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 8
MAX_HEADER = 16 * 1024
MAX_BODY = 96 * 1024  # About 5 s of 128 kbit/s audio.
MAX_PLAYLIST = 64 * 1024
MAX_SEGMENT = 256 * 1024
MAX_HOPS = 5
READ_WINDOW = 4.0  # Seconds of audio read after the first byte, at most.

PLAYLIST_TYPES = ("mpegurl", "x-scpls", "pls", "m3u")


class Failure(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def _public_addresses(host, port):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise Failure("dns", str(error)) from None
    addresses = []
    for family, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise Failure("private_address")
        addresses.append((family, sockaddr))
    if not addresses:
        raise Failure("dns")
    return addresses


class Response:
    def __init__(self, status, headers, sock, started, ttfb):
        self.status, self.headers, self.sock = status, headers, sock
        self.started, self.ttfb_ms = started, ttfb

    def read(self, limit, window=None):
        chunks, size = [], 0
        deadline = time.monotonic() + window if window else None
        try:
            while size < limit:
                if deadline and time.monotonic() > deadline:
                    break
                data = self.sock.recv(min(16384, limit - size))
                if not data:
                    break
                chunks.append(data)
                size += len(data)
        except (socket.timeout, OSError):
            if not chunks:
                raise Failure("read_timeout") from None
        return b"".join(chunks)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _get(url, allow_private=False):
    """One GET over a socket we open ourselves. Accepts ICY status lines."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise Failure("bad_url")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if allow_private:
        addresses = [(f, s) for f, _, _, _, s in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)]
    else:
        addresses = _public_addresses(parts.hostname, port)
    family, sockaddr = addresses[0]
    started = time.monotonic()
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        sock.connect(sockaddr)
    except OSError:
        sock.close()
        raise Failure("connect") from None
    if parts.scheme == "https":
        context = ssl.create_default_context()
        try:
            sock = context.wrap_socket(sock, server_hostname=parts.hostname)
        except ssl.SSLCertVerificationError:
            sock.close()
            raise Failure("tls_invalid") from None
        except (ssl.SSLError, OSError):
            sock.close()
            raise Failure("tls") from None
    sock.settimeout(READ_TIMEOUT)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    request = (
        f"GET {target} HTTP/1.0\r\nHost: {host}\r\nUser-Agent: {USER_AGENT}\r\n"
        "Accept: */*\r\nIcy-MetaData: 1\r\nConnection: close\r\n\r\n"
    )
    try:
        sock.sendall(request.encode("ascii", "strict"))
        raw = b""
        while b"\r\n\r\n" not in raw and b"\n\n" not in raw:
            data = sock.recv(4096)
            if not data:
                break
            raw += data
            if len(raw) > MAX_HEADER:
                raise Failure("bad_response")
    except (socket.timeout, OSError, UnicodeEncodeError):
        sock.close()
        raise Failure("read_timeout") from None
    ttfb = round((time.monotonic() - started) * 1000)
    separator = b"\r\n\r\n" if b"\r\n\r\n" in raw else b"\n\n"
    head, _, rest = raw.partition(separator)
    lines = head.decode("latin-1").splitlines()
    match = re.match(r"^(?:HTTP/\d(?:\.\d)?|ICY)\s+(\d{3})", lines[0] if lines else "")
    if not match:
        sock.close()
        raise Failure("bad_response")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    response = Response(int(match.group(1)), headers, sock, started, ttfb)
    response.leftover = rest
    return response


def _fetch(url, limit, window=None, allow_private=False, hops=None):
    """GET with checked redirects. Returns (final_url, response, body)."""
    hops = hops if hops is not None else []
    while True:
        response = _get(url, allow_private)
        if response.status in (301, 302, 303, 307, 308) and "location" in response.headers:
            response.close()
            if len(hops) >= MAX_HOPS:
                raise Failure("too_many_redirects")
            url = urljoin(url, response.headers["location"])
            hops.append(url)
            continue
        if response.status != 200:
            response.close()
            raise Failure("http_error", str(response.status))
        body = response.leftover + response.read(max(0, limit - len(response.leftover)), window)
        response.close()
        return url, response, body[:limit]


def parse_pls(text):
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if re.fullmatch(r"\s*file\d+\s*", key, re.IGNORECASE) and value.strip():
            return value.strip()
    return None


def parse_m3u(text, base):
    """Returns ('master', [(bandwidth, codecs, uri)]) or ('media', [segment uris]) or ('list', [uris])."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if any(l.startswith("#EXT-X-STREAM-INF") for l in lines):
        variants = []
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
                bandwidth = re.search(r"BANDWIDTH=(\d+)", line)
                codecs = re.search(r'CODECS="([^"]*)"', line)
                variants.append((int(bandwidth.group(1)) if bandwidth else 0,
                                 codecs.group(1) if codecs else "", urljoin(base, lines[i + 1])))
        return "master", variants
    uris = [urljoin(base, l) for l in lines if not l.startswith("#")]
    if any(l.startswith("#EXTINF") or l.startswith("#EXT-X-TARGETDURATION") for l in lines):
        return "media", uris
    return "list", uris


def icy_title_present(body, metaint):
    """True when the first ICY metadata block carries a non-empty StreamTitle."""
    if not metaint or len(body) <= metaint:
        return None
    length = body[metaint] * 16
    block = body[metaint + 1: metaint + 1 + length].decode("utf-8", "replace")
    match = re.search(r"StreamTitle='(.*?)';", block)
    return bool(match and match.group(1).strip(" -"))


def strip_icy(body, metaint):
    """Audio bytes without the interleaved ICY metadata blocks."""
    if not metaint:
        return body
    out, i = bytearray(), 0
    while i < len(body):
        out += body[i: i + metaint]
        i += metaint
        if i >= len(body):
            break
        i += 1 + body[i] * 16
    return bytes(out)


def describe(audio, ffprobe="ffprobe"):
    """Codec, profile, sample rate and channels of some audio bytes, read from memory only."""
    if len(audio) < 2048:
        return {}
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-protocol_whitelist", "pipe", "-probesize", str(len(audio)),
             "-show_entries", "stream=codec_type,codec_name,profile,sample_rate,channels,bit_rate:format=format_name",
             "-of", "json", "-i", "pipe:0"],
            input=audio, capture_output=True, timeout=15, check=False,
        )
        data = json.loads(result.stdout or b"{}")
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return {}
    streams = data.get("streams") or []
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    out = {"video": any(s.get("codec_type") == "video" for s in streams)}
    if data.get("format", {}).get("format_name"):
        out["container"] = data["format"]["format_name"].split(",")[0]
    if audio_streams:
        s = audio_streams[0]
        out["codec"] = s.get("codec_name")
        if s.get("profile"):
            out["profile"] = s["profile"]
        if s.get("sample_rate"):
            out["sample_rate"] = int(s["sample_rate"])
        if s.get("channels"):
            out["channels"] = s["channels"]
        if str(s.get("bit_rate", "")).isdigit():
            out["bitrate_kbps"] = round(int(s["bit_rate"]) / 1000)
    return out


def codec_name(info):
    """The base's codec vocabulary: mp3, aac, he-aac, he-aac-v2, flac, opus, vorbis."""
    codec, profile = info.get("codec"), (info.get("profile") or "").upper()
    if codec == "aac":
        if "HE-AACV2" in profile.replace(" ", ""):
            return "he-aac-v2"
        if "HE" in profile:
            return "he-aac"
        return "aac"
    return codec if codec in ("mp3", "flac", "opus", "vorbis") else None


def probe(url, ffprobe="ffprobe", allow_private=False):
    """Returns a dict describing the stream. Never raises."""
    result = {"ok": False}
    started = time.monotonic()
    hops = []
    try:
        final, response, body = _fetch(url, MAX_BODY, READ_WINDOW, allow_private, hops)
        result["ttfb_ms"] = response.ttfb_ms
        ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
        text_like = body[:7] == b"#EXTM3U" or body[:10].lower().startswith(b"[playlist]")
        if text_like or any(t in ctype for t in PLAYLIST_TYPES):
            text = body[:MAX_PLAYLIST].decode("utf-8", "replace")
            if text.lower().lstrip().startswith("[playlist]"):
                target = parse_pls(text)
                if not target:
                    raise Failure("empty_playlist")
                result["playlist"] = "pls"
                final, response, body = _fetch(target, MAX_BODY, READ_WINDOW, allow_private, hops)
            else:
                kind, items = parse_m3u(text, final)
                if kind == "master":
                    result["hls"] = True
                    result["hls_variants_kbps"] = sorted({round(b / 1000) for b, _, _ in items if b})
                    if not items:
                        raise Failure("empty_playlist")
                    _, _, variant = min(items, key=lambda v: v[0] or 10**9)
                    final, _, body = _fetch(variant, MAX_PLAYLIST, None, allow_private, hops)
                    kind, items = parse_m3u(body.decode("utf-8", "replace"), final)
                if kind == "media":
                    result["hls"] = True
                    if not items:
                        raise Failure("empty_playlist")
                    _, response, body = _fetch(items[0], MAX_SEGMENT, None, allow_private, hops)
                else:
                    if not items:
                        raise Failure("empty_playlist")
                    result["playlist"] = "m3u"
                    final, response, body = _fetch(items[0], MAX_BODY, READ_WINDOW, allow_private, hops)
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
        headers = response.headers
        metaint = int(headers["icy-metaint"]) if headers.get("icy-metaint", "").isdigit() else 0
        result["icy"] = any(k.startswith("icy-") for k in headers)
        title = icy_title_present(body, metaint)
        if title is not None:
            result["now_playing"] = "icy" if title else "icy_empty"
        if headers.get("icy-br", "").split(",")[0].isdigit():
            result["declared_kbps"] = int(headers["icy-br"].split(",")[0])
        info = describe(strip_icy(body, metaint), ffprobe)
        if info.get("video") and "codec" not in info:
            raise Failure("video_only")
        if "codec" not in info:
            raise Failure("not_audio", ctype)
        result.update({k: v for k, v in info.items() if k != "video" and v is not None})
        if info.get("video"):
            result["video"] = True
        result["codec"] = codec_name(info) or info.get("codec")
        if "bitrate_kbps" not in result and result.get("declared_kbps"):
            result["bitrate_kbps"] = result["declared_kbps"]
        result["https"] = urlsplit(final).scheme == "https"
        result["ok"] = True
    except Failure as failure:
        result["error"] = failure.code
    except (OSError, ValueError, UnicodeError):
        result["error"] = "bad_response"
    result["redirects"] = len(hops)
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        print(json.dumps({"url": arg, **probe(arg)}, ensure_ascii=False))
