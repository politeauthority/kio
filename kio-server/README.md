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
GRANT ALL PRIVILEGES ON kio . * TO 'kio'@'%';
CREATE DATABASE IF NOT EXISTS kio;
```
- Launch the Kio-Server docker container
```console
# Set the variables you're likely to want to change for your environment
set -eu
DB_HOST=192.168.50.100
DB_PASS=your_fancy_password
MQTT_HOST=192.168.50.100
RELEASE=latest
DB_NAME=kio
DB_USER=kio

# Start the Kio-Server web app container
docker run \
    --name=kio \
    -e KIO_SERVER_DB_HOST=$DB_HOST \
    -e KIO_SERVER_DB_NAME=$DB_NAME \
    -e KIO_SERVER_DB_USER=$DB_USER \
    -e KIO_SERVER_DB_PASS=$DB_PASS \
    -e KIO_SERVER_MQTT_HOST=$MQTT_HOST \
    -d \
    --net=host \
    --restart=always \
   politeauthority/kio-server:$RELEASE


# Start the Kio-Server command container
docker run \
    --name=kio-cmd \
    -e KIO_SERVER_DB_HOST=$DB_HOST \
    -e KIO_SERVER_DB_NAME=$DB_NAME \
    -e KIO_SERVER_DB_USER=$DB_USER \
    -e KIO_SERVER_DB_PASS=$DB_PASS \
    -e KIO_SERVER_MQTT_HOST=$MQTT_HOST \
    -d \
    --net=host \
    --restart=always \
   politeauthority/kio-server:${RELEASE} \
   python3 daemon.py

```


## API
The Kio Server api lives at the Kio Server lives at the server's url.

### /api/cmd
This endpoint exists to ultimately send commands to Kio-Nodes. It does this by creating a `device_cmd` record and sending it to the MQTT broker.
#### Arguments
`device_id` The ID of the device to issue a command to. *Required*
`cmd` The command type to send to a device.
    Accepted commands
  - `display_set` Used to tell a Kio-Node to set the display to a particular URL which is defined in the payload's `value`.
  - `display_toggle` Turns a display on/off. Requires the `value` argument to contain either `0` for off or `1` for on. *Only works for some device types.*
  - `display_reboot` Tells a device to reboot, does not require any `value`.

`value` The value to send to the api for the command. If the command is `display_set` this would be the url you wish to display to load.
