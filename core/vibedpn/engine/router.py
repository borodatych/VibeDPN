"""Host routing: nftables sets, fwmarks and ``ip rule`` tables rendered from templates.

The only module allowed to change host networking. It never touches the host default route:
each uplink is a gateway container, and this module only steers marked LAN traffic to it.
Implemented in Stage 4 (modes ``off``/``full``, table ``vps``), extended in Stages 5, 8, 10.
"""
