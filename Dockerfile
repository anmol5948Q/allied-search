FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --system --no-create-home appuser
USER appuser
EXPOSE 8080
# No --access-logfile: gunicorn's access log would record query strings.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "30", "wsgi:app"]
