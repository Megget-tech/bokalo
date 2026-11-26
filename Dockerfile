FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x bin/start.sh \
 && DJANGO_SECRET_KEY=build DJANGO_DEBUG=false python manage.py collectstatic --noinput
CMD ["./bin/start.sh"]
