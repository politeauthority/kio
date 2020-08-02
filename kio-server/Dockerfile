FROM debian:bullseye-slim

ENV KIO_SERVER_CONFIG=docker
ENV KIO_SERVER_DB_HOST=kio-server-mysql
ENV KIO_SERVER_DB_PORT=3306
ENV KIO_SERVER_DB_NAME=kio_pages
ENV KIO_SERVER_DB_USER=root
ENV KIO_SERVER_DB_PASS=pass
ENV KIO_SERVER_DB_DRIVER=mysql
ENV KIO_SERVER_STATIC_PATH='/static'
ENV KIO_SERVER_LOG_DIR=/app/logs
ENV KIO_SERVER_TMP_DIR=/tmp/lan_nanny
ENV KIO_SERVER_GIT_BRANCH=0.0.1

ADD ./ /app
VOLUME /app/
WORKDIR /app/

# Install apt requirements
RUN apt-get -y update

RUN apt-get -y install python3-pip

RUN pip install -r /app/requirements.txt

CMD cd kio-server && gunicorn -b 0.0.0.0:5000 kio-server:app
