# -------------------------------------------------------
# Wisecow Application – Dockerfile
# Base: Ubuntu 22.04 (LTS) for apt package availability
# -------------------------------------------------------
FROM ubuntu:22.04

LABEL maintainer="devops@example.com"
LABEL description="Wisecow – Cow wisdom web server"
LABEL version="1.0"

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PORT=4499

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fortune-mod \
        fortunes \
        cowsay \
        socat \
        openssl \
        netcat-openbsd \
        bash \
        ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Add cowsay to PATH
ENV PATH="/usr/games:${PATH}"

# Create non-root user for security
RUN groupadd -r wisecow && useradd -r -g wisecow wisecow

# Set working directory
WORKDIR /app

# Copy application source
COPY wisecow.sh /app/wisecow.sh
RUN chmod +x /app/wisecow.sh

# TLS directory (certificates can be mounted here)
RUN mkdir -p /app/tls && chown wisecow:wisecow /app/tls

# Switch to non-root user
USER wisecow

# Expose application port
EXPOSE 4499

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD bash -c "echo -e 'GET / HTTP/1.0\r\n\r\n' | nc -w 2 localhost ${PORT} | grep -q 'HTTP/1' || exit 1"

# Run the application
CMD ["/app/wisecow.sh"]
