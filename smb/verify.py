"""Run the candidate against unchanged Plural helpers and public upstream sources.

Only a disposable checkout is written. No deployment, API secrets, payments or
LLM calls are used. Helm template is rendering, not a Kubernetes runtime test.
"""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

PIN = "66bad0cd9d6b11215a2b35f4672441ec19671320"
ROOT = Path(sys.argv[1]).resolve()
SOURCE = Path(__file__).with_name("csi-driver-smb.py")
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == PIN
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("EXA_API_KEY", None)
work = ROOT / "utils/compatibility"
shutil.copyfile(SOURCE, work / "scrapers/csi-driver-smb.py")
sys.path.insert(0, str(work))
os.chdir(work)
import utils
assert not utils.summarization_enabled(), "Paid summarization must stay disabled"
spec = importlib.util.spec_from_file_location("smb_candidate", SOURCE)
smb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smb)
# fetch_page is the real upstream implementation. Bound its underlying HTTP
# transport's time without changing parsed data, caching, or HTTP status policy.
original_get = utils.requests.get

def bounded_get(*args, **kwargs):
    kwargs.setdefault("timeout", 25)
    return original_get(*args, **kwargs)

utils.requests.get = bounded_get
ceiling = utils.current_kube_version()
markdown = utils.fetch_page(smb.README_URL)
index_bytes = utils.fetch_page(smb.INDEX_URL)
assert markdown and index_bytes, "Full public source retrieval failed"
(OUT / "README.source.md").write_bytes(markdown)
(OUT / "index.source.yaml").write_bytes(index_bytes)
rows = smb.extract_versions(markdown.decode("utf-8"), yaml.safe_load(index_bytes), ceiling)
assert rows and len({r["version"] for r in rows}) == len(rows)
metadata = {
    "icon": "https://avatars.githubusercontent.com/u/33050221?v=4",
    "git_url": "https://github.com/kubernetes-csi/csi-driver-smb",
    "release_url": "https://github.com/kubernetes-csi/csi-driver-smb/releases/tag/v{vsn}",
    "helm_repository_url": smb.HELM_REPOSITORY_URL,
    "chart_name": smb.APP_NAME,
    "readme_url": "https://github.com/kubernetes-csi/csi-driver-smb/blob/master/README.md",
    "compatibility_notes": "Upstream-declared minimum through KUBE_VERSION, not a runtime-tested matrix. Existing SMB server required. Windows CSI Proxy is not required with HostProcess containers.",
    "versions": []
}
target = ROOT / "static/compatibilities/csi-driver-smb.yaml"
assert not target.exists(), "Refuse to overwrite an upstream SMB catalog entry"
target.write_text(yaml.safe_dump(metadata, sort_keys=False))
errors = []
old_error = utils.print_error

def capture_error(message):
    errors.append(str(message))
    old_error(message)

utils.print_error = capture_error
# No updater mock: executes read/merge/reduce, real Helm image extraction and write.
smb.scrape()
assert not errors, f"Upstream reported errors: {errors}"
first = target.read_bytes()
generated = yaml.safe_load(first)
assert [r["version"] for r in generated["versions"]] == [r["version"] for r in rows]
for expected, row in zip(rows, generated["versions"]):
    assert row["chart_version"] == expected["chart_version"]
    assert row["kube"] == expected["kube"]
    assert row.get("images") and all(isinstance(x, str) for x in row["images"])
    assert any(f"smbplugin:v{row['version']}" in x for x in row["images"]), row["images"]
for key, value in metadata.items():
    if key != "versions":
        assert generated[key] == value, f"Metadata changed: {key}"
smb.scrape()
assert not errors and target.read_bytes() == first, "Second generation was not stable"
# Existing summary must survive refresh through the real updater.
seed = copy.deepcopy(generated)
seed["versions"][0]["summary"] = {"helm_changes": "synthetic retention control", "chart_updates": [], "features": [], "breaking_changes": []}
target.write_text(yaml.safe_dump(seed, sort_keys=False))
smb.scrape()
assert yaml.safe_load(target.read_bytes())["versions"][0]["summary"] == seed["versions"][0]["summary"]
# Restore generated output, then test a failed source retrieval keeps bytes intact.
target.write_bytes(first)
real_fetch = utils.fetch_page
utils.fetch_page = lambda url: None if url == smb.INDEX_URL else real_fetch(url)
count_before = len(errors)
smb.scrape()
assert len(errors) == count_before + 1 and target.read_bytes() == first
utils.fetch_page = real_fetch
shutil.copyfile(target, OUT / "csi-driver-smb.generated.yaml")
report = {
    "upstream_commit": PIN,
    "source_sha256": {"README": hashlib.sha256(markdown).hexdigest(), "index": hashlib.sha256(index_bytes).hexdigest()},
    "source_bytes": {"README": len(markdown), "index": len(index_bytes)},
    "kube_ceiling": ceiling,
    "versions": [{"version": x["version"], "chart": x["chart_version"], "images": x["images"]} for x in generated["versions"]],
    "real_shared_updater": True, "real_helm_rendering": True,
    "second_generation_identical": True, "summary_retained": True,
    "failed_source_preserves_file": True, "kubernetes_runtime_tested": False,
    "financial_operations": False
}
(OUT / "LIVE_RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
print("SMB_INTEGRATION_RESULT=" + json.dumps(report, sort_keys=True))
