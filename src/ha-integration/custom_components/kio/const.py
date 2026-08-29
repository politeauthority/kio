DOMAIN = "kio"
PLATFORMS = ["binary_sensor", "sensor", "button", "switch", "select", "number", "text"]

CONF_API_URL = "api_url"
CONF_API_KEY = "api_key"
CONF_API_IP = "api_ip"
# PEM file (path, relative to the HA config dir unless absolute) to trust in
# addition to the system CAs — the kio API sits behind a private CA.
CONF_CA_CERT = "ca_cert"
