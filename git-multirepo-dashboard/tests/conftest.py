"""Shared test configuration."""
import resource

# The test suite creates many TestClient instances across ~14 test files,
# each holding open file descriptors for ASGI transport. By test ~59,
# the default macOS soft limit (256) is exhausted, causing OSError: [Errno 24]
# Too many open files when a test spawns a subprocess.
# Raise the soft limit to the hard limit to prevent flaky failures.
_soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
if _soft < hard:
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(hard, 8192), hard))
