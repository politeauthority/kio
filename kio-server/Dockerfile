FROM python:rc-alpine3.12

ENV KIO_SERVER_CONFIG=docker
ENV KIO_SERVER_DB_DRIVER=mysql
ENV KIO_SERVER_DB_HOST=mysql
ENV KIO_SERVER_DB_PORT=3306
ENV KIO_SERVER_DB_NAME=kio
ENV KIO_SERVER_DB_USER=root
ENV KIO_SERVER_DB_PASS=pass
ENV KIO_SERVER_DB_DRIVER=mysql
ENV KIO_SERVER_MQTT_HOST=mqtt
ENV KIO_SERVER_MQTT_TOPIC=kio
ENV KIO_SERVER_MQTT_AUTH=false
ENV KIO_SERVER_MQTT_USER=root
ENV KIO_SERVER_MQTT_PASS=pass
ENV KIO_SERVER_STATIC_PATH='/static'
ENV KIO_SERVER_LOG_DIR=/app/logs
ENV KIO_SERVER_TMP_DIR=/tmp/kio
ENV KIO_SERVER_URL="localhost:8000"

ADD ./ /app
VOLUME /app
WORKDIR /app

# Install apt requirements
RUN apk update
RUN apk add --virtual \
    build-deps \
    gcc \
    python3-dev \
    musl-dev \
    mariadb-dev \
    py3-pip \
    bash 

# Install Kio Python requirements
RUN pip install -r /app/requirements.txt

CMD gunicorn -b 0.0.0.0:8000 kio-server:app
