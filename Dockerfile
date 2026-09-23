FROM python:3.11

# Install Node.js plus the small PostgreSQL client used by the durable
# Supabase snapshot layer. No database credentials are baked into the image.
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm postgresql-client \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

RUN npm ci \
  && npm ci --prefix frontend \
  && cd backend && uv sync --frozen

COPY . .

# Render runtime compatibility hardening.
#
# 1. MiroFish accepts arbitrary OpenAI/OpenAI-compatible model names from
#    LLM_MODEL_NAME. CAMEL's strict OPENAI adapter in the pinned version can
#    reject newer model IDs before an API request. Use the compatible adapter
#    and pass the configured URL/key explicitly.
# 2. OASIS 0.2.5 checks platform enum identity with isinstance(). Resolve the
#    enum from the exact defining module used by OasisEnv so packaged/runtime
#    import layouts cannot produce the observed "Invalid platform" failure.
# 3. Step 3 is the dual-world runner. Normalize the backend start route to
#    parallel as a final server-side guard as well as the existing frontend
#    normalization. This prevents stale browser payloads from blocking launch.
RUN python -c 'from pathlib import Path; p=Path("backend/scripts/run_parallel_simulation.py"); s=p.read_text(); old="""    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI,\n        model_type=llm_model,\n    )"""; new="""    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,\n        model_type=llm_model,\n        url=llm_base_url or \"https://api.openai.com/v1\",\n        api_key=llm_api_key or os.environ.get(\"OPENAI_API_KEY\"),\n    )"""; assert old in s, "CAMEL model factory block changed; update Dockerfile patch"; s=s.replace(old,new,1); tw="platform=oasis.DefaultPlatformType.TWITTER"; rd="platform=oasis.DefaultPlatformType.REDDIT"; exact="__import__(\"oasis.social_platform.typing\", fromlist=[\"DefaultPlatformType\"]).DefaultPlatformType"; assert tw in s and rd in s, "OASIS platform call changed; update Dockerfile patch"; s=s.replace(tw, "platform="+exact+".TWITTER", 1).replace(rd, "platform="+exact+".REDDIT", 1); p.write_text(s); api=Path("backend/app/api/simulation.py"); a=api.read_text(); old_api="platform = data.get(\u0027platform\u0027, \u0027parallel\u0027)"; assert old_api in a, "simulation start platform assignment changed; update Dockerfile patch"; a=a.replace(old_api, "platform = \u0027parallel\u0027  # Step 3 always runs the dual-world simulation", 1); api.write_text(a)'

# Fail the deployment at build time instead of discovering dependency/import
# incompatibilities after spending API credit. These checks make no network or
# OpenAI calls and expose no secrets.
RUN cd backend && uv run python -c 'from camel.types import ModelPlatformType; from oasis.social_platform.typing import DefaultPlatformType; from oasis.environment.env import DefaultPlatformType as EnvPlatformType; assert hasattr(ModelPlatformType, "OPENAI_COMPATIBLE_MODEL"); assert DefaultPlatformType is EnvPlatformType; assert isinstance(DefaultPlatformType.TWITTER, EnvPlatformType); assert isinstance(DefaultPlatformType.REDDIT, EnvPlatformType); print("MiroFish runtime compatibility checks passed")' \
  && uv run python -m compileall -q app scripts

# Build the Vue frontend once for production. Flask serves the built files
# and the API from the same Render port.
RUN npm run build --prefix frontend

EXPOSE 5001

CMD ["npm", "run", "backend"]
