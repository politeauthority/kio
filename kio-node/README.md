# Kio Node

## Installing
This installation process assumes you have the user `pi`.

### Step 1

```console
sudo apt update
sudo apt full-upgrade
sudo reboot
```

### Step 2
```console
sudo apt-get install \
    vim \
    git \
    xdotool unclutter
mkdir -p ~/apps
git clone git@github.com:politeauthority/kio.git ~/apps/kio
pip3 install -r requirements.txt
```

Add the following to `/etc/rc.local` to make Kio-Node run at boot. This will run the Kio-Node api on
port `8001`. Change that part of the command if that's an issue on your system.
```console
cd /home/pi/apps/kio/kio-node && gunicorn kio-node:app -b0.0.0.0:8001 --daemon
```