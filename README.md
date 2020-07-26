# Kio
Raspberry Pi Kiosk software for controlling one or many displays.

## Kio Node
The Kio Node web app api runs on every kiosk you'll want to control.

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