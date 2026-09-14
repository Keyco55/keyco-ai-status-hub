import contextlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import time
import unittest
import urllib.error
from unittest import mock


SCRIPT = pathlib.Path(__file__).parents[1] / "src" / "ai-resource-hud"
REPO_ROOT = pathlib.Path(__file__).parents[1]
SWIFT_SOURCE = REPO_ROOT / "src" / "ai-resource-hud-menu.swift"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-status-hub.sh"
LOADER = importlib.machinery.SourceFileLoader("ai_resource_hud", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
HUD = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(HUD)


@contextlib.contextmanager
def temp_runtime():
    """Authoritative fake-runtime fixture (AGY-TEST-ISO-01).

    Redirects EVERY collector runtime path into one temporary root, never
    the real HOME: CACHE_DIR, CACHE_FILE, AGY_STATUS_FILE, HEALTH_FILE,
    LOCK_FILE. Every test that triggers a collector write must run inside
    this fixture; TestIsolationTests guards the coverage.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        originals = (
            HUD.CACHE_DIR,
            HUD.CACHE_FILE,
            HUD.AGY_STATUS_FILE,
            HUD.HEALTH_FILE,
            HUD.LOCK_FILE,
        )
        HUD.CACHE_DIR = root / ".cache" / "ai-resource-hud"
        HUD.CACHE_FILE = HUD.CACHE_DIR / "status.json"
        HUD.AGY_STATUS_FILE = HUD.CACHE_DIR / "antigravity-statusline.json"
        HUD.HEALTH_FILE = HUD.CACHE_DIR / "health.json"
        HUD.LOCK_FILE = HUD.CACHE_DIR / ".collector.lock"
        try:
            yield root
        finally:
            (
                HUD.CACHE_DIR,
                HUD.CACHE_FILE,
                HUD.AGY_STATUS_FILE,
                HUD.HEALTH_FILE,
                HUD.LOCK_FILE,
            ) = originals


RUNTIME_PATH_ATTRS = (
    "CACHE_DIR",
    "CACHE_FILE",
    "AGY_STATUS_FILE",
    "HEALTH_FILE",
    "LOCK_FILE",
)


def real_home_runtime_base() -> pathlib.Path:
    """The real user runtime base that tests must never write to."""
    home = pathlib.Path(os.environ.get("HOME") or pathlib.Path.home())
    return home / ".cache" / "ai-resource-hud"


def write_agy_record(record, *, stale=False, malformed=False):
    HUD.CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if malformed:
        HUD.AGY_STATUS_FILE.write_text("{not valid json", encoding="utf-8")
    else:
        HUD.AGY_STATUS_FILE.write_text(json.dumps(record), encoding="utf-8")
    if stale:
        old = time.time() - HUD.AGY_STATUS_MAX_AGE_SECONDS - 60
        os.utime(HUD.AGY_STATUS_FILE, (old, old))


def fresh_fallback(remaining=55.0):
    return {
        "status": "ready",
        "source": "statusline",
        "lastSuccessAt": "2026-09-14T00:00:00Z",
        "metrics": {"geminiFiveHour": {"remainingPercent": remaining}},
    }


def offline_payload():
    return [{"provider": "antigravity", "source": "offline", "usage": {}}]


def offline_payload_with_metrics(remaining=1.0):
    # CodexBar may report source=offline while STILL carrying metric values.
    # AGY-FB-01: these must never read as current READY quota.
    return [{
        "provider": "antigravity",
        "source": "offline",
        "usage": {"primary": {"id": "gemini", "remainingPercent": remaining}},
    }]


def run_collect(fetch_result):
    with mock.patch.object(HUD, "fetch_snapshot_result", return_value=fetch_result):
        assert HUD.collect() == 0
    snapshot = json.loads(HUD.CACHE_FILE.read_text(encoding="utf-8"))
    health = json.loads(HUD.HEALTH_FILE.read_text(encoding="utf-8"))
    return snapshot, health


class AntigravityStatuslineTests(unittest.TestCase):
    def test_extracts_quota_without_identity_fields(self):
        record = HUD.agy_statusline_record({
            "product": "antigravity",
            "email": "private@example.test",
            "conversation_id": "private-session",
            "plan_tier": "Pro",
            "quota": {
                "gemini-five-hour": {
                    "remaining_fraction": 0.42,
                    "reset_time": "2026-09-14T05:00:00Z",
                    "reset_in_seconds": 3600,
                },
                "third-party-weekly": {
                    "remaining_fraction": 0.75,
                    "reset_time": "2026-09-19T05:00:00Z",
                    "reset_in_seconds": 400000,
                },
            },
        })

        self.assertEqual(record["source"], "statusline")
        self.assertEqual(record["metrics"]["geminiFiveHour"]["remainingPercent"], 42.0)
        self.assertEqual(record["metrics"]["claudeGptWeekly"]["remainingPercent"], 75.0)
        self.assertNotIn("email", record)
        self.assertNotIn("conversation_id", record)
        self.assertNotIn("plan_tier", record)

    def test_rejects_unrelated_or_empty_payloads(self):
        self.assertIsNone(HUD.agy_statusline_record({"product": "other", "quota": {}}))
        self.assertIsNone(HUD.agy_statusline_record({"product": "antigravity", "quota": {}}))

    def test_weekly_quota_is_used_when_five_hour_is_absent(self):
        root = {
            "providers": {
                "antigravity": {
                    "status": "ready",
                    "metrics": {"geminiWeekly": {"remainingPercent": 93.78}},
                }
            }
        }
        value, status, metric = HUD.status_record(
            root, "antigravity", "geminiFiveHour", "geminiWeekly"
        )
        self.assertEqual((value, status), ("93.8", "ready"))
        self.assertEqual(metric["remainingPercent"], 93.78)

    def test_fresh_cache_loads_and_old_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = pathlib.Path(directory) / "agy.json"
            cache.write_text('{"status":"ready","metrics":{"geminiWeekly":{"remainingPercent":80}}}')
            original_file = HUD.AGY_STATUS_FILE
            original_age = HUD.AGY_STATUS_MAX_AGE_SECONDS
            HUD.AGY_STATUS_FILE = cache
            try:
                self.assertEqual(HUD.load_agy_statusline()["status"], "ready")
                HUD.AGY_STATUS_MAX_AGE_SECONDS = -1
                self.assertIsNone(HUD.load_agy_statusline())
            finally:
                HUD.AGY_STATUS_FILE = original_file
                HUD.AGY_STATUS_MAX_AGE_SECONDS = original_age

    def test_collector_uses_statusline_when_codexbar_is_offline(self):
        # AGY-TEST-ISO-01: the authoritative temp_runtime fixture redirects
        # every runtime path (previously HEALTH_FILE/AGY_STATUS_FILE leaked
        # to the real HOME here).
        with temp_runtime():
            fallback = {
                "status": "ready",
                "source": "statusline",
                "lastSuccessAt": "2026-09-14T00:00:00Z",
                "metrics": {"geminiFiveHour": {"remainingPercent": 55}},
            }
            offline = [{"provider": "antigravity", "source": "offline", "usage": {}}]
            with mock.patch.object(HUD, "fetch_snapshot_result", return_value=(offline, None)), \
                 mock.patch.object(HUD, "load_agy_statusline", return_value=fallback):
                self.assertEqual(HUD.collect(), 0)
            snapshot = json.loads(HUD.CACHE_FILE.read_text())
            self.assertEqual(snapshot["providers"]["antigravity"], fallback)


class TestIsolationTests(unittest.TestCase):
    def test_fixture_redirects_every_runtime_path(self):
        real_base = real_home_runtime_base()
        defaults = {name: getattr(HUD, name) for name in RUNTIME_PATH_ATTRS}
        with temp_runtime() as root:
            for name in RUNTIME_PATH_ATTRS:
                redirected = getattr(HUD, name)
                self.assertNotEqual(redirected, defaults[name])
                self.assertTrue(
                    str(redirected).startswith(str(root)),
                    msg=f"{name} escapes the fake runtime root",
                )
                self.assertFalse(
                    str(redirected).startswith(str(real_base)),
                    msg=f"{name} resolves under the real HOME runtime",
                )
        for name in RUNTIME_PATH_ATTRS:
            self.assertEqual(getattr(HUD, name), defaults[name])

    def test_collect_writes_nothing_under_real_home(self):
        real_base = real_home_runtime_base()
        marker = real_base / ".remediation-guard-probe"
        self.assertFalse(marker.exists())
        with temp_runtime():
            write_agy_record(fresh_fallback())
            run_collect((offline_payload(), None))
            for name in RUNTIME_PATH_ATTRS:
                self.assertFalse(str(getattr(HUD, name)).startswith(str(real_base)))
        self.assertFalse(marker.exists())


class StatuslineSanitizationTests(unittest.TestCase):
    def test_weekly_only_payload_has_no_five_hour_keys(self):
        record = HUD.agy_statusline_record({
            "product": "antigravity",
            "quota": {
                "gemini-weekly": {"remaining_fraction": 0.9378, "reset_in_seconds": 560580},
                "claude-weekly": {"remaining_fraction": 0.5, "reset_in_seconds": 400000},
            },
        })
        self.assertEqual(record["status"], "ready")
        self.assertEqual(record["source"], "statusline")
        self.assertIn("geminiWeekly", record["metrics"])
        self.assertIn("claudeGptWeekly", record["metrics"])
        self.assertNotIn("geminiFiveHour", record["metrics"])
        self.assertNotIn("claudeGptFiveHour", record["metrics"])

    def test_multiple_buckets_with_unknown_bucket_ignored(self):
        record = HUD.agy_statusline_record({
            "product": "antigravity",
            "quota": {
                "gemini-five-hour": {"remaining_fraction": 0.42, "reset_in_seconds": 3600},
                "mystery-model-unlimited": {"remaining_fraction": 0.99, "reset_in_seconds": 10},
                "broken": "not-a-dict",
            },
        })
        self.assertEqual(record["metrics"]["geminiFiveHour"]["remainingPercent"], 42.0)
        self.assertEqual(len(record["metrics"]), 1)

    def test_identity_fields_present_but_absent_from_cache(self):
        payload = {
            "product": "antigravity",
            "email": "someone@example.test",
            "conversation_id": "conv-secret-1",
            "session_id": "sess-secret-2",
            "cwd": "/secret/work/project",
            "transcript_path": "/secret/brain/logs/t.jsonl",
            "workspace": {"current_dir": "/secret/work", "project_dir": "/secret/work"},
            "model": {"id": "Gemini 3", "display_name": "Gemini"},
            "plan_tier": "Pro",
            "quota": {
                "gemini-five-hour": {"remaining_fraction": 0.1, "reset_time": "2026-09-14T05:00:00Z"},
            },
        }
        record = HUD.agy_statusline_record(payload)
        serialized = json.dumps(record)
        for secret in (
            "someone@example.test",
            "conv-secret-1",
            "sess-secret-2",
            "/secret/work",
            "transcript",
            "Pro",
            "Gemini",
        ):
            self.assertNotIn(secret, serialized)
        for key in ("email", "conversation_id", "session_id", "cwd", "transcript_path", "workspace", "model", "plan_tier"):
            self.assertNotIn(key, record)

    def test_malformed_payloads_return_none(self):
        self.assertIsNone(HUD.agy_statusline_record(None))
        self.assertIsNone(HUD.agy_statusline_record([]))
        self.assertIsNone(HUD.agy_statusline_record("antigravity"))
        self.assertIsNone(HUD.agy_statusline_record({"product": "antigravity"}))
        self.assertIsNone(HUD.agy_statusline_record({"product": "antigravity", "quota": []}))
        self.assertIsNone(HUD.agy_statusline_record({
            "product": "antigravity",
            "quota": {"gemini-five-hour": {"remaining_fraction": True}},
        }))
        self.assertIsNone(HUD.agy_statusline_record({
            "product": "antigravity",
            "quota": {"gemini-five-hour": {"remaining_fraction": "high"}},
        }))
        self.assertIsNone(HUD.agy_statusline_record({
            "product": "antigravity",
            "quota": {"gemini-five-hour": "not-a-dict"},
        }))

    def test_cache_states_are_explicit(self):
        with temp_runtime():
            self.assertEqual(HUD.agy_cache_state(), "missing")
            write_agy_record(fresh_fallback())
            self.assertEqual(HUD.agy_cache_state(), "fresh")
            write_agy_record(fresh_fallback(), stale=True)
            self.assertEqual(HUD.agy_cache_state(), "stale")
            write_agy_record(None, malformed=True)
            self.assertEqual(HUD.agy_cache_state(), "malformed")
            HUD.AGY_STATUS_FILE.write_text('{"status":"ready"}', encoding="utf-8")
            self.assertEqual(HUD.agy_cache_state(), "malformed")


class CodexBarCollectionTests(unittest.TestCase):
    def test_valid_response_single_attempt(self):
        payload = [{"provider": "codex"}]
        with mock.patch.object(HUD, "fetch_once", return_value=payload) as fetch, \
             mock.patch.object(HUD.time, "sleep") as sleep:
            self.assertEqual(HUD.fetch_snapshot_result(), (payload, None))
            self.assertEqual(fetch.call_count, 1)
            sleep.assert_not_called()

    def test_empty_body_is_invalid_json_with_bounded_retry(self):
        with mock.patch.object(
            HUD, "fetch_once", side_effect=json.JSONDecodeError("empty", "", 0)
        ) as fetch, mock.patch.object(HUD.time, "sleep") as sleep:
            result, error = HUD.fetch_snapshot_result()
            self.assertIsNone(result)
            self.assertEqual(error, "invalid_json")
            self.assertEqual(fetch.call_count, 2)
            sleep.assert_called_once_with(HUD.RETRY_DELAY_SECONDS)

    def test_invalid_json_stops_after_two_attempts(self):
        with mock.patch.object(HUD, "fetch_once", side_effect=ValueError("bad")) as fetch, \
             mock.patch.object(HUD.time, "sleep"):
            self.assertEqual(HUD.fetch_snapshot_result(), (None, "invalid_json"))
            self.assertEqual(fetch.call_count, 2)

    def test_non_list_json_is_invalid(self):
        with mock.patch.object(HUD, "fetch_once", return_value={"provider": "codex"}) as fetch, \
             mock.patch.object(HUD.time, "sleep"):
            self.assertEqual(HUD.fetch_snapshot_result(), (None, "invalid_json"))
            self.assertEqual(fetch.call_count, 2)

    def test_transport_failure_classification(self):
        with mock.patch.object(
            HUD, "fetch_once", side_effect=urllib.error.URLError("refused")
        ) as fetch, mock.patch.object(HUD.time, "sleep"):
            self.assertEqual(HUD.fetch_snapshot_result(), (None, "transport_error"))
            self.assertEqual(fetch.call_count, 2)

    def test_retry_succeeds_on_second_attempt(self):
        payload = [{"provider": "codex"}]
        with mock.patch.object(
            HUD, "fetch_once", side_effect=[ValueError("empty"), payload]
        ) as fetch, mock.patch.object(HUD.time, "sleep") as sleep:
            self.assertEqual(HUD.fetch_snapshot_result(), (payload, None))
            self.assertEqual(fetch.call_count, 2)
            sleep.assert_called_once_with(HUD.RETRY_DELAY_SECONDS)

    def test_error_classes_are_sanitized(self):
        with mock.patch.object(HUD, "fetch_once", side_effect=OSError("down")), \
             mock.patch.object(HUD.time, "sleep"):
            result, error = HUD.fetch_snapshot_result()
            self.assertIsNone(result)
            self.assertIn(error, HUD.ALLOWED_ERROR_CLASSES)


class RetryBudgetTests(unittest.TestCase):
    """AGY-RETRY-01: at most 2 attempts inside one monotonic total budget."""

    def run_with_fake_clock(self, fetch_behavior):
        """Drive fetch_snapshot_result with a scripted monotonic clock.

        fetch_behavior: list of ("raise", exc) / ("return", value) /
        ("timeout", seconds) consumed in order per fetch_once call, where
        "timeout" advances the fake clock by the simulated attempt duration
        before raising. Returns (result, calls); calls records ("fetch",
        timeout) and ("sleep", delay) events. No real time passes.
        """
        clock = [1000.0]
        calls = []
        behaviors = list(fetch_behavior)

        def fake_monotonic():
            return clock[0]

        def fake_sleep(delay):
            calls.append(("sleep", delay))
            clock[0] += delay

        def fake_fetch(timeout=None):
            calls.append(("fetch", timeout))
            action, value = behaviors.pop(0) if behaviors else ("raise", OSError("down"))
            if action == "timeout":
                clock[0] += value
                raise urllib.error.URLError("timed out")
            if action == "raise":
                raise value
            return value

        with mock.patch.object(HUD.time, "monotonic", side_effect=fake_monotonic), \
             mock.patch.object(HUD.time, "sleep", side_effect=fake_sleep), \
             mock.patch.object(HUD, "fetch_once", side_effect=fake_fetch):
            result = HUD.fetch_snapshot_result()
        return result, calls

    def test_attempt_timeouts_respect_remaining_budget(self):
        payload = [{"provider": "codex"}]
        (_, error), calls = self.run_with_fake_clock([("return", payload)])
        self.assertIsNone(error)
        fetches = [c for c in calls if c[0] == "fetch"]
        self.assertEqual(len(fetches), 1)
        self.assertLessEqual(fetches[0][1], HUD.FETCH_BUDGET_SECONDS)

    def test_no_retry_once_budget_is_exhausted(self):
        # First attempt consumes the whole budget; no second fetch, no sleep.
        (_, error), calls = self.run_with_fake_clock(
            [("timeout", HUD.FETCH_BUDGET_SECONDS + 1.0)]
        )
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds, ["fetch"])
        self.assertEqual(error, "transport_error")

    def test_retry_delay_is_bounded_by_remaining_budget(self):
        # First attempt burns nearly the whole budget; the retry delay must
        # shrink to fit instead of using the full 0.5s.
        (_, _), calls = self.run_with_fake_clock(
            [("timeout", HUD.FETCH_BUDGET_SECONDS - 0.1),
             ("timeout", HUD.FETCH_BUDGET_SECONDS)]
        )
        sleeps = [c[1] for c in calls if c[0] == "sleep"]
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)
        self.assertLessEqual(sleeps[0], 0.1 + 1e-9)
        self.assertLessEqual(sleeps[0], HUD.RETRY_DELAY_SECONDS)

    def test_total_simulated_time_never_exceeds_budget_plus_delay(self):
        (_, _), calls = self.run_with_fake_clock(
            [("timeout", 14.0), ("timeout", 14.0)]
        )
        fetches = [c for c in calls if c[0] == "fetch"]
        self.assertLessEqual(len(fetches), 2)
        for _, timeout in fetches:
            self.assertLessEqual(timeout, HUD.FETCH_BUDGET_SECONDS)
        for _, delay in (c for c in calls if c[0] == "sleep"):
            self.assertLessEqual(delay, HUD.RETRY_DELAY_SECONDS)

    def test_no_request_starts_below_minimum_threshold(self):
        # First attempt leaves 0.2s; no second request may be configured
        # beyond the remaining deadline, even though attempts remain.
        (_, error), calls = self.run_with_fake_clock(
            [("timeout", HUD.FETCH_BUDGET_SECONDS - 0.2),
             ("return", [{"provider": "codex"}])]
        )
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds, ["fetch", "sleep"])
        self.assertEqual(error, "transport_error")
        for _, timeout in (c for c in calls if c[0] == "fetch"):
            self.assertGreaterEqual(timeout, HUD.MIN_REQUEST_TIMEOUT)

    def test_second_attempt_success_inside_budget(self):
        payload = [{"provider": "codex"}]
        (result, error), calls = self.run_with_fake_clock(
            [("raise", ValueError("empty")), ("return", payload)]
        )
        self.assertEqual((result, error), (payload, None))
        self.assertEqual([c[0] for c in calls], ["fetch", "sleep", "fetch"])


class CodexBarHttpTests(unittest.TestCase):
    """Minimal synthetic HTTP coverage with stdlib only (no network).

    Exercises the real transport path (socket + JSON decode) for the empty,
    malformed, and valid cases. Sleeps are stubbed for speed; classification
    and attempt bounds are what matter here.
    """

    def run_against(self, body, content_type="application/json"):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # addCleanup runs LIFO, so register in reverse: shutdown, join, close.
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/usage?provider=all"
        with mock.patch.object(HUD, "SERVER_URL", url), \
             mock.patch.object(HUD.time, "sleep") as sleep:
            return HUD.fetch_snapshot_result(), sleep

    def test_http_empty_body_is_invalid(self):
        (payload, error), sleep = self.run_against(b"")
        self.assertIsNone(payload)
        self.assertEqual(error, "invalid_json")
        # Bounded retry happened without real delay.
        self.assertEqual(sleep.call_count, 1)

    def test_http_malformed_json_is_invalid(self):
        (payload, error), _ = self.run_against(b"{not json")
        self.assertIsNone(payload)
        self.assertEqual(error, "invalid_json")

    def test_http_valid_list_succeeds_without_retry(self):
        body = b'[{"provider":"codex","usage":{"primary":{"remainingPercent":80}}}]'
        (payload, error), sleep = self.run_against(body)
        self.assertEqual(error, None)
        self.assertEqual(payload, json.loads(body))
        sleep.assert_not_called()


class FallbackPrecedenceTests(unittest.TestCase):
    def test_codexbar_healthy_preserves_normal_behavior(self):
        payload = [{
            "provider": "antigravity",
            "source": "loopback",
            "usage": {"primary": {"id": "gemini", "remainingPercent": 61.5}},
        }]
        with temp_runtime():
            write_agy_record(fresh_fallback(remaining=10.0))
            snapshot, health = run_collect((payload, None))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "ready")
            self.assertEqual(antigravity["source"], "loopback")
            self.assertEqual(
                antigravity["metrics"]["geminiFiveHour"]["remainingPercent"], 61.5
            )
            self.assertIsNone(health["last_error_class"])

    def test_offline_with_metrics_still_prefers_fresh_statusline(self):
        payload = [{
            "provider": "antigravity",
            "source": "offline",
            "usage": {"primary": {"id": "gemini", "remainingPercent": 1.0}},
        }]
        with temp_runtime():
            write_agy_record(fresh_fallback(remaining=55.0))
            snapshot, health = run_collect((payload, None))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "ready")
            self.assertEqual(antigravity["source"], "statusline")
            self.assertEqual(
                antigravity["metrics"]["geminiFiveHour"]["remainingPercent"], 55.0
            )
            self.assertEqual(health["last_error_class"], "provider_offline")

    def test_offline_metrics_with_stale_fallback_is_stale_only(self):
        previous = {
            "version": 1,
            "providers": {
                "antigravity": {
                    "status": "ready",
                    "source": "statusline",
                    "lastSuccessAt": "2026-09-13T00:00:00Z",
                    "metrics": {"geminiFiveHour": {"remainingPercent": 44.0}},
                }
            },
        }
        with temp_runtime():
            HUD.CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            HUD.CACHE_FILE.write_text(json.dumps(previous), encoding="utf-8")
            write_agy_record(fresh_fallback(), stale=True)
            snapshot, _ = run_collect((offline_payload_with_metrics(), None))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "stale")
            self.assertEqual(
                antigravity["metrics"]["geminiFiveHour"]["remainingPercent"], 44.0
            )

    def test_offline_metrics_with_missing_fallback_is_unavailable(self):
        with temp_runtime():
            snapshot, health = run_collect((offline_payload_with_metrics(), None))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "unavailable")
            self.assertNotIn("remainingPercent", json.dumps(antigravity))
            self.assertEqual(health["last_error_class"], "provider_offline")

    def test_offline_metrics_with_malformed_fallback_is_safe(self):
        with temp_runtime():
            write_agy_record(None, malformed=True)
            snapshot, health = run_collect((offline_payload_with_metrics(), None))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "unavailable")
            self.assertNotIn("remainingPercent", json.dumps(antigravity))
            self.assertEqual(health["statusline_cache_state"], "malformed")

    def test_empty_response_with_fresh_statusline_stays_ready(self):
        with temp_runtime():
            write_agy_record(fresh_fallback())
            snapshot, health = run_collect((None, "invalid_json"))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual((antigravity["status"], antigravity["source"]), ("ready", "statusline"))
            self.assertEqual(health["codexbar_state"], "invalid_json")
            self.assertEqual(health["last_error_class"], "invalid_json")

    def test_transport_failure_with_fresh_statusline_stays_ready(self):
        with temp_runtime():
            write_agy_record(fresh_fallback())
            snapshot, health = run_collect((None, "transport_error"))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual((antigravity["status"], antigravity["source"]), ("ready", "statusline"))
            self.assertEqual(health["last_error_class"], "transport_error")

    def test_stale_cache_gives_deterministic_stale(self):
        previous = {
            "version": 1,
            "providers": {
                "antigravity": {
                    "status": "ready",
                    "source": "statusline",
                    "lastSuccessAt": "2026-09-13T00:00:00Z",
                    "metrics": {"geminiFiveHour": {"remainingPercent": 44.0}},
                }
            },
        }
        with temp_runtime():
            HUD.CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            HUD.CACHE_FILE.write_text(json.dumps(previous), encoding="utf-8")
            write_agy_record(fresh_fallback(), stale=True)
            snapshot, health = run_collect((None, "transport_error"))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "stale")
            self.assertEqual(
                antigravity["metrics"]["geminiFiveHour"]["remainingPercent"], 44.0
            )
            self.assertEqual(health["statusline_cache_state"], "stale")

    def test_missing_cache_gives_unavailable_without_fabrication(self):
        with temp_runtime():
            snapshot, health = run_collect((None, "transport_error"))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "unavailable")
            self.assertNotIn("remainingPercent", json.dumps(antigravity))
            self.assertEqual(health["statusline_cache_state"], "missing")
            self.assertEqual(health["last_error_class"], "transport_error")

    def test_malformed_cache_gives_safe_state(self):
        with temp_runtime():
            write_agy_record(None, malformed=True)
            snapshot, health = run_collect((None, "transport_error"))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual(antigravity["status"], "unavailable")
            self.assertNotIn("remainingPercent", json.dumps(antigravity))
            self.assertEqual(health["statusline_cache_state"], "malformed")


class LoaderWhitelistTests(unittest.TestCase):
    """AGY-CACHE-01: the loader rebuilds records from a whitelist only."""

    def test_tampered_cache_falls_back_without_identity(self):
        tampered = {
            "status": "ready",
            "source": "statusline",
            "lastSuccessAt": "2026-09-14T00:00:00Z",
            "email": "someone@example.test",
            "conversation_id": "conv-secret",
            "session_id": "sess-secret",
            "workspace": {"current_dir": "/secret/work"},
            "cwd": "/secret/work",
            "transcript_path": "/secret/t.jsonl",
            "model": {"id": "Gemini 3"},
            "metrics": {
                "geminiFiveHour": {
                    "remainingPercent": 42.0,
                    "resetAt": "2026-09-14T05:00:00Z",
                    "email": "someone@example.test",
                },
                "unknownFutureWindow": {"remainingPercent": 99.0},
            },
        }
        with temp_runtime():
            write_agy_record(tampered)
            record = HUD.load_agy_statusline()
            self.assertEqual(record["metrics"]["geminiFiveHour"]["remainingPercent"], 42.0)
            serialized = json.dumps(record)
            for banned in ("someone@example.test", "conv-secret", "sess-secret",
                           "/secret", "transcript", "unknownFutureWindow", "Gemini"):
                self.assertNotIn(banned, serialized)
            self.assertEqual(set(record), {"status", "source", "lastSuccessAt", "metrics"})
            snapshot, _ = run_collect((offline_payload_with_metrics(), None))
            snapshot_text = json.dumps(snapshot["providers"]["antigravity"])
            for banned in ("someone@example.test", "conv-secret", "sess-secret",
                           "/secret", "transcript", "unknownFutureWindow"):
                self.assertNotIn(banned, snapshot_text)

    def test_loader_rejects_metric_without_remaining(self):
        with temp_runtime():
            write_agy_record({"status": "ready", "metrics": {"geminiWeekly": {"resetAt": "x"}}})
            self.assertIsNone(HUD.load_agy_statusline())
            self.assertEqual(HUD.agy_cache_state(), "malformed")

    def test_loader_clamps_and_keeps_reset(self):
        with temp_runtime():
            write_agy_record({"status": "ready",
                              "metrics": {"geminiWeekly": {"remainingPercent": 140.5,
                                                           "resetAt": "2026-09-19T05:00:00Z"}}})
            record = HUD.load_agy_statusline()
            self.assertEqual(record["metrics"]["geminiWeekly"]["remainingPercent"], 100.0)
            self.assertEqual(record["metrics"]["geminiWeekly"]["resetAt"], "2026-09-19T05:00:00Z")


class MenuSelectionTests(unittest.TestCase):
    def test_five_hour_preferred_when_present(self):
        root = {"providers": {"antigravity": {
            "status": "ready",
            "metrics": {
                "geminiFiveHour": {"remainingPercent": 42.0},
                "geminiWeekly": {"remainingPercent": 93.78},
            },
        }}}
        value, status, metric = HUD.status_record(root, "antigravity", "geminiFiveHour", "geminiWeekly")
        self.assertEqual((value, status), ("42", "ready"))
        self.assertEqual(metric["remainingPercent"], 42.0)

    def test_neither_window_is_unavailable(self):
        root = {"providers": {"antigravity": {"status": "unavailable", "metrics": {}}}}
        self.assertEqual(
            HUD.status_record(root, "antigravity", "geminiFiveHour", "geminiWeekly"),
            ("--", "unavailable", None),
        )

    def test_swift_helper_has_weekly_fallback(self):
        source = SWIFT_SOURCE.read_text(encoding="utf-8")
        self.assertIn('return self.metric(record: providerRecord, name: "geminiWeekly")', source)
        self.assertIn('return self.metric(record: providerRecord, name: "claudeGptWeekly")', source)
        self.assertIn('menu.usage.title = detailText("Weekly", weeklyMetric)', source)
        self.assertIn('menu.usage.title = detailText("5H", fiveHourMetric)', source)


class HealthRecordTests(unittest.TestCase):
    def test_healthy_run_records_success(self):
        payload = [{
            "provider": "antigravity",
            "source": "loopback",
            "usage": {"primary": {"id": "gemini", "remainingPercent": 61.5}},
        }]
        with temp_runtime():
            _, health = run_collect((payload, None))
            self.assertEqual(set(health) <= set(HUD.HEALTH_KEYS), True)
            self.assertEqual(health["schema_version"], 1)
            self.assertEqual(health["codexbar_state"], "ok")
            self.assertIsNone(health["last_error_class"])
            self.assertEqual(health["antigravity_source"], "loopback")
            self.assertEqual(health["antigravity_status"], "ready")
            self.assertIsNotNone(health["last_collector_run"])
            self.assertIsNotNone(health["last_success"])
            mode = HUD.HEALTH_FILE.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_degraded_run_distinguishes_exit_from_health(self):
        with temp_runtime():
            write_agy_record(fresh_fallback())
            _, health = run_collect((None, "transport_error"))
            self.assertEqual(health["antigravity_source"], "statusline")
            self.assertEqual(health["antigravity_status"], "ready")
            self.assertEqual(health["codexbar_state"], "transport_error")
            self.assertEqual(health["last_error_class"], "transport_error")

    def test_health_contains_no_identity_or_body(self):
        with temp_runtime():
            write_agy_record(fresh_fallback())
            _, health = run_collect((None, "transport_error"))
            serialized = json.dumps(health)
            for banned in ("email", "token", "conversation", "session", "workspace",
                           "transcript", "cwd", "prompt", "raw", "body", "account"):
                self.assertNotIn(banned, serialized.lower())
            self.assertIn(health["last_error_class"], HUD.ALLOWED_ERROR_CLASSES)

    def test_write_health_rejects_unknown_error_class(self):
        with temp_runtime():
            HUD.write_health({"schema_version": 1, "last_error_class": "http-500-body"})
            health = json.loads(HUD.HEALTH_FILE.read_text(encoding="utf-8"))
            self.assertIsNone(health["last_error_class"])

    def test_offline_fallback_does_not_advance_last_success(self):
        payload = [{
            "provider": "antigravity",
            "source": "loopback",
            "usage": {"primary": {"id": "gemini", "remainingPercent": 61.5}},
        }]
        with temp_runtime():
            _, healthy = run_collect((payload, None))
            first_success = healthy["last_success"]
            self.assertIsNotNone(first_success)
            write_agy_record(fresh_fallback())
            snapshot, degraded = run_collect((offline_payload_with_metrics(), None))
            antigravity = snapshot["providers"]["antigravity"]
            self.assertEqual((antigravity["status"], antigravity["source"]),
                             ("ready", "statusline"))
            self.assertIsNotNone(degraded["last_collector_run"])
            self.assertEqual(degraded["last_success"], first_success)
            self.assertEqual(degraded["last_error_class"], "provider_offline")

    def test_failed_cycle_preserves_last_success(self):
        payload = [{
            "provider": "antigravity",
            "source": "loopback",
            "usage": {"primary": {"id": "gemini", "remainingPercent": 61.5}},
        }]
        with temp_runtime():
            _, healthy = run_collect((payload, None))
            first_success = healthy["last_success"]
            self.assertIsNotNone(first_success)
            _, degraded = run_collect((None, "transport_error"))
            self.assertEqual(degraded["last_success"], first_success)
            self.assertNotEqual(degraded["last_collector_run"], None)
            self.assertEqual(degraded["codexbar_state"], "transport_error")


class SwiftHarnessTests(unittest.TestCase):
    """AGY-SWIFT-01: execute the real menuStateTitle from Swift source.

    The pure helper is extracted verbatim between its TESTABLE markers and
    compiled into a small harness (no AppKit, no framework): real execution,
    not pattern matching. The Python truth table below documents the same
    rule for reviewers.
    """

    START = "// TESTABLE-START menu-state-title"
    END = "// TESTABLE-END menu-state-title"

    CASES = [
        # (isAvailable, percentText, providerState, expected)
        ("false", "50", "ready", "Status: unavailable"),
        ("true", "50", "stale", "Status: stale"),
        ("true", "99.9", "stale", "Status: stale"),
        ("true", "0", "stale", "Status: stale"),
        ("true", "100", "ready", "Status: ready"),
        ("true", "0", "ready", "Status: stop"),
        ("true", "50", "ready", "Status: active"),
    ]

    def test_menu_state_title_harness(self):
        import shutil as _shutil
        if _shutil.which("swiftc") is None:
            self.skipTest("swiftc not available")
        source = SWIFT_SOURCE.read_text(encoding="utf-8")
        start = source.index(self.START) + len(self.START)
        end = source.index(self.END)
        function = source[start:end]
        self.assertIn("func menuStateTitle", function)
        lines = ["import Foundation", function, "func check(_ actual: String, _ expected: String, _ name: String) {",
                 '    if actual != expected { print("FAIL \\(name): got \\(actual), want \\(expected)"); fatalError("harness failure") }',
                 "}"]
        for available, percent, state, expected in self.CASES:
            lines.append(
                f'check(menuStateTitle(isAvailable: {available}, percentText: "{percent}", '
                f'providerState: "{state}"), "{expected}", "{percent}/{state}")'
            )
        lines.append('print("HARNESS PASS")')
        with tempfile.TemporaryDirectory() as directory:
            harness = pathlib.Path(directory) / "menu-state-harness.swift"
            binary = pathlib.Path(directory) / "menu-state-harness"
            harness.write_text("\n".join(lines) + "\n", encoding="utf-8")
            compiled = subprocess.run(
                ["swiftc", "-o", str(binary), str(harness)],
                capture_output=True, text=True, timeout=300,
            )
            self.assertEqual(compiled.returncode, 0, msg=compiled.stderr)
            ran = subprocess.run(
                [str(binary)], capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(ran.returncode, 0, msg=ran.stdout + ran.stderr)
            self.assertIn("HARNESS PASS", ran.stdout)


def run_in_child(script, timeout=300):
    """Run a shell snippet as a single child process and return it.

    All filesystem reads inside `script` share one view with the writes it
    performs, so assertions about deployed artifacts are made in-child and
    reported over stdout/stderr and exit codes (which are always faithfully
    captured). Tests never read child-written files directly.
    """
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=timeout)


# Shared preamble for deployment probes: build an isolated CLEAN git source
# fixture (real sources committed) plus a fake HOME, entirely inside one
# worktree-local temp root that the probe cleans up itself. Everything the
# probe asserts is computed in-child and reported via stdout markers.
FIXTURE_PREAMBLE = """set -eu
T=$(mktemp -d "{repo}/.tmp-deploy-XXXXXX")
trap 'rm -rf "$T"' EXIT INT TERM
SRC="$T/src"
HOME_DIR="$T/home"
mkdir -p "$SRC/src" "$HOME_DIR"
cp "{repo}/src/ai-resource-hud" "$SRC/src/ai-resource-hud"
cp "{repo}/src/ai-resource-hud-menu.swift" "$SRC/src/ai-resource-hud-menu.swift"
git -C "$SRC" init -q
git -C "$SRC" add -A
git -c user.email=fixture@example.test -c user.name=fixture -C "$SRC" commit -qm init
test -z "$(git -C "$SRC" status --porcelain)"
HEAD=$(git -C "$SRC" rev-parse HEAD)
DEPLOY="{deploy}"
"""


class DeployMatrixTests(unittest.TestCase):
    """Substantive deployment guarantees (AGY-DEPLOY-01/02, AGY-PROV-01, §13).

    Every test runs its fixture, deployment, and assertions inside a single
    child shell; the parent asserts only on exit codes and stdout markers.
    """

    def probe(self, body, timeout=300):
        script = FIXTURE_PREAMBLE.format(repo=REPO_ROOT, deploy=DEPLOY_SCRIPT) + body
        return run_in_child(script, timeout=timeout)

    def test_clean_deploy_provenance_paths_and_permissions(self):
        result = self.probe(
            'BIN="$HOME_DIR/.local/bin"\n'
            'MANIFEST="$HOME_DIR/.cache/ai-resource-hud/install.json"\n'
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" --print-manifest >"$T/out.txt" 2>&1\n'
            'echo "DEPLOY_RC=$?"\n'
            'grep -q "deploy: OK" "$T/out.txt" && echo DEPLOY_OK\n'
            'MANIFEST_JSON=$(grep "^manifest: " "$T/out.txt" | sed "s/^manifest: //")\n'
            'echo "MANIFEST_JSON=$MANIFEST_JSON"\n'
            'C_SHA=$(python3 -c \'import json,sys; print(json.loads(sys.argv[1])["collector_sha256"])\' "$MANIFEST_JSON")\n'
            'M_SHA=$(python3 -c \'import json,sys; print(json.loads(sys.argv[1])["menu_sha256"])\' "$MANIFEST_JSON")\n'
            'S_COMMIT=$(python3 -c \'import json,sys; print(json.loads(sys.argv[1])["source_commit"])\' "$MANIFEST_JSON")\n'
            'KEYS=$(python3 -c \'import json,sys; print(",".join(sorted(json.loads(sys.argv[1]).keys())))\' "$MANIFEST_JSON")\n'
            'echo "KEYS=$KEYS"\n'
            'test "$S_COMMIT" = "$HEAD" && echo COMMIT_MATCH\n'
            'grep -q "verify: collector sha256 $C_SHA" "$T/out.txt" && echo COLLECTOR_SHA_MATCH\n'
            'grep -q "verify: menu helper sha256 $M_SHA" "$T/out.txt" && echo HELPER_SHA_MATCH\n'
            'test -f "$MANIFEST" && echo MANIFEST_PATH_OK\n'
            'test ! -e "$HOME_DIR/.cache/ai-resource-hub/install.json" && echo NO_TYPO_PATH\n'
            'test "$(stat -f %Lp "$MANIFEST")" = 600 && echo MANIFEST_PERMS_OK\n'
            'test "$(stat -f %Lp "$BIN/ai-resource-hud")" = 755 && echo COLLECTOR_PERMS_OK\n'
            'test "$(stat -f %Lp "$BIN/ai-resource-hud-menu")" = 755 && echo HELPER_PERMS_OK\n'
            'test "$(stat -f %Lp "$HOME_DIR/.cache/ai-resource-hud")" = 700 && echo CACHEDIR_PERMS_OK\n'
            'if grep -qi -E "email|token|conversation|session|workspace|transcript|prompt|payload|account" "$MANIFEST"; then echo SENSITIVE_LEAK; else echo NO_SENSITIVE; fi\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for marker in ("DEPLOY_RC=0", "DEPLOY_OK", "MANIFEST_PATH_OK", "NO_TYPO_PATH",
                       "COMMIT_MATCH", "COLLECTOR_SHA_MATCH", "HELPER_SHA_MATCH",
                       "MANIFEST_PERMS_OK", "COLLECTOR_PERMS_OK", "HELPER_PERMS_OK",
                       "CACHEDIR_PERMS_OK", "NO_SENSITIVE"):
            self.assertIn(marker, result.stdout)
        manifest = json.loads(next(
            line for line in result.stdout.splitlines() if line.startswith("MANIFEST_JSON=")
        )[len("MANIFEST_JSON="):])
        self.assertEqual(
            set(manifest),
            {"schema_version", "source_commit", "collector_sha256",
             "menu_sha256", "installed_at", "runtime_version"},
        )

    def test_deploy_into_path_with_spaces(self):
        result = self.probe(
            'HOME_DIR="$T/my home"\n'
            'mkdir -p "$HOME_DIR"\n'
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1\n'
            'echo "DEPLOY_RC=$?"\n'
            'test -f "$HOME_DIR/.cache/ai-resource-hud/install.json" && echo MANIFEST_OK\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEPLOY_RC=0", result.stdout)
        self.assertIn("MANIFEST_OK", result.stdout)

    def test_verify_only_and_tamper_detection(self):
        result = self.probe(
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1\n'
            'echo "DEPLOY_RC=$?"\n'
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" --verify-only >/dev/null 2>&1\n'
            'echo "VERIFY_CLEAN_RC=$?"\n'
            'printf tampered >> "$HOME_DIR/.local/bin/ai-resource-hud-menu"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" --verify-only >/dev/null 2>&1; then echo "VERIFY_TAMPERED_RC=0"; else echo "VERIFY_TAMPERED_RC=$?"; fi\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEPLOY_RC=0", result.stdout)
        self.assertIn("VERIFY_CLEAN_RC=0", result.stdout)
        self.assertNotIn("VERIFY_TAMPERED_RC=0", result.stdout)
        self.assertIn("VERIFY_TAMPERED_RC=", result.stdout)

    def rollback_probe(self, inject_point):
        # Every statement is total under set -eu: expected failures use
        # if/else so the probe always survives to report markers.
        return (
            'mkdir -p "$HOME_DIR/.local/bin" "$HOME_DIR/.cache/ai-resource-hud"\n'
            'printf old-collector-bytes > "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'printf old-helper-bytes > "$HOME_DIR/.local/bin/ai-resource-hud-menu"\n'
            'printf \'{"schema_version":1,"old":true}\' > "$HOME_DIR/.cache/ai-resource-hud/install.json"\n'
            'cp "$HOME_DIR/.local/bin/ai-resource-hud" "$T/expected-collector"\n'
            'cp "$HOME_DIR/.local/bin/ai-resource-hud-menu" "$T/expected-helper"\n'
            'cp "$HOME_DIR/.cache/ai-resource-hud/install.json" "$T/expected-manifest"\n'
            f'if STATUS_HUB_INJECT_FAIL={inject_point} "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >"$T/out.txt" 2>&1; then echo "INJECT_RC=0"; else echo "INJECT_RC=$?"; fi\n'
            'grep -q "deploy: OK" "$T/out.txt" && echo UNEXPECTED_OK || echo NO_OK\n'
            'cmp -s "$T/expected-collector" "$HOME_DIR/.local/bin/ai-resource-hud" && echo COLLECTOR_RESTORED || echo COLLECTOR_CHANGED\n'
            'cmp -s "$T/expected-helper" "$HOME_DIR/.local/bin/ai-resource-hud-menu" && echo HELPER_RESTORED || echo HELPER_CHANGED\n'
            'cmp -s "$T/expected-manifest" "$HOME_DIR/.cache/ai-resource-hud/install.json" && echo MANIFEST_RESTORED || echo MANIFEST_CHANGED\n'
            'ls "$HOME_DIR/.cache/ai-resource-hud" | grep -q "^\\.install\\." && echo TEMP_LEFTOVER || echo NO_TEMP_LEFTOVER\n'
        )

    def assert_rollback(self, inject_point):
        result = self.probe(self.rollback_probe(inject_point))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("NO_OK", result.stdout)
        self.assertNotIn("UNEXPECTED_OK", result.stdout)
        self.assertNotIn("INJECT_RC=0", result.stdout)
        for marker in ("COLLECTOR_RESTORED", "HELPER_RESTORED", "MANIFEST_RESTORED",
                       "NO_TEMP_LEFTOVER"):
            self.assertIn(marker, result.stdout, msg=f"{inject_point}: {result.stdout}")

    def test_rollback_on_collector_install_failure(self):
        self.assert_rollback("collector-install")

    def test_rollback_on_helper_install_failure(self):
        self.assert_rollback("helper-install")

    def test_rollback_on_manifest_write_failure(self):
        self.assert_rollback("manifest-write")

    def test_rollback_on_verification_failure(self):
        self.assert_rollback("verify")

    def test_rollback_on_timestamp_failure(self):
        self.assert_rollback("timestamp")

    def test_rollback_on_manifest_commit_failure(self):
        self.assert_rollback("manifest-commit")

    def test_failed_rollback_keeps_recovery_material(self):
        # Both the deployment failure and the rollback restoration failure
        # are injected: recovery backups must survive and the failure must
        # be explicit, never reported as success.
        result = self.probe(
            'mkdir -p "$HOME_DIR/.local/bin" "$HOME_DIR/.cache/ai-resource-hud"\n'
            'printf old-collector-bytes > "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'printf old-helper-bytes > "$HOME_DIR/.local/bin/ai-resource-hud-menu"\n'
            'printf \'{"schema_version":1,"old":true}\' > "$HOME_DIR/.cache/ai-resource-hud/install.json"\n'
            'if STATUS_HUB_INJECT_FAIL=verify STATUS_HUB_INJECT_ROLLBACK_FAIL=1 '
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" >"$T/out.txt" 2>&1; '
            'then echo "INJECT_RC=0"; else echo "INJECT_RC=$?"; fi\n'
            'grep -q "rollback FAILED" "$T/out.txt" && echo ROLLBACK_FAILED_EXPLICIT || echo ROLLBACK_SILENT\n'
            'BACKUP_DIR=$(grep "recovery backups kept in " "$T/out.txt" | sed "s/.*recovery backups kept in //")\n'
            'test -n "$BACKUP_DIR" && echo BACKUP_DIR_KNOWN || echo BACKUP_DIR_UNKNOWN\n'
            'test -f "$BACKUP_DIR/ai-resource-hud" && echo BACKUP_COLLECTOR_KEPT || echo BACKUP_COLLECTOR_GONE\n'
            'test -f "$BACKUP_DIR/ai-resource-hud-menu" && echo BACKUP_HELPER_KEPT || echo BACKUP_HELPER_GONE\n'
            'test -f "$BACKUP_DIR/install.json" && echo BACKUP_MANIFEST_KEPT || echo BACKUP_MANIFEST_GONE\n'
            'grep -q "deploy: OK" "$T/out.txt" && echo UNEXPECTED_OK || echo NO_OK\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("INJECT_RC=0", result.stdout)
        self.assertIn("ROLLBACK_FAILED_EXPLICIT", result.stdout)
        self.assertIn("BACKUP_DIR_KNOWN", result.stdout)
        for marker in ("BACKUP_COLLECTOR_KEPT", "BACKUP_HELPER_KEPT",
                       "BACKUP_MANIFEST_KEPT", "NO_OK"):
            self.assertIn(marker, result.stdout)

    def mutate_manifest(self, python_edit):
        return (
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1\n'
            'echo "DEPLOY_RC=$?"\n'
            'MANIFEST="$HOME_DIR/.cache/ai-resource-hud/install.json"\n'
            f'python3 - "$MANIFEST" <<\'PYEOF\'\n'
            'import json, sys\n'
            'path = sys.argv[1]\n'
            'record = json.load(open(path))\n'
            f'{python_edit}\n'
            'json.dump(record, open(path, "w"), sort_keys=True, separators=(",", ":"))\n'
            'PYEOF\n'
        )

    def test_verify_only_rejects_forged_commit(self):
        result = self.probe(
            self.mutate_manifest('record["source_commit"] = "f" * 40')
            + 'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" --verify-only >/dev/null 2>&1; then echo "VERIFY_RC=0"; else echo "VERIFY_RC=$?"; fi\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEPLOY_RC=0", result.stdout)
        self.assertNotIn("VERIFY_RC=0", result.stdout)

    def test_verify_only_rejects_missing_key(self):
        result = self.probe(
            self.mutate_manifest('del record["menu_sha256"]')
            + 'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" --verify-only >/dev/null 2>&1; then echo "VERIFY_RC=0"; else echo "VERIFY_RC=$?"; fi\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEPLOY_RC=0", result.stdout)
        self.assertNotIn("VERIFY_RC=0", result.stdout)

    def test_verify_only_rejects_extra_key(self):
        result = self.probe(
            self.mutate_manifest('record["forged_extra"] = "x"')
            + 'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" --verify-only >/dev/null 2>&1; then echo "VERIFY_RC=0"; else echo "VERIFY_RC=$?"; fi\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEPLOY_RC=0", result.stdout)
        self.assertNotIn("VERIFY_RC=0", result.stdout)

    def test_verify_only_rejects_malformed_manifest(self):
        result = self.probe(
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1\n'
            'echo "DEPLOY_RC=$?"\n'
            'printf "{broken" > "$HOME_DIR/.cache/ai-resource-hud/install.json"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" --verify-only >/dev/null 2>&1; then echo "VERIFY_RC=0"; else echo "VERIFY_RC=$?"; fi\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEPLOY_RC=0", result.stdout)
        self.assertNotIn("VERIFY_RC=0", result.stdout)

    def test_verify_only_rejects_dirty_source(self):
        result = self.probe(
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1\n'
            'echo "DEPLOY_RC=$?"\n'
            'printf dirty > "$SRC/src/untracked-dirt"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" --verify-only >/dev/null 2>&1; then echo "VERIFY_RC=0"; else echo "VERIFY_RC=$?"; fi\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEPLOY_RC=0", result.stdout)
        self.assertNotIn("VERIFY_RC=0", result.stdout)

    def test_symlink_destinations_refused(self):
        # Sequential scenarios; each refusal must leave the canary untouched
        # (proves no write-through of any symlink).
        body = (
            'mkdir -p "$HOME_DIR/.local" "$HOME_DIR/.cache"\n'
            'printf canary > "$T/canary.txt"\n'
            'mkdir -p "$HOME_DIR/.local/bin" "$HOME_DIR/.cache/ai-resource-hud"\n'
            'ln -s "$T/canary.txt" "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "SYMLINK_COLLECTOR_RC=0"; else echo "SYMLINK_COLLECTOR_RC=$?"; fi\n'
            'rm "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'ln -s "$T/canary.txt" "$HOME_DIR/.local/bin/ai-resource-hud-menu"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "SYMLINK_HELPER_RC=0"; else echo "SYMLINK_HELPER_RC=$?"; fi\n'
            'rm "$HOME_DIR/.local/bin/ai-resource-hud-menu"\n'
            'ln -s "$T/canary.txt" "$HOME_DIR/.cache/ai-resource-hud/install.json"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "SYMLINK_MANIFEST_RC=0"; else echo "SYMLINK_MANIFEST_RC=$?"; fi\n'
            'rm "$HOME_DIR/.cache/ai-resource-hud/install.json"\n'
            'rmdir "$HOME_DIR/.local/bin"\n'
            'ln -s "$T" "$HOME_DIR/.local/bin"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "SYMLINK_BINDIR_RC=0"; else echo "SYMLINK_BINDIR_RC=$?"; fi\n'
            'rm "$HOME_DIR/.local/bin"\n'
            'mkdir -p "$HOME_DIR/.local/bin"\n'
            'rmdir "$HOME_DIR/.cache/ai-resource-hud"\n'
            'ln -s "$T" "$HOME_DIR/.cache/ai-resource-hud"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "SYMLINK_CACHEDIR_RC=0"; else echo "SYMLINK_CACHEDIR_RC=$?"; fi\n'
            'test "$(cat "$T/canary.txt")" = canary && echo CANARY_INTACT || echo CANARY_CHANGED\n'
        )
        result = self.probe(body)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for marker in ("SYMLINK_COLLECTOR_RC=", "SYMLINK_HELPER_RC=", "SYMLINK_MANIFEST_RC=",
                       "SYMLINK_BINDIR_RC=", "SYMLINK_CACHEDIR_RC="):
            line = next(l for l in result.stdout.splitlines() if l.startswith(marker))
            self.assertNotEqual(line, marker + "0", msg=line)
        self.assertIn("CANARY_INTACT", result.stdout)
        self.assertNotIn("CANARY_CHANGED", result.stdout)

    def test_dirty_sources_refused_before_install(self):
        result = self.probe(
            'mkdir -p "$HOME_DIR/.local/bin"\n'
            'printf old-collector > "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'printf tracked-dirty >> "$SRC/src/ai-resource-hud"\n'
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" 2>&1 | grep -qi dirty && echo TRACKED_DIRTY_REFUSED || echo TRACKED_DIRTY_ALLOWED\n'
            'git -C "$SRC" checkout -q -- src/ai-resource-hud\n'
            'printf staged-dirty >> "$SRC/src/ai-resource-hud"\n'
            'git -C "$SRC" add -A\n'
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" 2>&1 | grep -qi dirty && echo STAGED_DIRTY_REFUSED || echo STAGED_DIRTY_ALLOWED\n'
            'git -C "$SRC" reset -q\n'
            'git -C "$SRC" checkout -q -- src/ai-resource-hud\n'
            'printf untracked > "$SRC/src/untracked-tool"\n'
            '"$DEPLOY" --home "$HOME_DIR" --source "$SRC" 2>&1 | grep -qi dirty && echo UNTRACKED_DIRTY_REFUSED || echo UNTRACKED_DIRTY_ALLOWED\n'
            'rm "$SRC/src/untracked-tool"\n'
            'test "$(cat "$HOME_DIR/.local/bin/ai-resource-hud")" = old-collector && echo REFUSALS_UNTOUCHED_LIVE || echo REFUSALS_CHANGED_LIVE\n'
            'printf "*.log\\n" > "$SRC/.gitignore"\n'
            'git -C "$SRC" add -A\n'
            'git -c user.email=fixture@example.test -c user.name=fixture -C "$SRC" commit -qm ignore-logs\n'
            'printf ignored-content > "$SRC/debug.log"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "IGNORED_ALLOWED_RC=0"; else echo "IGNORED_ALLOWED_RC=$?"; fi\n'
            'test "$(cat "$HOME_DIR/.local/bin/ai-resource-hud")" = old-collector && echo LIVE_STILL_OLD || echo LIVE_CHANGED\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Refusals must precede any install: the primed live collector survives
        # until the ignored-file case performs the one allowed deployment.
        self.assertIn("TRACKED_DIRTY_REFUSED", result.stdout)
        self.assertNotIn("TRACKED_DIRTY_ALLOWED", result.stdout)
        self.assertIn("STAGED_DIRTY_REFUSED", result.stdout)
        self.assertNotIn("STAGED_DIRTY_ALLOWED", result.stdout)
        self.assertIn("UNTRACKED_DIRTY_REFUSED", result.stdout)
        self.assertNotIn("UNTRACKED_DIRTY_ALLOWED", result.stdout)
        self.assertIn("REFUSALS_UNTOUCHED_LIVE", result.stdout)
        self.assertNotIn("REFUSALS_CHANGED_LIVE", result.stdout)
        self.assertIn("IGNORED_ALLOWED_RC=0", result.stdout)
        self.assertIn("LIVE_CHANGED", result.stdout)

    def test_fifo_and_directory_destinations_refused(self):
        result = self.probe(
            'mkdir -p "$HOME_DIR/.local/bin" "$HOME_DIR/.cache/ai-resource-hud"\n'
            'printf canary > "$T/canary.txt"\n'
            'mkfifo "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "FIFO_RC=0"; else echo "FIFO_RC=$?"; fi\n'
            'test -p "$HOME_DIR/.local/bin/ai-resource-hud" && echo FIFO_INTACT || echo FIFO_GONE\n'
            'rm "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'mkdir "$HOME_DIR/.local/bin/ai-resource-hud"\n'
            'printf nested > "$HOME_DIR/.local/bin/ai-resource-hud/nested.txt"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "DIR_RC=0"; else echo "DIR_RC=$?"; fi\n'
            'test -d "$HOME_DIR/.local/bin/ai-resource-hud" && echo DIR_INTACT || echo DIR_GONE\n'
            'test "$(cat "$HOME_DIR/.local/bin/ai-resource-hud/nested.txt")" = nested && echo NESTED_INTACT || echo NESTED_GONE\n'
            'test "$(cat "$T/canary.txt")" = canary && echo CANARY_INTACT || echo CANARY_CHANGED\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("FIFO_RC=0", result.stdout)
        self.assertNotIn("DIR_RC=0", result.stdout)
        for marker in ("FIFO_INTACT", "DIR_INTACT", "NESTED_INTACT", "CANARY_INTACT"):
            self.assertIn(marker, result.stdout)

    def test_parent_symlinks_refused_without_escape(self):
        result = self.probe(
            'mkdir -p "$T/outside-local" "$T/outside-cache"\n'
            'printf outside-local > "$T/outside-local/canary.txt"\n'
            'printf outside-cache > "$T/outside-cache/canary.txt"\n'
            'ln -s "$T/outside-local" "$HOME_DIR/.local"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "LOCAL_RC=0"; else echo "LOCAL_RC=$?"; fi\n'
            'rm "$HOME_DIR/.local"\n'
            'ln -s "$T/outside-cache" "$HOME_DIR/.cache"\n'
            'if "$DEPLOY" --home "$HOME_DIR" --source "$SRC" >/dev/null 2>&1; then echo "CACHE_RC=0"; else echo "CACHE_RC=$?"; fi\n'
            'rm "$HOME_DIR/.cache"\n'
            'test "$(cat "$T/outside-local/canary.txt")" = outside-local && echo LOCAL_CANARY_INTACT || echo LOCAL_CANARY_CHANGED\n'
            'test "$(cat "$T/outside-cache/canary.txt")" = outside-cache && echo CACHE_CANARY_INTACT || echo CACHE_CANARY_CHANGED\n'
            'test "$(ls "$T/outside-local")" = canary.txt && echo LOCAL_NO_LEAK || echo LOCAL_LEAK\n'
            'test "$(ls "$T/outside-cache")" = canary.txt && echo CACHE_NO_LEAK || echo CACHE_LEAK\n'
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("LOCAL_RC=0", result.stdout)
        self.assertNotIn("CACHE_RC=0", result.stdout)
        for marker in ("LOCAL_CANARY_INTACT", "CACHE_CANARY_INTACT",
                       "LOCAL_NO_LEAK", "CACHE_NO_LEAK"):
            self.assertIn(marker, result.stdout)

    def test_manifest_path_has_no_typo_namespace(self):
        # The runtime assertion (NO_TYPO_PATH) proves behavior; this static
        # guard pins the single correct namespace in product files. The test
        # file itself is excluded: it must name the typo path to assert its
        # absence at runtime.
        for path in (DEPLOY_SCRIPT, REPO_ROOT / "src" / "ai-resource-hud",
                     REPO_ROOT / "README.md", REPO_ROOT / "docs" / "security.md"):
            text = pathlib.Path(path).read_text(encoding="utf-8")
            self.assertNotIn(".cache/ai-resource-hub", text, msg=str(path))
        self.assertIn(".cache/ai-resource-hud",
                      DEPLOY_SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
