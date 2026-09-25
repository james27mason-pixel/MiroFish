"""Runtime compatibility and low-memory fixes for MiroFish simulation workers."""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import sys
from typing import Any

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
            for chunk in data.splitlines(keepends=True):
                if self._line_start and chunk:
                    self.mirror.write(self.prefix)
                self.mirror.write(chunk)
                self._line_start = chunk.endswith("\n") or chunk.endswith("\r")
            self.mirror.flush()
        except Exception:
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
    if os.name != "posix" or os.environ.get("MIROFISH_MIRROR_WORKER_LOGS", "1") == "0":
        return
    if getattr(sys.stdout, "_mirofish_render_tee", False):
        return
    try:
        mirror = open(f"/proc/{os.getppid()}/fd/1", "w", encoding="utf-8", buffering=1)
        stdout_tee = _TeeStream(sys.stdout, mirror)
        stderr_tee = _TeeStream(sys.stderr, mirror, "[MIROFISH-WORKER:ERR] ")
        stdout_tee._mirofish_render_tee = True
        stderr_tee._mirofish_render_tee = True
        sys.stdout = stdout_tee
        sys.stderr = stderr_tee
        print(f"[diagnostics] worker log mirroring enabled; pid={os.getpid()} parent_pid={os.getppid()}", flush=True)
    except Exception as exc:
        try:
            sys.stderr.write(f"[diagnostics] worker log mirroring unavailable: {exc}\n")
        except Exception:
            pass


def _install_camel_platform_fallback() -> None:
    try:
        from camel.models import ModelFactory
        from camel.types import ModelPlatformType
    except Exception:
        return
    compatible_platform = getattr(ModelPlatformType, "OPENAI_COMPATIBLE_MODEL", None)
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
            if "invalid platform" not in str(exc).lower():
                raise
            requested_platform = kwargs.get("model_platform")
            positional = list(args)
            if requested_platform is None and positional:
                requested_platform = positional[0]
            if requested_platform != openai_platform:
                raise
            logger.warning("CAMEL rejected strict OpenAI platform; retrying with OPENAI_COMPATIBLE_MODEL")
            retry_kwargs = dict(kwargs)
            if "model_platform" in retry_kwargs:
                retry_kwargs["model_platform"] = compatible_platform
            elif positional:
                positional[0] = compatible_platform
            else:
                retry_kwargs["model_platform"] = compatible_platform
            return original_create(*positional, **retry_kwargs)

    create_with_platform_fallback._mirofish_platform_fallback = True
    ModelFactory.create = create_with_platform_fallback


def _low_memory_enabled() -> bool:
    explicit = os.getenv("MIROFISH_LOW_MEMORY")
    if explicit is not None:
        return explicit.strip().lower() not in {"0", "false", "no", "off"}
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes"}


def _install_low_memory_platform_runner() -> None:
    """Avoid holding two complete OASIS worlds in RAM on Render Free.

    Only the top-level Twitter+Reddit gather is serialized. OASIS' own gather
    calls are untouched. After the first platform finishes, its persisted logs
    and DB remain, but its in-memory env/graph are closed and released before
    the second platform is constructed.
    """
    if not _low_memory_enabled():
        return

    original_gather = asyncio.gather

    def coro_name(value: Any) -> str:
        return getattr(getattr(value, "cr_code", None), "co_name", "")

    async def sequential_platform_pair(first, second):
        first_result = await first
        env = getattr(first_result, "env", None)
        if env is not None:
            try:
                await env.close()
            except Exception as exc:
                logger.warning("Low-memory cleanup could not close first env: %s", exc)
        try:
            first_result.env = None
            first_result.agent_graph = None
        except Exception:
            pass
        gc.collect()
        print("[memory] first platform released before starting second platform", flush=True)
        second_result = await second
        return [first_result, second_result]

    def low_memory_gather(*aws, **kwargs):
        names = [coro_name(item) for item in aws]
        if len(aws) == 2 and set(names) == {"run_twitter_simulation", "run_reddit_simulation"}:
            print("[memory] Render low-memory mode: platforms will run sequentially", flush=True)
            return sequential_platform_pair(aws[0], aws[1])
        return original_gather(*aws, **kwargs)

    asyncio.gather = low_memory_gather
    gc.set_threshold(350, 5, 5)


_install_render_log_mirror()
_install_camel_platform_fallback()
_install_low_memory_platform_runner()
