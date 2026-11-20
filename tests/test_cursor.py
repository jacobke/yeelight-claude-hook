#!/usr/bin/env python3
"""cursor_plan.py 的单元测试"""

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cursor_plan  # noqa: E402
import deepseek  # noqa: E402
import minimax  # noqa: E402


def period_body(**plan):
    return {"billingCycleEnd": "1771077734000", "planUsage": plan}


class TestParsePeriodUsage(unittest.TestCase):
    def test_cents_to_dollars(self):
        body = period_body(
            includedSpend=23222, remaining=16778, limit=40000,
            totalPercentUsed=15.48)
        used, remaining = cursor_plan.parse_period_usage(body)
        self.assertAlmostEqual(used, 232.22)
        self.assertAlmostEqual(remaining, 167.78)

    def test_string_cents(self):
        used, remaining = cursor_plan.parse_period_usage(
            period_body(includedSpend="400", remaining="1600", limit="2000"))
        self.assertAlmostEqual(used, 4.0)
        self.assertAlmostEqual(remaining, 16.0)

    def test_remaining_computed_when_missing(self):
        used, remaining = cursor_plan.parse_period_usage(
            period_body(includedSpend=500, limit=2000))
        self.assertAlmostEqual(used, 5.0)
        self.assertAlmostEqual(remaining, 15.0)

    def test_used_computed_when_included_missing(self):
        used, remaining = cursor_plan.parse_period_usage(
            period_body(remaining=1500, limit=2000))
        self.assertAlmostEqual(used, 5.0)
        self.assertAlmostEqual(remaining, 15.0)

    def test_negative_remaining_clamped(self):
        used, remaining = cursor_plan.parse_period_usage(
            period_body(includedSpend=2500, remaining=-100, limit=2000))
        self.assertAlmostEqual(used, 25.0)
        self.assertAlmostEqual(remaining, 0.0)

    def test_percent_fallback(self):
        used, remaining = cursor_plan.parse_period_usage(
            period_body(totalPercentUsed=15.5))
        self.assertAlmostEqual(used, 15.5)
        self.assertAlmostEqual(remaining, 84.5)

    def test_bool_cents_are_ignored(self):
        used, remaining = cursor_plan.parse_period_usage(
            period_body(remaining=True, totalPercentUsed=10))
        self.assertAlmostEqual(used, 10.0)
        self.assertAlmostEqual(remaining, 90.0)

    def test_not_a_dict(self):
        with self.assertRaises(cursor_plan.CursorError):
            cursor_plan.parse_period_usage(["nope"])

    def test_missing_plan_usage(self):
        with self.assertRaises(cursor_plan.CursorError):
            cursor_plan.parse_period_usage({"enabled": True})

    def test_empty_plan_usage(self):
        with self.assertRaises(cursor_plan.CursorError):
            cursor_plan.parse_period_usage(period_body())


class FakeResponse:
    def __init__(self, body, code=200):
        self._body = body
        self.code = code

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFetchPeriodUsage(unittest.TestCase):
    def setUp(self):
        self._original = cursor_plan.urllib.request.urlopen

    def tearDown(self):
        cursor_plan.urllib.request.urlopen = self._original

    def test_requires_token(self):
        with self.assertRaises(cursor_plan.CursorError):
            cursor_plan.fetch_period_usage("")

    def test_successful_fetch(self):
        payload = json.dumps(period_body(
            includedSpend=400, remaining=1600, limit=2000)).encode()
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["connect"] = request.get_header("Connect-protocol-version")
            captured["body"] = request.data
            return FakeResponse(payload)

        cursor_plan.urllib.request.urlopen = fake_urlopen
        used, remaining = cursor_plan.fetch_period_usage("dummy-token")
        self.assertAlmostEqual(used, 4.0)
        self.assertAlmostEqual(remaining, 16.0)
        self.assertEqual(
            captured["url"],
            "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage")
        self.assertEqual(captured["auth"], "Bearer dummy-token")
        self.assertEqual(captured["connect"], "1")
        self.assertEqual(captured["body"], b"{}")

    def test_unauthorized_is_auth_error(self):
        def fake_urlopen(request, timeout=None):
            raise cursor_plan.urllib.error.HTTPError(
                request.full_url, 401, "unauthorized", hdrs=None, fp=None)

        cursor_plan.urllib.request.urlopen = fake_urlopen
        with self.assertRaises(cursor_plan.CursorAuthError):
            cursor_plan.fetch_period_usage("expired")

    def test_refresh_returns_token(self):
        payload = json.dumps({"access_token": "new-token", "shouldLogout": False}).encode()

        def fake_urlopen(request, timeout=None):
            self.assertIn("/oauth/token", request.full_url)
            sent = json.loads(request.data.decode())
            self.assertEqual(sent["grant_type"], "refresh_token")
            self.assertEqual(sent["refresh_token"], "refresh-me")
            self.assertNotIn("Authorization", request.headers)
            return FakeResponse(payload)

        cursor_plan.urllib.request.urlopen = fake_urlopen
        self.assertEqual(cursor_plan.refresh_access_token("refresh-me"), "new-token")

    def test_refresh_logout(self):
        payload = json.dumps({"access_token": "", "shouldLogout": True}).encode()
        cursor_plan.urllib.request.urlopen = lambda request, timeout=None: FakeResponse(payload)
        with self.assertRaises(cursor_plan.CursorAuthError):
            cursor_plan.refresh_access_token("refresh-me")


class TestUnsealToken(unittest.TestCase):
    def test_plaintext_passes_through(self):
        self.assertEqual(cursor_plan.unseal_token("eyJ.plain.jwt", "ignored"), "eyJ.plain.jwt")

    def test_round_trip(self):
        password = "test-safe-storage-password"
        key = hashlib.pbkdf2_hmac(
            "sha1", password.encode("utf-8"), cursor_plan._CHROMIUM_SALT, 1003, dklen=16)
        plain = b"header.payload.signature"
        pad = 16 - (len(plain) % 16)
        padded = plain + bytes([pad]) * pad
        proc = subprocess.run(
            [
                "openssl", "enc", "-aes-128-cbc",
                "-K", key.hex(), "-iv", cursor_plan._CHROMIUM_IV.hex(), "-nopad",
            ],
            input=padded,
            capture_output=True,
            check=True,
        )
        sealed = cursor_plan.SAFE_STORAGE_PREFIX + base64.b64encode(b"v10" + proc.stdout).decode()
        self.assertEqual(cursor_plan.unseal_token(sealed, password), plain.decode())

    def test_rejects_unknown_prefix(self):
        sealed = cursor_plan.SAFE_STORAGE_PREFIX + base64.b64encode(b"v11not-valid").decode()
        with self.assertRaises(cursor_plan.CursorError):
            cursor_plan.unseal_token(sealed, "password")


class TestReadLocalTokens(unittest.TestCase):
    def test_reads_auth_keys_only(self):
        path = os.path.join(tempfile.mkdtemp(), "state.vscdb")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        conn.executemany(
            "INSERT INTO ItemTable VALUES (?, ?)",
            [
                ("cursorAuth/accessToken", "access-1"),
                ("cursorAuth/refreshToken", "refresh-1"),
                ("cursorAuth/cachedEmail", "person@example.com"),
            ],
        )
        conn.commit()
        conn.close()

        self.assertEqual(cursor_plan.read_local_tokens(path), ("access-1", "refresh-1"))

    def test_missing_file(self):
        self.assertEqual(
            cursor_plan.read_local_tokens("/nonexistent/state.vscdb"), ("", ""))

    def test_identical_sealed_tokens_drop_refresh(self):
        password = "test-safe-storage-password"
        key = hashlib.pbkdf2_hmac(
            "sha1", password.encode("utf-8"), cursor_plan._CHROMIUM_SALT, 1003, dklen=16)
        plain = b"access-token-value"
        pad = 16 - (len(plain) % 16)
        padded = plain + bytes([pad]) * pad
        proc = subprocess.run(
            [
                "openssl", "enc", "-aes-128-cbc",
                "-K", key.hex(), "-iv", cursor_plan._CHROMIUM_IV.hex(), "-nopad",
            ],
            input=padded,
            capture_output=True,
            check=True,
        )
        sealed = cursor_plan.SAFE_STORAGE_PREFIX + base64.b64encode(b"v10" + proc.stdout).decode()
        path = os.path.join(tempfile.mkdtemp(), "state.vscdb")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        conn.executemany(
            "INSERT INTO ItemTable VALUES (?, ?)",
            [
                ("cursorAuth/accessToken", sealed),
                ("cursorAuth/refreshToken", sealed),
            ],
        )
        conn.commit()
        conn.close()
        self.assertEqual(
            cursor_plan.read_local_tokens(path, password=password),
            ("access-token-value", ""),
        )


class TestRender(unittest.TestCase):
    def test_side_by_side_uses_cursor_colors(self):
        mode, texts = cursor_plan.compose_page(4.2, 16)
        self.assertEqual(mode, "side")
        grid = cursor_plan.render_page(mode, texts)
        colors = {px for px in grid if px != deepseek.BLACK}
        self.assertEqual(colors, {cursor_plan.USED_COLOR, cursor_plan.REMAINING_COLOR})

    def test_palette_disjoint_from_other_pages(self):
        cursor_colors = {cursor_plan.USED_COLOR, cursor_plan.REMAINING_COLOR}
        others = {
            minimax.GREEN, minimax.YELLOW, minimax.RED, minimax.TEAL,
            minimax.BLUE, minimax.PURPLE, minimax.RESET_TRACK,
            deepseek.SPEND_COLOR, deepseek.BALANCE_COLOR,
        }
        for _, color in minimax.RESET_STOPS:
            others.add(color)
        self.assertEqual(cursor_colors & others, set())
