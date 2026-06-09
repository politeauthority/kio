# Dev Agent Guide

## To DO
 - Allow for DNS to be auto configured
 - Install screen

## Learning
Interesting file

`/boot/firmware/cmdline.txt`

## URLS
"https://grafana.example.local/public-dashboards/&lt;dashboard-uid&gt;"
Q media Public

Public Colfax
https://grafana.example.local/public-dashboards/&lt;dashboard-uid&gt;


## Commands

### Core
'
Start Chromium
```bash
# DISPLAY=:0 chromium --password-store=basic &
# DISPLAY=:0 chromium --password-store=basic "https://google.com" > /dev/null 2>&1 &

DISPLAY=:0 chromium \
    --password-store=basic \
    --force-dark-mode \
    --start-fullscreen "https://google.com" > /dev/null 2>&1 &


DISPLAY=:0 chromium --password-store=basic --start-fullscreen \
    --force-dark-mode \
    --ignore-certificate-errors \
    --force-dark-mode \
    --disable-session-crashed-bubble \
    --no-first-run \
    --remote-debugging-port=9222 \
    --hide-crash-restore-bubble \
    "https://grafana.example.local/public-dashboards/&lt;dashboard-uid&gt;" > /dev/null 2>&1 &

```

Naviage
```bash
DISPLAY=:0 chromium "https://google.com"
DISPLAY=:0 chromium "https://reddit.com"

DISPLAY=:0 chromium "https://grafana.example.local/public-dashboards/&lt;dashboard-uid&gt;"


DISPLAY=:0 chromium "https://grafana.example.local/public-dashboards/&lt;dashboard-uid&gt;"

DISPLAY=:0 chromium "https://grafana.example.local/public-dashboards/&lt;dashboard-uid&gt;"
```

Stop Chromium 
```bash
DISPLAY=:0 pkill chromium
```
List Tabs
```bash
curl -s http://localhost:9222/json | python3 -m json.tool | grep '"url"'
```

### Debugging
DNS RESET
```bash
sudo nmcli con mod "netplan-wlan0-A Series of Tubes" ipv4.dns ""
sudo nmcli con mod "netplan-wlan0-A Series of Tubes" ipv4.ignore-auto-dns no
sudo nmcli con up "netplan-wlan0-A Series of Tubes"
```  




## Python Agent
```bash
KIO_API_URL="https://your-api-url" KIO_POLL_INTERVAL=5 python3 pi-agent/scripts/kio-agent
```  


  KIO_API_URL="https://your-api-url" KIO_POLL_INTERVAL=5 python3
  pi-agent/scripts/kio-agent

  The log will go to ~/kio/logs/kio-agent.log. If you want to watch it live in
  another terminal:

  tail -f ~/kio/logs/kio-agent.log

  If requests isn't installed:

  pip3 install requests

  Set a short KIO_POLL_INTERVAL (like 5s) while developing so you don't wait 30
  seconds between cycles.
