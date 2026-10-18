"""Regression tests for the Windows service launcher's port replacement flow.

All network/process operations are mocked; running this suite never stops or
starts a real service.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

from scripts import start_services as launcher


class ListenerTests(unittest.TestCase):
    def test_only_exact_local_tcp_listeners_are_selected(self):
        output = """
Active Connections
  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:5181            0.0.0.0:0              LISTENING       110
  TCP    [::]:5181               [::]:0                 LISTENING       110
  TCP    127.0.0.1:5181          0.0.0.0:0              LISTENING       220
  TCP    [::1]:5181              [::]:0                 LISTENING       330
  TCP    0.0.0.0:15181           0.0.0.0:0              LISTENING       440
  TCP    127.0.0.1:51810         0.0.0.0:0              LISTENING       441
  TCP    127.0.0.1:5181          127.0.0.1:60200        ESTABLISHED     550
  TCP    127.0.0.1:5181          127.0.0.1:60201        TIME_WAIT       0
  TCP    127.0.0.1:60202         127.0.0.1:5181         ESTABLISHED     660
  UDP    0.0.0.0:5181            *:*                                    770
  TCP    bad-address            0.0.0.0:0              LISTENING       880
  TCP    127.0.0.1:5181          0.0.0.0:0              LISTENING       bad-pid
"""
        result = subprocess.CompletedProcess(["netstat", "-ano"], 0, output, "")
        with patch.object(launcher.subprocess, "run", return_value=result) as run:
            self.assertEqual(launcher.listener_pids(5181), {110, 220, 330})
        self.assertEqual(run.call_args.args[0], ["netstat", "-ano"])

    def test_localized_listener_state_accepts_only_wildcard_foreign_endpoint(self):
        output = """
  TCP    0.0.0.0:5181            0.0.0.0:0              侦听          110
  TCP    [::]:5181               [::]:0                 侦听          220
  TCP    127.0.0.1:5181          127.0.0.1:60000        UNKNOWN         330
"""
        result = subprocess.CompletedProcess(["netstat", "-ano"], 0, output, "")
        with patch.object(launcher.subprocess, "run", return_value=result):
            self.assertEqual(launcher.listener_pids(5181), {110, 220})

    def test_netstat_failure_is_reported_instead_of_treating_port_as_free(self):
        result = subprocess.CompletedProcess(["netstat", "-ano"], 1, "", "failed")
        with patch.object(launcher.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError):
                launcher.listener_pids(5181)


class ReleasePortTests(unittest.TestCase):
    def test_free_port_does_not_invoke_taskkill(self):
        with (
            patch.object(launcher, "listener_pids", return_value=set()),
            patch.object(launcher.subprocess, "run") as run,
        ):
            launcher.release_port(5181)
        run.assert_not_called()

    def test_kills_each_listener_process_tree_and_verifies_release(self):
        active = {110, 220}

        def kill(argv, **_kwargs):
            self.assertEqual(argv[0], "taskkill")
            self.assertIn("/T", argv)
            self.assertIn("/F", argv)
            active.remove(int(argv[argv.index("/PID") + 1]))
            return subprocess.CompletedProcess(argv, 0, "", "")

        with (
            patch.object(launcher, "listener_pids", side_effect=lambda _port: active.copy()) as listeners,
            patch.object(launcher.subprocess, "run", side_effect=kill) as run,
            redirect_stdout(io.StringIO()),
        ):
            launcher.release_port(5181)
        self.assertEqual(active, set())
        self.assertEqual(run.call_count, 2)
        self.assertGreater(listeners.call_count, 2)
        self.assertTrue(all(args == call(5181) for args in listeners.call_args_list))

    def test_does_not_kill_listener_that_disappeared_before_recheck(self):
        with (
            patch.object(launcher, "listener_pids", side_effect=[{110}, set(), set()]),
            patch.object(launcher.subprocess, "run") as run,
        ):
            launcher.release_port(5181)
        run.assert_not_called()

    def test_refuses_system_and_launcher_pids(self):
        for pid in (0, 1, 4, os.getpid()):
            with self.subTest(pid=pid):
                with (
                    patch.object(launcher, "listener_pids", return_value={pid}),
                    patch.object(launcher.subprocess, "run") as run,
                ):
                    with self.assertRaises(RuntimeError):
                        launcher.release_port(5181)
                run.assert_not_called()

    def test_failed_taskkill_is_reported_when_process_still_listens(self):
        result = subprocess.CompletedProcess(["taskkill"], 1, "", "access denied")
        with (
            patch.object(launcher, "listener_pids", return_value={110}),
            patch.object(launcher.subprocess, "run", return_value=result),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(RuntimeError):
                launcher.release_port(5181)

    def test_failed_taskkill_is_harmless_if_listener_already_exited(self):
        active = {110}

        def kill(argv, **_kwargs):
            active.clear()
            return subprocess.CompletedProcess(argv, 1, "", "process not found")

        with (
            patch.object(launcher, "listener_pids", side_effect=lambda _port: active.copy()),
            patch.object(launcher.subprocess, "run", side_effect=kill),
            redirect_stdout(io.StringIO()),
        ):
            launcher.release_port(5181)

    def test_waits_for_listener_to_disappear_after_successful_taskkill(self):
        killed = False
        observations_after_kill = 0

        def listeners(_port):
            nonlocal observations_after_kill
            if killed:
                observations_after_kill += 1
            return set() if observations_after_kill >= 2 else {110}

        def kill(argv, **_kwargs):
            nonlocal killed
            killed = True
            return subprocess.CompletedProcess(argv, 0, "", "")

        with (
            patch.object(launcher, "listener_pids", side_effect=listeners),
            patch.object(launcher.subprocess, "run", side_effect=kill) as run,
            patch.object(launcher.time, "sleep") as sleep,
            redirect_stdout(io.StringIO()),
        ):
            launcher.release_port(5181)
        self.assertEqual(run.call_count, 1)
        sleep.assert_called()

    def test_reports_timeout_when_port_remains_occupied(self):
        ticks = iter((0, 1000))
        result = subprocess.CompletedProcess(["taskkill"], 0, "", "")
        with (
            patch.object(launcher, "listener_pids", return_value={110}),
            patch.object(launcher.subprocess, "run", return_value=result),
            patch.object(launcher.time, "monotonic", side_effect=lambda: next(ticks, 1000)),
            patch.object(launcher.time, "sleep"),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(RuntimeError):
                launcher.release_port(5181)


class StartupTests(unittest.TestCase):
    def test_environment_failure_precedes_any_port_release(self):
        with (
            patch.object(launcher, "startup_lock", return_value=nullcontext()),
            patch.object(launcher, "child_environment", side_effect=RuntimeError("missing .env")),
            patch.object(launcher, "command"),
            patch.object(launcher, "release_port") as release,
            patch.object(launcher.subprocess, "Popen") as popen,
        ):
            with self.assertRaisesRegex(RuntimeError, "missing .env"):
                launcher.start_services()
        release.assert_not_called()
        popen.assert_not_called()

    def test_both_commands_are_checked_before_any_port_release(self):
        def command(name):
            if name == "web":
                raise RuntimeError("missing web dependencies")
            return [name], launcher.ROOT

        with (
            patch.object(launcher, "startup_lock", return_value=nullcontext()),
            patch.object(launcher, "child_environment", return_value={}),
            patch.object(launcher, "command", side_effect=command) as commands,
            patch.object(launcher, "release_port") as release,
            patch.object(launcher.subprocess, "Popen") as popen,
        ):
            with self.assertRaisesRegex(RuntimeError, "missing web dependencies"):
                launcher.start_services()
        self.assertEqual(commands.call_args_list, [call("api"), call("web")])
        release.assert_not_called()
        popen.assert_not_called()

    def test_healthy_services_are_replaced_only_after_all_preflight_checks(self):
        events = []
        environment = {"TEST_ENV": "present"}

        def command(name):
            events.append(f"command:{name}")
            return [name], launcher.ROOT

        def release(port):
            events.append(f"release:{port}")

        def spawn(argv, **kwargs):
            events.append(f"spawn:{argv[0]}")
            self.assertIs(kwargs["env"], environment)
            return Mock(pid=110 if argv[0] == "api" else 220, poll=Mock(return_value=None))

        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            with (
                patch.object(launcher, "STATE_DIR", state_dir),
                patch.object(launcher, "METADATA", state_dir / "services.json"),
                patch.object(launcher, "startup_lock", return_value=nullcontext()),
                patch.object(launcher, "child_environment", return_value=environment),
                patch.object(launcher, "command", side_effect=command),
                patch.object(launcher, "release_port", side_effect=release),
                patch.object(launcher, "probe", return_value=("ready", "healthy")),
                patch.object(launcher.subprocess, "Popen", side_effect=spawn) as popen,
                patch.object(launcher, "write_metadata") as metadata,
                redirect_stdout(io.StringIO()),
            ):
                launcher.start_services()
        self.assertEqual(events, [
            "command:api", "command:web", "release:8008", "release:5181", "spawn:api", "spawn:web",
        ])
        self.assertEqual(popen.call_count, 2)
        final_records = metadata.call_args.args[0]
        self.assertEqual({record["action"] for record in final_records.values()}, {"started"})
        self.assertEqual({record["state"] for record in final_records.values()}, {"ready"})


class CommandLineTests(unittest.TestCase):
    def test_check_is_read_only_and_reports_ready_status(self):
        with (
            patch.object(launcher.sys, "argv", ["start_services.py", "--check"]),
            patch.object(launcher, "probe", return_value=("ready", "healthy")) as probe,
            patch.object(launcher, "startup_lock") as lock,
            patch.object(launcher, "release_port") as release,
            patch.object(launcher, "start_services") as start,
            patch.object(launcher, "write_metadata") as metadata,
            patch.object(launcher.subprocess, "run") as run,
            patch.object(launcher.subprocess, "Popen") as popen,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(launcher.main(), 0)
        self.assertEqual(probe.call_args_list, [call("api"), call("web")])
        for operation in (lock, release, start, metadata, run, popen):
            operation.assert_not_called()

    def test_check_returns_failure_for_unready_service(self):
        with (
            patch.object(launcher.sys, "argv", ["start_services.py", "--check"]),
            patch.object(launcher, "probe", side_effect=[("ready", "healthy"), ("unready", "HTTPError")]),
            patch.object(launcher, "release_port") as release,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(launcher.main(), 1)
        release.assert_not_called()

    def test_release_helper_does_not_start_services(self):
        with (
            patch.object(launcher.sys, "argv", ["start_services.py", "--release-port", "5181"]),
            patch.object(launcher, "startup_lock", return_value=nullcontext()) as lock,
            patch.object(launcher, "release_port") as release,
            patch.object(launcher, "start_services") as start,
        ):
            self.assertEqual(launcher.main(), 0)
        lock.assert_called_once_with()
        release.assert_called_once_with(5181)
        start.assert_not_called()

    def test_release_helper_does_not_release_port_when_startup_lock_is_held(self):
        with (
            patch.object(launcher.sys, "argv", ["start_services.py", "--release-port", "5181"]),
            patch.object(launcher, "startup_lock") as lock,
            patch.object(launcher, "release_port") as release,
            patch.object(launcher, "start_services") as start,
            redirect_stderr(io.StringIO()),
        ):
            lock.return_value.__enter__.side_effect = RuntimeError("Another startup is in progress")
            self.assertEqual(launcher.main(), 1)
        lock.assert_called_once_with()
        release.assert_not_called()
        start.assert_not_called()

    def test_invalid_or_conflicting_arguments_do_not_mutate_services(self):
        cases = (
            ["--release-port", "0"],
            ["--release-port", "65536"],
            ["--release-port", "-1"],
            ["--release-port", "abc"],
            ["--check", "--release-port", "5181"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with (
                    patch.object(launcher.sys, "argv", ["start_services.py", *arguments]),
                    patch.object(launcher, "release_port") as release,
                    patch.object(launcher, "start_services") as start,
                    redirect_stderr(io.StringIO()),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        launcher.main()
                self.assertEqual(raised.exception.code, 2)
                release.assert_not_called()
                start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
