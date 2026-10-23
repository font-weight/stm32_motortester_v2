"""Reproduce two unrelated legacy expectations with pre-change HEAD methods.

This is a method-level baseline comparison, not a claim to run the whole old
checkout. The current test body and other current modules remain in use.
"""
import ast
import subprocess
import textwrap
import unittest
from motortester.stream_session import StreamSession
from motortester.v2.stream_device import StreamDeviceBridge

print("HEAD", subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
for path, cls, method in (
    ("host/motortester/stream_session.py", StreamSession, "snapshot"),
    ("host/motortester/v2/stream_device.py", StreamDeviceBridge, "start_live"),
):
    src = subprocess.check_output(["git", "show", "HEAD:" + path], text=True, encoding="utf-8")
    node = next(n for c in ast.parse(src).body if isinstance(c, ast.ClassDef)
                and c.name == cls.__name__ for n in c.body
                if isinstance(n, ast.FunctionDef) and n.name == method)
    code = textwrap.dedent("\n".join(src.splitlines()[node.lineno - 1:node.end_lineno]))
    namespace = dict(getattr(cls, method).__globals__)
    exec(code, namespace)
    setattr(cls, method, namespace[method])
suite = unittest.defaultTestLoader.loadTestsFromNames([
    "test_stream_session.BoundaryTests.test_received_queued_accepted_checkpointed_finalized_are_distinct",
    "test_v2_stream_device.V2StreamDeviceTests.test_direct_record_unknown_tail_preserves_prefix_and_blocks_restart",
])
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
