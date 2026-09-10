"""Fetch complete test fixtures by immutable commit and verify exact bytes."""
from pathlib import Path
import hashlib
import urllib.request

COMMIT = "e5c7628b0490bad0665d95d675ce4072ed903f4b"
BASE = f"https://raw.githubusercontent.com/kubernetes-csi/csi-driver-smb/{COMMIT}"
FILES = {
    "compatibility.md": ("README.md", "999d19c120b1ccf1deaea15c24d467a701cc87b0267334db0cafb80acfec5e0f"),
    "index.yaml": ("charts/index.yaml", "95add5a7a6b4a8f82de657c4c98d6fc82d3f1d0712c8fcf79b5a76c2147f280e"),
}
target = Path(__file__).parent / "tests/fixtures/csi-driver-smb"
target.mkdir(parents=True, exist_ok=True)
for name, (source, expected) in FILES.items():
    with urllib.request.urlopen(f"{BASE}/{source}", timeout=25) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(f"Fixture integrity check failed: {name}")
    (target / name).write_bytes(data)
    print(f"Fixture verified: {name}, {len(data)} bytes")
