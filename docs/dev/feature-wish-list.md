# Feature List
## Pi Management
- [x] Update hosts file
- [x] Import certificates
- [ ] Better Playlist Setup
  - [ ] show progress of playlist running (in progress)
  - [ ] Pre load brower tabs (in progress)
  - [ ] Pause rotation process if display is off
- [ ] Manage browser tabs (in progress not working)
- [ ] Support for SQLlite
- [ ] Settings
  - [ ] Show weather using postgres of SQL lite
  - [ ] Kio Node metadata edit/viewer
- [ ] Feature flags
- [ ] system up time
- [ ] Configurable by env timeout for agent command lockout
- [ ] Store multiple display configs/ discovery per kio node



## UI
 - [ ] Collapse side nav
 - [ ] Reboot modal has a transparent background
 - [ ] Add a toast for node online after not being online
 - [ ] kiosk/{node} should show slow plusing when online
 - [ ] url should be host-name or pretty-slug

## Security
- [ ] Lock down api
- [ ] Use the latest possible versions of every package
  - [ ] Api
  - [ ] UI
  - [ ] agent
- [ ] Verify Authentik is working
- [ ] Lock down MQTT and update connections
  - [ ] Use a password
  - [ ] Use a TLS cert
- [ ] Docker contaners
  - [ ] minimize
  - [ ] user land
  - [ ] secure
- [ ] Static api RBAK, limit what a node can do on the api etc


## Agent
- [ ] Report off all browser tabs
- [ ] Explore how to browser authentication potentialls
- [x] Use Yaml as config
-  [ ] Manage display settings
   -  [ ] resolution 
- [ ] Minimze Kio Node foot path with setup.sh (if requested)
- [ ] Event Log
  - [ ] reboot should be reboot_issues
  - [ ] on reboot/ boot add to event log, booted
  - [ ] make sure agent start is also preserved
- [ ] Suspend browser operations (reloading, playlist cycling) when display is off
- [ ] Hide cursor

## Home Assistant
- [ ] Ability to add multiple Kiosk


## Look Into
- [ ] Tigthening up input selection in HA and Kio
  - [ ] Make the 


## Development
- [x] Clean up directory structure
- [ ] Setup new development agent section on the pi
- [ ] Better release process
- [x] Use Black
- [x] Add unit tests
- [x] Add regression tests
- [x] Staging Environment
- [ ] Signed local certs
- [ ] Strealine agent development
  - [ ] Use Git for updates
  - [ ] Have setup.sh take config var
  - [ ] Incorperator read write perms on debug files
  - [ ] Setup prd version of the pi agent
- [ ] About 
  - [ ] page shows current migration versions
  - [ ] Data statistics, ie numbers of models and size on disk
- [ ] Event log can search types of events
  - [ ] Add event - full scan
- [ ] CICD
  - [ ] Run Unit tests
  - [ ] Run Regression tests (on demand?)
  - [ ] Create new relase
    - [ ] UI
    - [ ] API
    - [ ] Agent
    - [ ] HA


## External
 - Home Assistant Dashboard
 - Q media specific dashboards
   - Sonarr
   - SabNZBD
   - Radarr
 - Tighten up jellyfin exporter to drop not playing streams faster
 - 