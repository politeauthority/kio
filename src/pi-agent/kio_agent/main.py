"""Process entry point: load config, resolve TLS policy and kiosk id, then run."""

import urllib3

from kio_agent import runtime
from kio_agent.agent import KioAgent
from kio_agent.config import load_config, resolve_kiosk_id
from kio_agent.constants import CONFIG_FILE, logger
from kio_agent.runtime import AGENT_VERSION, BOOT_ID, resolve_tls_verify


def main() -> None:
    cfg = load_config()
    runtime.TLS_VERIFY = resolve_tls_verify(cfg["tls_verify"])
    if runtime.TLS_VERIFY is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("TLS verification disabled — all API requests will skip cert checks")
    elif isinstance(runtime.TLS_VERIFY, str):
        logger.info("TLS verification using CA bundle: %s", runtime.TLS_VERIFY)
    logger.info("Loaded config from %s — will communicate with API at %s", CONFIG_FILE, cfg["api_url"])
    # Resolve the node id from the API via the token (so config need not carry it).
    cfg["kiosk_id"] = resolve_kiosk_id(cfg)
    logger.info(
        "kio agent starting — version=%s boot_id=%s kiosk_id=%s config=%s api=%s tls=%s mqtt=%s:%s topic=%s features=%s",
        AGENT_VERSION,
        BOOT_ID,
        cfg["kiosk_id"],
        CONFIG_FILE,
        cfg["api_url"],
        "on" if runtime.TLS_VERIFY else "OFF",
        cfg["mqtt_host"],
        cfg["mqtt_port"],
        cfg["topic_prefix"],
        ",".join(cfg["features"]) or "none",
    )
    runtime.agent = KioAgent(cfg)
    runtime.agent.run()


if __name__ == "__main__":
    main()
