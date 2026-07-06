from enum import StrEnum


class Strength(StrEnum):
    """The strength of an extension, either mandatory or optional.

    The value is the key used for the extension declaration header.
    For most purposes it's a boolean mandatory or optional, so the value just
    aids parsing.
    """

    MANDATORY = "Man"
    OPTIONAL = "Opt"


class Scope(StrEnum):
    """The scope of an extension, end-to-end or hop-by-hop.

    The value is the prefix used for the extension declaration header key.
    For most purposes it's a boolean (hop-by-hop or not), so the value just
    aids parsing.
    """

    HOP_BY_HOP = "C"
    END_TO_END = ""
