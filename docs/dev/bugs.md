# Bugs
## Agent
 - hosts file seems to get updates but it doesn't appear to be affected by google.com being null routed on kio-2
 - Figure out what to do with kanshi-config
 - Brower tabs are still not working
   - Not geting list of tabs
   - not able to manage properly
 - Reboot seems broken
 - living room inputs broken

## Browser Tabs
 - Refresh rate is BAD
 - Add a last-focused time to the UI and records
 - the unique ID for a browser tab
   - should be pretty
   - should be user editable
   - be restoreable (preserved and stored in DB)

## Urls
 - Needs to be integrated to playlists
 - Browser Tabs should show better info for pre known Urls

## Home Assistant
 - Filter device inputs going to HA to just selected/ co configured in HA
   - use the HA nmaes


profile kiosk {
    output "Dell Inc. DELL S2721QS 7W2WZY3" mode 1920x1080@60Hz position 0,0
}