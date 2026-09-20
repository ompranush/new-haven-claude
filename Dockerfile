FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 10001 newhaven && mkdir -p /app/static /app/data && chown -R newhaven:newhaven /app
USER newhaven
# Streamlit config as env vars, so the deploy does not depend on the hidden .streamlit/ folder
ENV PYTHONUNBUFFERED=1 PORT=8501 \
    STREAMLIT_SERVER_ENABLE_STATIC_SERVING=true \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_THEME_BASE=dark \
    STREAMLIT_THEME_PRIMARY_COLOR="#3b82f6" \
    STREAMLIT_THEME_BACKGROUND_COLOR="#0b1220" \
    STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR="#141d2b" \
    STREAMLIT_THEME_TEXT_COLOR="#e6edf3"
EXPOSE 8501
CMD streamlit run app.py --server.port ${PORT} --server.address 0.0.0.0
