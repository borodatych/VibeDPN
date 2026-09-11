"""Side-effecting engine: host network rules, WireGuard keys and peers, Mysterium client, DNS.

Every module here talks to the outside world (nft, ip, TequilAPI, files). Pure logic that these
modules need is kept importable without the environment so it can be unit-tested.
"""
