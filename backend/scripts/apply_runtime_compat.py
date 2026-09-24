"""Apply idempotent runtime compatibility fixes before the backend starts.

Render can run this repository as a native service, in which case Dockerfile
build-time patches are never executed. Keep compatibility fixes here too so
both native and Docker deployments run identical simulation code.

IMPORTANT: this script must never prevent the web service from booting merely
because a source patch has already been applied or the upstream source changed
slightly. Each fix therefore accepts both the original and patched forms.
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def replace_if_present(path: Path, old: str, new: str, label: str) -> bool:
    """Apply a compatibility replacement when required.

    Returns True when the desired code is present after this call. A missing
    exact source pattern is reported but is not fatal; this keeps Render from
    crash-looping during startup when the repository has already incorporated
    an equivalent fix.
    """
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"runtime compat: {label} already applied")
        return True
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        print(f"runtime compat: applied {label}")
        return True
    print(f"runtime compat: {label} exact pattern not found; leaving source unchanged")
    return False


runner = BACKEND / "scripts" / "run_parallel_simulation.py"
api = BACKEND / "app" / "api" / "simulation.py"

# CAMEL/OpenAI routing. The repository may contain either the upstream OPENAI
# form or an already-patched OPENAI_COMPATIBLE_MODEL form.
old_model = """    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI,\n        model_type=llm_model,\n    )"""
new_model = """    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,\n        model_type=llm_model,\n        url=llm_base_url or \"https://api.openai.com/v1\",\n        api_key=llm_api_key or os.environ.get(\"OPENAI_API_KEY\"),\n    )"""
replace_if_present(runner, old_model, new_model, "CAMEL OpenAI-compatible model routing")

# OASIS can expose DefaultPlatformType through different import identities
# across releases. Use the enum from oasis.social_platform.typing explicitly.
exact_enum = '__import__("oasis.social_platform.typing", fromlist=["DefaultPlatformType"]).DefaultPlatformType'
replace_if_present(
    runner,
    "platform=oasis.DefaultPlatformType.TWITTER",
    f"platform={exact_enum}.TWITTER",
    "OASIS Twitter platform enum identity",
)
replace_if_present(
    runner,
    "platform=oasis.DefaultPlatformType.REDDIT",
    f"platform={exact_enum}.REDDIT",
    "OASIS Reddit platform enum identity",
)

# Step 3 is always the dual-world simulation. Normalise stale/invalid browser
# platform values server-side rather than returning HTTP 400.
replace_if_present(
    api,
    "platform = data.get('platform', 'parallel')",
    "platform = 'parallel'  # Step 3 always runs the dual-world simulation",
    "Step 3 server-side platform normalization",
)

print("runtime compat: startup compatibility pass complete")
