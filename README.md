# Kio
Raspberry Pi Kiosk software for controlling one or many displays.

##Kio Node
The Kio Node web app api runs on every kiosk you'll want to control.

## Requirements
python3-pip


## Install
### Kio Node
Setup the kio-node app to run on boot. In `/etc/rc.local` set gunicorn to run the server at boot as the `pi` user on port `8000`
```
su pi -c 'cd /home/pi/repos/kio/kio-node && gunicorn kio-node:app -b0.0.0.0:8000 --daemon'
```
