cd /home/pi/repos/kio/kio-server
rm /opt/kio-dev/kio.db
sudo python3 install-upgrade.py
sudo chmod -R 777 /opt/kio-dev