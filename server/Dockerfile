FROM python:3.12-slim
LABEL org.opencontainers.image.source=https://github.com/bdlnaredi/bahi
WORKDIR /app
COPY app /app
ENV DATA_DIR=/data PORT=8780 PYTHONUNBUFFERED=1 TZ=IST-5:30
EXPOSE 8780
VOLUME /data
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8780/manifest.webmanifest')" || exit 1
CMD ["python", "/app/main.py"]
