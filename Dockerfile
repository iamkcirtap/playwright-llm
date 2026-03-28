# Use the official Node.js 20 slim image as the base.
# We install Python on top since the generator scripts require it.
FROM node:20-slim

# Install Python 3 and pip.
# python-is-python3 maps the `python` command to Python 3
# so the npm scripts that call `python scripts/...` work as-is.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-pip \
       python-is-python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifests first so Docker can cache these layers.
# The layers below only rebuild when requirements.txt or package.json change.
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY package.json package-lock.json ./
RUN npm ci

# Install only Chromium and its system dependencies.
# Other browsers are not needed for this pipeline.
RUN npx playwright install --with-deps chromium

# Copy the rest of the project files.
COPY . .

# CI-mode defaults — all generation flags are on by default inside the container.
# GEMINI_API_KEY must be supplied at run time via -e or --env-file.
ENV CI=true \
    FORCE_REGENERATE=true \
    STRICT_GENERATION=true \
    LLM_CACHE_ENABLED=false

# Run the full quality gate: generate tests, then execute them.
CMD ["npm", "run", "quality:gate:ci"]
