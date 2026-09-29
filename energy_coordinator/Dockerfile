FROM python:3.12-alpine3.22
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}"
RUN apk add --no-cache tzdata
WORKDIR /app
COPY energy/ /app/energy/
COPY config/ /app/config/
COPY tests/ /app/tests/
RUN python3 -m unittest discover -s tests -q && rm -rf /app/tests
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Prague
CMD ["python3", "-m", "energy.bootstrap"]
