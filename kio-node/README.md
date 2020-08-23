# Kio Node
Current Node Version: `v0.0.1g`
The Kio Node web app api runs on every kiosk you'll want to control. For more details on Kio-Node
such as documentation and install guides check out the Kio-Node [READEME.md](kio-node/README.md)
## API Endpoints
#### /set-display
Set display is the work horse of `kio_node`. This URI will set the chromium session to load the
requested url. To set the chromium web page, something like the following will do that.
Example:
```
http://192.168.1.20:8001/set-display?url=https://www.google.com
```
## Install Kio-Node
### System Requirements
`python3-pip`

### Process
Install the kio-node python requirementsrequirements
```
pip3 install -r kio-node/requirements.txt
```

Setup the kio-node app to run on boot. In `/etc/rc.local` set gunicorn to run the server at boot as the `pi` user on port `8001`
```
cd /home/pi/apps/kio/kio-node && gunicorn kio-node:app -b0.0.0.0:8001 --daemon
```
