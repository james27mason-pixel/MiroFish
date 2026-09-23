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

# Build the Vue frontend once for production. Flask serves the built files
# and the API from the same Render port.
RUN npm run build --prefix frontend

EXPOSE 5001

CMD ["npm", "run", "backend"]
