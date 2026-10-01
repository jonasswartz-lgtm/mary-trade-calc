"""Encrypt data/players.json with the league password (AES-256-GCM, PBKDF2).

Output: _site/data/players.enc.json, decrypted in the browser with WebCrypto.
Fails if SITE_PASSWORD is not set, so plaintext data is never published.
"""

import base64
import json
import os
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 250_000

pw = os.environ.get("SITE_PASSWORD", "")
if not pw:
    print("SITE_PASSWORD secret is not set; refusing to publish.", file=sys.stderr)
    sys.exit(1)

plain = open("data/players.json", "rb").read()
salt, iv = os.urandom(16), os.urandom(12)
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
ct = AESGCM(key).encrypt(iv, plain, None)  # ciphertext || 16-byte tag, as WebCrypto expects

b64 = lambda b: base64.b64encode(b).decode()
os.makedirs("_site/data", exist_ok=True)
with open("_site/data/players.enc.json", "w") as f:
    json.dump({"v": 1, "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}, f)
print(f"encrypted {len(plain)} bytes")
