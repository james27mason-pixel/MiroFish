"""Runtime compatibility fixes for MiroFish simulation scripts.

Python imports ``sitecustomize`` automatically during interpreter startup when
this directory is on ``sys.path``. The OASIS simulation scripts are executed
from ``backend/scripts``, so this hook applies to the parallel, Twitter and
Reddit runners without changing their persisted simulation data.

This module also mirrors worker stdout/stderr to the parent web process stdout
on Linux. SimulationRunner still writes the worker output to simulation.log,
but the same lines are now visible in Render's Application Logs, giving us one
copy/pasteable diagnostic stream for Flask + MiroFish/OASIS worker output.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("mirofish.camel_compat")


class _TeeStream:
    """Write to the normal simulation log and a second diagnostic stream."""

    def __init__(self, primary, mirror, prefix: str = "[MIROFISH-WORKER] "):
        self.primary = primary
        self.mirror = mirror
        self.prefix = prefix
        self._line_start = True

    def write(self, data):
        if not data:
            return 0
        written = self.primary.write(data)
        try:
            # Prefix each physical line so worker output is easy to find/copy
            # among Render's HTTP access logs.
            chunks = data.splitlines(keepends=True)
            for chunk in chunks:
                if self._line_start and chunk:
                    self.mirror.write(self.prefix)
                self.mirror.write(chunk)
                self._line_start = chunk.endswith("\n") or chunk.endswith("\r")
            self.mirror.flush()
        except Exception:
            # Logging must never be able to break a simulation.
            pass
        return written

    def flush(self):
        try:
            self.primary.flush()
        finally:
            try:
                self.mirror.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    @property
    def encoding(self):
        return getattr(self.primary, "encoding", "utf-8")

    def fileno(self):
        return self.primary.fileno()

    def __getattr__(self, name):
        return getattr(self.primary, name)


def _install_render_log_mirror() -> None:
    """Mirror simulation stdout/stderr into the parent service log stream."""
    if os.name != "posix" or os.environ.get("MIROFISH_MIRROR_WORKER_LOGS", "1") == "0":
        return
    if getattr(sys.stdout, "_mirofish_render_tee", False):
        return

    parent_stdout = f"/proc/{os.getppid()}/fd/1"
    try:
        # line-buffered text stream; do not close it explicitly because it is a
        # duplicate handle to the parent service's logging destination.
        mirror = open(parent_stdout, "w", encoding="utf-8", buffering=1)
        stdout_tee = _TeeStream(sys.stdout, mirror)
        stderr_tee = _TeeStream(sys.stderr, mirror, "[MIROFISH-WORKER:ERR] ")
        stdout_tee._mirofish_render_tee = True
        stderr_tee._mirofish_render_tee = True
        sys.stdout = stdout_tee
        sys.stderr = stderr_tee
        print(
            f"[diagnostics] worker log mirroring enabled; pid={os.getpid()} "
            f"parent_pid={os.getppid()}",
            flush=True,
        )
    except Exception as exc:
        # Render/Linux normally supports /proc. Local/macOS/Windows development
        # may not; in that case preserve the existing simulation.log behaviour.
        try:
            sys.stderr.write(
                f"[diagnostics] worker log mirroring unavailable: {exc}\n"
            )
            sys.stderr.flush()
        except Exception:
            pass


def _install_camel_platform_fallback() -> None:
    try:
        from camel.models import ModelFactory
        from camel.types import ModelPlatformType
    except Exception:
        # Do not make interpreter startup depend on optional simulation
        # dependencies. The runner will report the normal import error later.
        return

    compatible_platform = getattr(
        ModelPlatformType, "OPENAI_COMPATIBLE_MODEL", None
    )
    openai_platform = getattr(ModelPlatformType, "OPENAI", None)
    if compatible_platform is None or openai_platform is None:
        return

    original_create = ModelFactory.create
    if getattr(original_create, "_mirofish_platform_fallback", False):
        return

    def create_with_platform_fallback(*args, **kwargs):
        try:
            return original_create(*args, **kwargs)
        except ValueError as exc:
            # Only handle the exact failure seen when OASIS starts the MiroFish
            # simulation. Never mask authentication, quota, model, network or
            # unrelated configuration errors.
            if "invalid platform" not in str(exc).lower():
                raise

            requested_platform = kwargs.get("model_platform")
            positional = list(args)
            if requested_platform is None and positional:
                requested_platform = positional[0]

            if requested_platform != openai_platform:
                raise

            logger.warning(
                "CAMEL rejected the strict OpenAI platform; retrying with "
                "OPENAI_COMPATIBLE_MODEL"
            )

            retry_kwargs = dict(kwargs)
            retry_args = positional
            if "model_platform" in retry_kwargs:
                retry_kwargs["model_platform"] = compatible_platform
            elif retry_args:
                retry_args[0] = compatible_platform
            else:
                retry_kwargs["model_platform"] = compatible_platform

            return original_create(*retry_args, **retry_kwargs)

    create_with_platform_fallback._mirofish_platform_fallback = True
    ModelFactory.create = create_with_platform_fallback


_install_render_log_mirror()
_install_camel_platform_fallback()
