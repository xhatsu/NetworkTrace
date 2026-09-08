FROM node:22-alpine AS ui
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend ./backend
COPY docs ./docs
COPY --from=ui /src/frontend/dist ./frontend/dist
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh
ENV OTEL_DB_PATH=/data/tracescope.db OTEL_DEMO_MODE=true OTEL_RETENTION_DAYS=30
VOLUME ["/data"]
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
