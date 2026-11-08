import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from checker import probe as p
from checker import run as r

HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class Parsers(unittest.TestCase):
    def test_pls(self):
        self.assertEqual(p.parse_pls("[playlist]\nNumberOfEntries=1\nFile1=https://a.example.org/x\n"),
                         "https://a.example.org/x")

    def test_hls_master_and_media(self):
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=64000,CODECS="mp4a.40.5"\nlow.m3u8\n' \
                 '#EXT-X-STREAM-INF:BANDWIDTH=192000\nhigh.m3u8\n'
        kind, items = p.parse_m3u(master, "https://a.example.org/live/index.m3u8")
        self.assertEqual(kind, "master")
        self.assertEqual(items[0], (64000, "mp4a.40.5", "https://a.example.org/live/low.m3u8"))
        kind, items = p.parse_m3u("#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg1.ts\n", "https://a.example.org/l/")
        self.assertEqual((kind, items), ("media", ["https://a.example.org/l/seg1.ts"]))

    def test_icy_metadata(self):
        meta = b"StreamTitle='Artist - Song';"
        meta += b"\0" * (-len(meta) % 16)
        body = b"a" * 8 + bytes([len(meta) // 16]) + meta + b"b" * 8
        self.assertTrue(p.icy_title_present(body, 8))
        self.assertEqual(p.strip_icy(body, 8), b"a" * 8 + b"b" * 8)
        empty = b"a" * 8 + bytes([2]) + b"StreamTitle='';".ljust(32, b"\0")
        self.assertFalse(p.icy_title_present(empty, 8))
        self.assertIsNone(p.icy_title_present(b"a" * 4, 8))

    def test_codec_names(self):
        self.assertEqual(p.codec_name({"codec": "aac", "profile": "HE-AAC"}), "he-aac")
        self.assertEqual(p.codec_name({"codec": "aac", "profile": "HE-AACv2"}), "he-aac-v2")
        self.assertEqual(p.codec_name({"codec": "aac", "profile": "LC"}), "aac")
        self.assertIsNone(p.codec_name({"codec": "pcm_s16le"}))

    def test_private_addresses_are_refused(self):
        for url in ("http://127.0.0.1:8000/x", "http://localhost/x", "http://[::1]/x", "http://10.0.0.1/x"):
            self.assertEqual(p.probe(url)["error"], "private_address", url)


class Health(unittest.TestCase):
    def step(self, history, day, ok, error="connect"):
        streams = [{"id": "sm_a", "url": "https://a.example.org/x", "shard": "FR"}]
        result = {"ok": True, "codec": "mp3", "ttfb_ms": 300} if ok else {"ok": False, "error": error}
        return r.update(history, streams, {"sm_a": result}, day)["sm_a"]

    def test_dead_only_after_three_days(self):
        history = {}
        self.assertEqual(self.step(history, "2026-11-01", True)["state"], "ok")
        self.assertEqual(self.step(history, "2026-11-02", False)["state"], "failing")
        self.assertEqual(self.step(history, "2026-11-02", False)["state"], "failing")  # same day twice
        self.assertEqual(self.step(history, "2026-11-03", False)["state"], "failing")
        dead = self.step(history, "2026-11-04", False)
        self.assertEqual((dead["state"], dead["last_ok_at"], dead["codec"]), ("dead", "2026-11-01", "mp3"))
        self.assertEqual(self.step(history, "2026-11-05", True)["state"], "ok")

    def test_unchecked_stream_keeps_its_state_and_gone_stream_is_forgotten(self):
        history = {"sm_gone": {"runs": []}}
        self.step(history, "2026-11-01", True)
        streams = [{"id": "sm_a", "url": "https://a.example.org/x", "shard": "FR"}]
        self.assertEqual(r.update(history, streams, {}, "2026-11-02")["sm_a"]["state"], "ok")
        self.assertNotIn("sm_gone", history)


class Handler(BaseHTTPRequestHandler):
    audio = b""

    def do_GET(self):
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/live.pls")
            self.end_headers()
        elif self.path == "/live.pls":
            port = self.server.server_address[1]
            body = f"[playlist]\nFile1=http://127.0.0.1:{port}/live\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "audio/x-scpls")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/live":
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("icy-br", "128")
            self.end_headers()
            self.wfile.write(self.audio)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg is not installed")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "tone.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                        "-ac", "2", "-b:a", "128k", str(out)], check=True)
        Handler.audio = out.read_bytes()
        shutil.rmtree(tmp)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_redirect_then_playlist_then_audio(self):
        result = p.probe(self.base + "/moved", allow_private=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["codec"], result["playlist"], result["redirects"]), ("mp3", "pls", 1))
        self.assertEqual(result["channels"], 2)

    def test_http_error(self):
        result = p.probe(self.base + "/nothing", allow_private=True)
        self.assertEqual((result["ok"], result["error"]), (False, "http_error"))

    def test_local_server_is_refused_by_default(self):
        self.assertEqual(p.probe(self.base + "/live")["error"], "private_address")
