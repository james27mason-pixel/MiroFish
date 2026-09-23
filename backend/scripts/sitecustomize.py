"""Runtime compatibility fixes for MiroFish simulation scripts.

Python imports ``sitecustomize`` automatically during interpreter startup when
this directory is on ``sys.path``.  The OASIS simulation scripts are executed
from ``backend/scripts``, so this hook applies to the parallel, Twitter and
Reddit runners without changing their persisted simulation data.

CAMEL 0.2.x can reject an otherwise valid OpenAI model/base-URL combination
with ``ValueError: Invalid platform`` when it is created through the strict
``ModelPlatformType.OPENAI`` adapter.  MiroFish supports OpenAI-compatible
configuration, so retry that *specific* failure through CAMEL's compatible
adapter.  All other exceptions are left untouched.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("mirofish.camel_compat")


def _install_camel_platform_fallback() -> None:
    try:
        from camel.models import ModelFactory
        from camel.types import ModelPlatformType
    except Exception:
        # Do not make interpreter startup depend on optional simulation
        # dependencies.  The runner will report the normal import error later.
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
            # simulation.  Never mask authentication, quota, model, network or
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


_install_camel_platform_fallback()
