"""Apply idempotent runtime compatibility fixes before the backend starts.

Render can run this repository as a native service, in which case Dockerfile
build-time patches are never executed. Keep the compatibility fixes here too so
both native and Docker deployments run identical simulation code.
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"runtime compat: {label} already applied")
        return
    if old not in text:
        raise RuntimeError(f"runtime compat: cannot locate {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"runtime compat: applied {label}")


runner = BACKEND / "scripts" / "run_parallel_simulation.py"
api = BACKEND / "app" / "api" / "simulation.py"

replace_once(
    runner,
    """    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI,\n        model_type=llm_model,\n    )""",
    """    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,\n        model_type=llm_model,\n        url=llm_base_url or \"https://api.openai.com/v1\",\n        api_key=llm_api_key or os.environ.get(\"OPENAI_API_KEY\"),\n    )""",
    "CAMEL OpenAI-compatible model routing",
)

exact_enum = '__import__("oasis.social_platform.typing", fromlist=["DefaultPlatformType"]).DefaultPlatformType'
replace_once(
    runner,
    "platform=oasis.DefaultPlatformType.TWITTER",
    f"platform={exact_enum}.TWITTER",
    "OASIS Twitter platform enum identity",
)
replace_once(
    runner,
    "platform=oasis.DefaultPlatformType.REDDIT",
    f"platform={exact_enum}.REDDIT",
    "OASIS Reddit platform enum identity",
)

replace_once(
    api,
    "platform = data.get('platform', 'parallel')",
    "platform = 'parallel'  # Step 3 always runs the dual-world simulation",
    "Step 3 server-side platform normalization",
)

print("runtime compat: all simulation startup fixes are active")
