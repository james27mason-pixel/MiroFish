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

# MiroFish accepts arbitrary OpenAI/OpenAI-compatible model names from
# LLM_MODEL_NAME. CAMEL's OPENAI backend in the pinned version validates the
# model name against its own enum, so newer model IDs can fail before making
# an API request. Route this configurable model through CAMEL's compatible
# backend and pass the URL/key explicitly. The assertion makes the image build
# fail loudly if the upstream source changes instead of silently skipping it.
RUN python -c 'from pathlib import Path; p=Path("backend/scripts/run_parallel_simulation.py"); s=p.read_text(); old="""    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI,\n        model_type=llm_model,\n    )"""; new="""    return ModelFactory.create(\n        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,\n        model_type=llm_model,\n        url=llm_base_url or \"https://api.openai.com/v1\",\n        api_key=llm_api_key or os.environ.get(\"OPENAI_API_KEY\"),\n    )"""; assert old in s, "CAMEL model factory block changed; update Dockerfile patch"; p.write_text(s.replace(old,new,1))'

# Build the Vue frontend once for production. Flask serves the built files
# and the API from the same Render port.
RUN npm run build --prefix frontend

EXPOSE 5001

CMD ["npm", "run", "backend"]
