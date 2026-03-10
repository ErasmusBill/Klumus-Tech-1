FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_HOME=/opt/poetry \
    POETRY_VERSION=1.8.5

WORKDIR /app

# System dependencies (weasyprint + psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    libffi-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
  && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="${POETRY_HOME}/bin:${PATH}"

# Use system site-packages inside the container
RUN poetry config virtualenvs.create false

# Install dependencies from requirements.txt using Poetry
COPY requirements.txt /app/requirements.txt
RUN poetry init -n --name klumus && \
    xargs -a requirements.txt poetry add -n

# Copy project files
COPY . /app

ENV PORT=8080 \
    APP_ENV=development

EXPOSE 8080

# Single image for dev + prod, controlled by APP_ENV
CMD ["bash", "-lc", "if [ \"$APP_ENV\" = \"production\" ]; then python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --config gunicorn.conf.py; else python manage.py migrate && python manage.py runserver 0.0.0.0:${PORT}; fi"]
