FROM python:3.11

# Install Node.js plus the small PostgreSQL client used by the durable
# Supabase snapshot layer. No database credentials are baked into the image.
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm postgresql-client \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# Child simulation output is redirected to files. Force Python to flush every
# startup checkpoint immediately so a stalled worker is diagnosable.
ENV PYTHONUNBUFFERED=1

COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

RUN npm ci \
  && npm ci --prefix frontend \
  && cd backend && uv sync --frozen

COPY . .

# Render runtime compatibility hardening.
#
# 1. Route configurable model IDs through CAMEL's OpenAI-compatible adapter.
# 2. Resolve the OASIS platform enum from the exact module OasisEnv uses.
# 3. Step 3 always runs the dual-world runner.
# 4. Bound OASIS environment reset so a dependency deadlock becomes a visible
#    failed run rather than an endless RUNNING 0/40 state.
# 5. Reduce per-world LLM concurrency on the small Render instance. Thirty
#    concurrent requests/environments is unnecessarily aggressive here.
# 6. Emit safe startup checkpoints (never the API key itself) around model,
#    graph and environment initialisation.
RUN python -c 'from pathlib import Path; p=Path("backend/scripts/run_parallel_simulation.py"); s=p.read_text(); old="""    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI,\n        model_type=llm_model,\n    )"""; new="""    print(f\"[startup] creating CAMEL model: label={config_label}, model={llm_model}, key_present={bool(llm_api_key)}, base_url={llm_base_url or 'https://api.openai.com/v1'}\", flush=True)\n    model = ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,\n        model_type=llm_model,\n        url=llm_base_url or \"https://api.openai.com/v1\",\n        api_key=llm_api_key or os.environ.get(\"OPENAI_API_KEY\"),\n    )\n    print(f\"[startup] CAMEL model created: label={config_label}\", flush=True)\n    return model"""; assert old in s, "CAMEL model factory block changed; update Dockerfile patch"; s=s.replace(old,new,1); tw="platform=oasis.DefaultPlatformType.TWITTER"; rd="platform=oasis.DefaultPlatformType.REDDIT"; exact="__import__(\"oasis.social_platform.typing\", fromlist=[\"DefaultPlatformType\"]).DefaultPlatformType"; assert tw in s and rd in s, "OASIS platform call changed; update Dockerfile patch"; s=s.replace(tw, "platform="+exact+".TWITTER", 1).replace(rd, "platform="+exact+".REDDIT", 1); s=s.replace("semaphore=30,", "semaphore=5,"); reset="    await result.env.reset()"; replacement="    print(\"[startup] resetting OASIS environment\", flush=True)\n    try:\n        await asyncio.wait_for(result.env.reset(), timeout=90)\n    except asyncio.TimeoutError as exc:\n        raise RuntimeError(\"OASIS environment reset timed out after 90 seconds\") from exc\n    print(\"[startup] OASIS environment ready\", flush=True)"; assert s.count(reset) >= 2, "OASIS reset blocks changed; update Dockerfile patch"; s=s.replace(reset,replacement); twgraph="    result.agent_graph = await generate_twitter_agent_graph("; rdgraph="    result.agent_graph = await generate_reddit_agent_graph("; assert twgraph in s and rdgraph in s, "agent graph generation changed; update Dockerfile patch"; s=s.replace(twgraph, "    print(\"[startup] generating Twitter agent graph\", flush=True)\n"+twgraph,1).replace(rdgraph, "    print(\"[startup] generating Reddit agent graph\", flush=True)\n"+rdgraph,1); p.write_text(s); api=Path("backend/app/api/simulation.py"); a=api.read_text(); old_api="platform = data.get(\u0027platform\u0027, \u0027parallel\u0027)"; assert old_api in a, "simulation start platform assignment changed; update Dockerfile patch"; a=a.replace(old_api, "platform = \u0027parallel\u0027  # Step 3 always runs the dual-world simulation", 1); api.write_text(a)'

# Fail deployment at build time for known dependency/import incompatibilities.
# These checks make no network/OpenAI calls and expose no secrets.
RUN cd backend && uv run python -c 'from camel.types import ModelPlatformType; from oasis.social_platform.typing import DefaultPlatformType; from oasis.environment.env import DefaultPlatformType as EnvPlatformType; assert hasattr(ModelPlatformType, "OPENAI_COMPATIBLE_MODEL"); assert DefaultPlatformType is EnvPlatformType; assert isinstance(DefaultPlatformType.TWITTER, EnvPlatformType); assert isinstance(DefaultPlatformType.REDDIT, EnvPlatformType); print("MiroFish runtime compatibility checks passed")' \
  && uv run python -m compileall -q app scripts

# Build the Vue frontend once for production. Flask serves the built files
# and the API from the same Render port.
RUN npm run build --prefix frontend

EXPOSE 5001

CMD ["npm", "run", "backend"]
