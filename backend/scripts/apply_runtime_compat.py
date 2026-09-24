"""Apply idempotent runtime compatibility fixes before the backend starts.

Render can run this repository as a native service, in which case Dockerfile
build-time patches are never executed. Keep compatibility fixes here too so
both native and Docker deployments run identical simulation code.

This pass is deliberately idempotent: it is safe when Docker already applied
some or all of the same fixes.
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def replace_if_present(path: Path, old: str, new: str, label: str, *, all_occurrences: bool = False) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text and (not all_occurrences or old not in text):
        print(f"runtime compat: {label} already applied", flush=True)
        return True
    if old in text:
        text = text.replace(old, new) if all_occurrences else text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")
        print(f"runtime compat: applied {label}", flush=True)
        return True
    print(f"runtime compat: {label} exact pattern not found; leaving source unchanged", flush=True)
    return False


runner = BACKEND / "scripts" / "run_parallel_simulation.py"
api = BACKEND / "app" / "api" / "simulation.py"

# CAMEL/OpenAI routing. Passing the URL and key explicitly avoids relying on
# CAMEL/OpenAI environment-variable interpretation in the child process.
old_model = """    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI,\n        model_type=llm_model,\n    )"""
new_model = """    print(f\"[startup] creating CAMEL model: label={config_label}, model={llm_model}, key_present={bool(llm_api_key or os.environ.get('OPENAI_API_KEY'))}, base_url={llm_base_url or 'https://api.openai.com/v1'}\", flush=True)\n    model = ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,\n        model_type=llm_model,\n        url=llm_base_url or \"https://api.openai.com/v1\",\n        api_key=llm_api_key or os.environ.get(\"OPENAI_API_KEY\"),\n    )\n    print(f\"[startup] CAMEL model created: label={config_label}\", flush=True)\n    return model"""
replace_if_present(runner, old_model, new_model, "CAMEL OpenAI-compatible model routing")

# OASIS can expose DefaultPlatformType through different import identities.
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

# A small Render instance should not fan out 30 LLM requests per world.
replace_if_present(
    runner,
    "semaphore=30,  # 限制最大并发 LLM 请求数，防止 API 过载",
    "semaphore=5,  # Render-safe LLM concurrency",
    "Render-safe OASIS concurrency",
    all_occurrences=True,
)

# Make the exact pre-LLM startup stage visible. Agent graph generation itself
# should be quick; if it hangs we now know which world is responsible.
replace_if_present(
    runner,
    "    result.agent_graph = await generate_twitter_agent_graph(",
    "    print(\"[startup] generating Twitter agent graph\", flush=True)\n    result.agent_graph = await generate_twitter_agent_graph(",
    "Twitter agent-graph startup checkpoint",
)
replace_if_present(
    runner,
    "    result.agent_graph = await generate_reddit_agent_graph(",
    "    print(\"[startup] generating Reddit agent graph\", flush=True)\n    result.agent_graph = await generate_reddit_agent_graph(",
    "Reddit agent-graph startup checkpoint",
)

# The observed failure mode is RUNNING at 0/40 with no OpenAI usage. Bound the
# OASIS reset stage so it cannot silently sit there forever. This applies to
# both Twitter and Reddit reset calls.
old_reset = "    await result.env.reset()"
new_reset = """    print(\"[startup] resetting OASIS environment\", flush=True)\n    try:\n        await asyncio.wait_for(result.env.reset(), timeout=90)\n    except asyncio.TimeoutError as exc:\n        raise RuntimeError(\"OASIS environment reset timed out after 90 seconds\") from exc\n    print(\"[startup] OASIS environment ready\", flush=True)"""
replace_if_present(
    runner,
    old_reset,
    new_reset,
    "bounded OASIS environment reset",
    all_occurrences=True,
)

# Do the same for actual LLM-backed environment steps. A provider/network
# failure must become a concrete worker error rather than an indefinite 0/40.
old_step = "        await result.env.step(actions)"
new_step = """        try:\n            await asyncio.wait_for(result.env.step(actions), timeout=120)\n        except asyncio.TimeoutError as exc:\n            raise RuntimeError(f\"OASIS LLM step timed out at round {round_num + 1} after 120 seconds\") from exc"""
replace_if_present(
    runner,
    old_step,
    new_step,
    "bounded OASIS LLM round step",
    all_occurrences=True,
)

# Step 3 is always the dual-world simulation. Ignore stale browser values.
replace_if_present(
    api,
    "platform = data.get('platform', 'parallel')",
    "platform = 'parallel'  # Step 3 always runs the dual-world simulation",
    "Step 3 server-side platform normalization",
)

print("runtime compat: startup compatibility pass complete", flush=True)
