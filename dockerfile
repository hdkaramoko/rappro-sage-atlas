# 1. Choisir une image de base
FROM python:3.12-slim

# 2. Définir le dossier de travail
WORKDIR /app

# 3. Copier les fichiers de dépendances
COPY pyproject.toml uv.lock ./

# 4. Installer les dépendances
RUN pip install uv
RUN uv sync --frozen

# 5. Copier le code
COPY . .

# 6. Faire les étapes de préparation
RUN uv run python manage.py collectstatic --noinput

# 7. Exposer le port
EXPOSE 8000

# 8. Définir la commande de démarrage
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]