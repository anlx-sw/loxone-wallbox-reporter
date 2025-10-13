### Dockerfile: Erzeugt ein optimiertes Image für den Wallbox Reporter
FROM python:3.14-slim

# Setze Arbeitsverzeichnis
WORKDIR /app

# Caching verhindern wenn neuer Commit
ADD https://api.github.com/repos/anlx-sw/loxone-wallbox-reporter/git/refs/heads/main version.json
# Installiere benötigte Pakete und klone das Repository
RUN apt-get update && apt-get install -y git \
    && git clone https://github.com/anlx-sw/loxone-wallbox-reporter.git /tmp/repo \
    && cp -r /tmp/repo/* /app/ \
    && rm -rf /tmp/repo \
    && pip install --no-cache-dir pandas reportlab

# Starte direkt das Python-Skript
CMD ["python","-u","wallbox_reporter.py"]