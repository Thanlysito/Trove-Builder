web: python manage.py migrate --noinput --skip-checks && python manage.py collectstatic --noinput --skip-checks && gunicorn trove_builder.wsgi --bind 0.0.0.0:$PORT --log-file -
