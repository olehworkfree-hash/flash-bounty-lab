# FLASH Bounty Lab — public work sample

Independent, AI-assisted documentation and reproducible local Python examples.
This is not the private FLASH trading project, a deployed bot or an earnings report.

## Contents

- `flint_sample/`: four-gate synthetic inventory example, including CLI hardening.
- `content/FLINT_THREAD_EN.txt`: six-post English draft for human review.
- `evidence/`: actual local test logs and file integrity manifest.

## Run

Python 3.10 or newer, with no third-party dependencies:

```sh
cd flint_sample
python -m unittest discover -v
python readiness.py cold_start.json
```

42 local tests passed on 2026-09-05. No GitHub Actions run is claimed.
The CLI makes no HTTP calls, uses no wallet, and never authorizes a trade.
Read `flint_sample/README.md` and the publication review before reuse.

## Publication boundaries

No API keys, private keys, claim links, authentication requests or account exports
belong in this repository. The fixtures and privacy-test markers are synthetic.
This package may be shared for review. It contains no private FLASH work log.
No endorsement, formal bounty submission, accepted job, prize or payment is implied.
