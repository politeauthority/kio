# Kio
Raspberry Pi Kiosk software for controlling one or many kiosk displays remotely.

Kio has two primary pieces. The first and most important is `kio-node`. This part of the application
must be run on every kiosk at a minimum.
Kio-Node creates a REST API on the device actually running the display. Kio-Node accepts requests
to change the running chromium processes currently displayed webpage. If that control is all you
seek you can just install the `kio-node` portion of the software.

The second part of Kio is a web app which helps collect and control multiple (or just one) instances
of Kio-Node. `kio-server` is a web app which you register all `kio-nodes` and then can set the web
page the kio-nodes display manually, or create playlists to cycle through.


## Kio Node
The Kio Node web app api runs on every kiosk you'll want to control.
### Endpoints
#### /set-display
Set display is the work horse of `kio_node`. This URI will set the chromium session to load the
requested url. To set the chromium web page, something like the following will do that.
Example:
```
http://192.168.1.20:8001/set-display?url=https://www.google.com
```

## Requirements
python3-pip


## Install
### Kio Node
Install the kio-node requirements
```
pip3 install -r kio-node/requirements.txt
```

Setup the kio-node app to run on boot. In `/etc/rc.local` set gunicorn to run the server at boot as the `pi` user on port `8001`
```
su pi -c 'cd /home/pi/kio/kio-node && gunicorn kio-node:app -b0.0.0.0:8001 --daemon'
```

### Kio Server

Install the kio-server requirements
```
pip3 install -r kio-server/requirements.txt
```

Setup the kio-server app to run on boot. In `/etc/rc.local` set gunicorn to run the server at boot as the `pi` user on port `8000`
```
su pi -c 'cd /home/pi/kio/kio-server && export KIO_SERVER_CONFIG="prod" && gunicorn kio-server:app -b0.0.0.0:8000 --daemon'
```

Setup the kio-server cron job which manages scheduling displays and other house keeping.

```console
*/2 * * * * python3 /home/pi/kio/kio-server/cron.py >/dev/null 2>&1
```


```console
docker build . -t="kio-server:dev"
docker run \
    --name kio-server-dev \
    -v /home/pi/repos/kio-server/:/app \
    --net=host \
    -d \
    --rm \
    kio-server:dev
```