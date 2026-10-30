# Viewer build
FROM node:24-slim AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Python package with the built viewer inside
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY --from=ui /app/src/tracejudge/static/ src/tracejudge/static/
RUN pip install --no-cache-dir .
COPY demo-data/ demo-data/
ENV TRACEJUDGE_DB=/data/tracejudge.db
VOLUME /data
EXPOSE 7600
# Load the sample runs on first start, then serve the viewer, API and OTLP endpoint.
CMD ["sh", "-c", "[ -f \"$TRACEJUDGE_DB\" ] || tracejudge import demo-data/*.json.gz demo-data/otlp-genai-sample.json; exec tracejudge serve --host 0.0.0.0 --port 7600"]
