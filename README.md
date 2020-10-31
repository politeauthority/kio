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
Current version: `v0.0.1g`
The Kio Node web app api runs on every kiosk you'll want to control. For more details on Kio-Node
such as documentation and installation guide, check out the [Kio-Node README.md](kio-node/README.md)

## Kio Server
Kio-Server is the controller system for all Kio-Nodes on your network. For more details on Kio-Server
such as documentation and installation guide, check out the [Kio-Server README.md](kio-server/README.md)
