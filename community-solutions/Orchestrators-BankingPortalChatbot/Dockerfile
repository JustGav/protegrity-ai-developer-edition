# ──────────────────────────────────────────────────────────────────────
# Banking Portal Chatbot — shared image for TechnicalApp & BusinessApp
#
# Build:  docker build -t banking-portal-app .
# Run:    via docker-compose.yml (sets APP_TYPE=technical|business)
# ──────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Ensure CA certificates are up to date (fixes SSL failures on some Docker hosts)
RUN apt-get update -qq 2>/dev/null && apt-get install -y --no-install-recommends ca-certificates 2>/dev/null; \
    rm -rf /var/lib/apt/lists/*

# Use reliable mirrors; fall back to HTTP if HTTPS still fails (e.g. Docker Desktop + proxy)
RUN printf 'Types: deb\nURIs: https://deb.debian.org/debian\nSuites: trixie trixie-updates\nComponents: main\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n\nTypes: deb\nURIs: https://deb.debian.org/debian-security\nSuites: trixie-security\nComponents: main\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n' > /etc/apt/sources.list.d/debian.sources

# Install runtime deps needed by the apps and entrypoint
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends --fix-missing \
        curl \
        git \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    || { \
        echo "HTTPS failed — retrying with HTTP mirrors …"; \
        sed -i 's|https://|http://|g' /etc/apt/sources.list.d/debian.sources; \
        apt-get -o Acquire::Retries=5 update \
        && apt-get -o Acquire::Retries=5 install -y --no-install-recommends --fix-missing \
            curl git netcat-openbsd \
        && rm -rf /var/lib/apt/lists/*; \
    }

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY config/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# Copy the entire project
COPY . /app/

# Make entrypoint executable
RUN chmod +x /app/docker/entrypoint.sh

# Non-root user for security (uid 1000 matches typical host uid)
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Ensure chat history directories exist at image build time
RUN mkdir -p /app/TechnicalApp/chat_history_tech \
             /app/BusinessCustomerApp/chat_history

ENTRYPOINT ["/app/docker/entrypoint.sh"]
