import logging
from dataclasses import dataclass
from typing import override

from gossip.upnp.uri import UPNP_DOMAIN

log = logging.getLogger(__name__)


@dataclass
class ExtensionHeader:
    """A header representing an extension to a typical SSDP message."""

    key: str
    domain: str

    @override
    def __str__(self):
        return ".".join((self.key, self.domain)).upper()


TCP_PORT = ExtensionHeader("tcpport", UPNP_DOMAIN)
BOOT_ID = ExtensionHeader("bootid", UPNP_DOMAIN)
NEXT_BOOT_ID = ExtensionHeader("nextbootid", UPNP_DOMAIN)
CONFIG_ID = ExtensionHeader("configid", UPNP_DOMAIN)
SEARCH_PORT = ExtensionHeader("searchport", UPNP_DOMAIN)
SECURE_LOCATION = ExtensionHeader("securelocation", UPNP_DOMAIN)
CPFN = ExtensionHeader("cpfn", UPNP_DOMAIN)
CPUUID = ExtensionHeader("cpuuid", UPNP_DOMAIN)
