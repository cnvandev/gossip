from gossip.http.extension import Extension, Strength
from gossip.internet.uri import URI

UPNP_EXTENSION = Extension(
    URI.parse("http://schemas.upnp.org/upnp/1/0/"),
    {
        "SEARCH": {
            Strength.OPTIONAL: {"": str},
        },
        "NOTIFY": {
            Strength.OPTIONAL: {"": str},
        },
    },
)
