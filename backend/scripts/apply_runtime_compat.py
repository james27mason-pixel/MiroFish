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
replace_if_present(runner, "platform=oasis.DefaultPlatformType.TWITTER", f"platform={exact_enum}.TWITTER", "OASIS Twitter platform enum identity")
replace_if_present(runner, "platform=oasis.DefaultPlatformType.REDDIT", f"platform={exact_enum}.REDDIT", "OASIS Reddit platform enum identity")

# A small Render instance should not fan out 30 LLM requests per world.
replace_if_present(
    runner,
    "semaphore=30,  # 限制最大并发 LLM 请求数，防止 API 过载",
    "semaphore=5,  # Render-safe LLM concurrency",
    "Render-safe OASIS concurrency",
    all_occurrences=True,
)

# Bound graph construction too. A graph-generation deadlock happens before the
# first action log entry, which otherwise leaves the UI at RUNNING 0/N forever.
old_tw_graph = """    print(\"[startup] generating Twitter agent graph\", flush=True)\n    result.agent_graph = await generate_twitter_agent_graph(\n        profile_path=profile_path,\n        model=model,\n        available_actions=TWITTER_ACTIONS,\n    )"""
new_tw_graph = """    print(\"[startup] generating Twitter agent graph\", flush=True)\n    try:\n        result.agent_graph = await asyncio.wait_for(\n            generate_twitter_agent_graph(\n                profile_path=profile_path,\n                model=model,\n                available_actions=TWITTER_ACTIONS,\n            ),\n            timeout=90,\n        )\n    except asyncio.TimeoutError as exc:\n        raise RuntimeError(\"Twitter agent graph generation timed out after 90 seconds\") from exc\n    print(\"[startup] Twitter agent graph ready\", flush=True)"""
replace_if_present(runner, old_tw_graph, new_tw_graph, "bounded Twitter agent-graph generation")

old_rd_graph = """    print(\"[startup] generating Reddit agent graph\", flush=True)\n    result.agent_graph = await generate_reddit_agent_graph(\n        profile_path=profile_path,\n        model=model,\n        available_actions=REDDIT_ACTIONS,\n    )"""
new_rd_graph = """    print(\"[startup] generating Reddit agent graph\", flush=True)\n    try:\n        result.agent_graph = await asyncio.wait_for(\n            generate_reddit_agent_graph(\n                profile_path=profile_path,\n                model=model,\n                available_actions=REDDIT_ACTIONS,\n            ),\n            timeout=90,\n        )\n    except asyncio.TimeoutError as exc:\n        raise RuntimeError(\"Reddit agent graph generation timed out after 90 seconds\") from exc\n    print(\"[startup] Reddit agent graph ready\", flush=True)"""
replace_if_present(runner, old_rd_graph, new_rd_graph, "bounded Reddit agent-graph generation")

# Docker-less/native deploys may not have the graph checkpoint yet.
replace_if_present(runner, "    result.agent_graph = await generate_twitter_agent_graph(", "    print(\"[startup] generating Twitter agent graph\", flush=True)\n    result.agent_graph = await generate_twitter_agent_graph(", "Twitter agent-graph startup checkpoint")
replace_if_present(runner, "    result.agent_graph = await generate_reddit_agent_graph(", "    print(\"[startup] generating Reddit agent graph\", flush=True)\n    result.agent_graph = await generate_reddit_agent_graph(", "Reddit agent-graph startup checkpoint")

# Bound environment reset so a dependency deadlock becomes a concrete failure.
old_reset = "    await result.env.reset()"
new_reset = """    print(\"[startup] resetting OASIS environment\", flush=True)\n    try:\n        await asyncio.wait_for(result.env.reset(), timeout=90)\n    except asyncio.TimeoutError as exc:\n        raise RuntimeError(\"OASIS environment reset timed out after 90 seconds\") from exc\n    print(\"[startup] OASIS environment ready\", flush=True)"""
replace_if_present(runner, old_reset, new_reset, "bounded OASIS environment reset", all_occurrences=True)

# Initial seeded posts happen before round 1. Previously these calls had no
# timeout, so a stuck ManualAction could produce the exact permanent 0/N state.
old_initial_step = """        if initial_actions:\n            await result.env.step(initial_actions)"""
new_initial_step = """        if initial_actions:\n            print(\"[startup] applying initial seeded posts\", flush=True)\n            try:\n                await asyncio.wait_for(result.env.step(initial_actions), timeout=120)\n            except asyncio.TimeoutError as exc:\n                raise RuntimeError(\"OASIS initial seeded-post step timed out after 120 seconds\") from exc\n            print(\"[startup] initial seeded posts complete\", flush=True)"""
replace_if_present(runner, old_initial_step, new_initial_step, "bounded initial seeded-post step", all_occurrences=True)

# Bound actual LLM-backed round steps.
old_step = "        await result.env.step(actions)"
new_step = """        try:\n            await asyncio.wait_for(result.env.step(actions), timeout=120)\n        except asyncio.TimeoutError as exc:\n            raise RuntimeError(f\"OASIS LLM step timed out at round {round_num + 1} after 120 seconds\") from exc"""
replace_if_present(runner, old_step, new_step, "bounded OASIS LLM round step", all_occurrences=True)

# Step 3 is always the dual-world simulation. Ignore stale browser values.
replace_if_present(api, "platform = data.get('platform', 'parallel')", "platform = 'parallel'  # Step 3 always runs the dual-world simulation", "Step 3 server-side platform normalization")

print("runtime compat: startup compatibility pass complete", flush=True)
