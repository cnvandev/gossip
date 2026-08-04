import hashlib
from enum import IntEnum
from ipaddress import ip_address

ROOT_SERVERS = {
    "a.root-servers.net": ip_address("198.41.0.4"), # Verisign, Inc.
    "b.root-servers.net": ip_address("170.247.170.2"), # University of Southern California, Information Sciences Institute
    "c.root-servers.net": ip_address("192.33.4.12"), # Cogent Communications
    "d.root-servers.net": ip_address("199.7.91.13"), # University of Maryland
    "e.root-servers.net": ip_address("192.203.230.10"), # NASA (Ames Research Center)
    "f.root-servers.net": ip_address("192.5.5.241"), # Internet Systems Consortium, Inc.
    "g.root-servers.net": ip_address("192.112.36.4"), # US Department of Defense (NIC)
    "h.root-servers.net": ip_address("198.97.190.53"), # US Army (Research Lab)
    "i.root-servers.net": ip_address("192.36.148.17"), # Netnod
    "j.root-servers.net": ip_address("192.58.128.30"), # Verisign, Inc.
    "k.root-servers.net": ip_address("193.0.14.129"), # RIPE NCC
    "l.root-servers.net": ip_address("199.7.83.42"), # ICANN
    "m.root-servers.net": ip_address("202.12.27.33"), # WIDE Project
}


TSIG_ALGORITHMS = {
    "hmac-sha256.": hashlib.sha256,
    "hmac-sha512.": hashlib.sha512,
    "hmac-sha384.": hashlib.sha384,
    "hmac-sha224.": hashlib.sha224,
    "hmac-sha1.": hashlib.sha1,
    "hmac-md5.sig-alg.reg.int.": hashlib.md5,
}


class RecordType(IntEnum):
    """DNS record types."""

    A = 1 # a host address
    NS = 2 # an authoritative name server
    MD = 3 # a mail destination (OBSOLETE - use MX)
    MF = 4 # a mail forwarder (OBSOLETE - use MX)
    CNAME = 5 # the canonical name for an alias
    SOA = 6 # marks the start of a zone of authority
    MB = 7 # a mailbox domain name (EXPERIMENTAL)
    MG = 8 # a mail group member (EXPERIMENTAL)
    MR = 9 # a mail rename domain name (EXPERIMENTAL)
    NULL = 10 # a null RR (EXPERIMENTAL)
    WKS = 11 # a well known service description
    PTR = 12 # a domain name pointer
    HINFO = 13 # host information
    MINFO = 14 # mailbox or mail list information
    MX = 15 # mail exchange
    TXT = 16 # text strings
    RP = 17 # for Responsible Person
    AFSDB = 18 # for AFS Data Base location
    X25 = 19 # for X.25 PSDN address
    ISDN = 20 # for ISDN address
    RT = 21 # for Route Through
    SIG = 24 # for security signature
    KEY = 25 # for security key
    PX = 26 # X.400 mail mapping information
    GPOS = 27 # Geographical Position
    AAAA = 28 # IP6 Address
    LOC = 29 # Location Information
    NXT = 30 # Next Domain (OBSOLETE)
    EID = 31 # Endpoint Identifier
    NIMLOC = 32 # Nimrod Locator
    SRV = 33 # Server Selection
    ATMA = 34 # ATM Address
    NAPTR = 35 # Naming Authority Pointer
    KX = 36 # Key Exchanger
    CERT = 37 # CERT
    DNAME = 39 # DNAME
    SINK = 40 # SINK
    OPT = 41 # OPT
    APL = 42 # APL
    DS = 43 # Delegation Signer
    SSHFP = 44 # SSH Key Fingerprint
    IPSECKEY = 45 # IPSECKEY
    RRSIG = 46 # RRSIG
    NSEC = 47 # NSEC
    DNSKEY = 48 # DNSKEY
    DHCID = 49 # DHCID
    NSEC3 = 50 # NSEC3
    NSEC3PARAM = 51 # NSEC3PARAM
    TLSA = 52 # TLSA
    SMIMEA = 53 # S/MIME cert association
    HIP = 55 # Host Identity Protocol
    NINFO = 56 # NINFO
    RKEY = 57 # RKEY
    TALINK = 58 # Trust Anchor LINK
    CDS = 59 # Child DS
    CDNSKEY = 60 # DNSKEY(s) the Child wants reflected in DS
    OPENPGPKEY = 61 # OpenPGP Key
    CSYNC = 62 # Child-To-Parent Synchronization
    ZONEMD = 63 # Message Digest Over Zone Data
    SVCB = 64 # General-purpose service binding
    HTTPS = 65 # SVCB-compatible type for use with HTTP
    DSYNC = 66 # Endpoint discovery for delegation synchronization
    HHIT = 67 # Hierarchical Host Identity Tag
    BRID = 68 # UAS Broadcast Remote Identification
    SPF = 99
    UINFO = 100
    UID = 101
    GID = 102
    UNSPEC = 103
    NID = 104
    L32 = 105
    L64 = 106
    LP = 107
    EUI48 = 108 # an EUI-48 address
    EUI64 = 109 # an EUI-64 address
    NXNAME = 128 # NXDOMAIN indicator for Compact Denial of Existence
    TKEY = 249 # Transaction Key
    TSIG = 250 # Transaction Signature
    IXFR = 251 # incremental transfer
    AXFR = 252 # transfer of an entire zone
    MAILB = 253 # mailbox-related RRs (MB, MG or MR)
    MAILA = 254 # mail agent RRs (OBSOLETE - see MX)
    ANY = 255 # A request for some or all records the server has available
    URI = 256 # URI
    CAA = 257 # Certification Authority Restriction
    AVC = 258 # Application Visibility and Control
    DOA = 259 # Digital Object Architecture
    AMTRELAY = 260 # Automatic Multicast Tunneling Relay
    RESINFO = 261 # Resolver Information as Key/Value Pairs
    WALLET = 262 # Public wallet address
    CLA = 263 # BP Convergence Layer Adapter
    IPN = 264 # BP Node Number
    TA = 32768 # DNSSEC Trust Authorities
    DLV = 32769 # DNSSEC Lookaside Validation (OBSOLETE)


class RecordClass(IntEnum):
    """DNS record classes."""

    IN = 1  # Internet
    CS = 2  # CSNET (obsolete)
    CH = 3  # CHAOS
    HS = 4  # Hesiod
    NONE = 254 # None (for deleting updates)
    ANY = 255 # Any (for updates)
