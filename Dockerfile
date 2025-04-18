# ---- Build Svelte frontend ----
    FROM node:18 AS frontend
    WORKDIR /frontend
    COPY frontend ./
    RUN npm install && npm run build
    
    # ---- Backend (Python) ----
    FROM python:3.11-slim AS backend
    WORKDIR /app
    
    # Install deps
    COPY backend/requirements.txt ./
    RUN pip install --no-cache-dir -r requirements.txt
    
    # Copy backend + frontend build
    COPY backend ./
    COPY --from=frontend /frontend/build ./static
    
    # Expose port + run with Uvicorn
    CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
    EXPOSE 8080
    