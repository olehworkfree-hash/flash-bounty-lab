# SMB CSI contributor candidate: reconciled validation

This isolated review branch combines the strict YAML loader from the earlier 41-test candidate with the real Plural/Helm integration. It is not a Plural fork or an upstream pull request. No award is claimed.

The workflow fetches full fixtures by immutable commit with SHA-256 checks, runs the original Plural compatibility suite, installs the candidate and all 41 targeted tests, runs the combined suite, and checks real generation plus malformed-source retention controls. Actual results are in the workflow log; this README does not assume success.

Local command after installing PyYAML:

```sh
python smb/fetch_fixtures.py
python -m unittest discover -s smb/tests -p test_csi_driver_smb.py -v
```

The upstream target is pluralsh/console at 66bad0cd9d6b11215a2b35f4672441ec19671320. Kubernetes ranges express documented minimum requirements bounded by KUBE_VERSION, not runtime-tested compatibility.

Independent AI-assisted work. No confidential account data, wallet operations, deployment or paid API calls are included. Source fixtures are under the upstream Apache-2.0 license.
