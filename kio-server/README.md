# Kio Server
Kio Server is comprised of multiple parts, which are most easily managed by running those parts via
Docker.
 - Kio Server: The web app which helps organize and control the entire system.
 - Kio Worker: The daemon process handling requests and commands to be sent to Kio-Nodes.
 - MySQL: Database to persist all data for the Kio system.
 - Mosquito: The MQTT broker which handles sending data and commands to nodes.

## Install
Kio Server is most easily run through the Docker container.
This assumes you already have a MySQL container running, eventually I will add details on setting
one up.

 - Create a MySQL user for kio-server
```sql
CREATE USER 'kio'@'%' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON * . * TO 'kio'@'localhost';
```
- Launch the Kio-Server docker container
```console
docker run \
    --name=kio \
    -e KIO_SERVER_DB_HOST="192.168.50.100" \
    -e KIO_SERVER_DB_NAME="kio" \
    -e KIO_SERVER_DB_USER="kio" \
    -e KIO_SERVER_DB_PASS="password" \
    -d \
    --net=host \
    --restart=always \
   politeauthority/kio-server:latest
```
