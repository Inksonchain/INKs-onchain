# Manifold contract audit (read-only)

## Scope

The inspector checks the public EVM addresses configured in `config/evm-contracts.json` on Ethereum Mainnet and Base. It does not sign or submit transactions, call state-changing contract methods, or require private keys.

## Run locally

Requires Python 3.12 and public JSON-RPC access:

```bash
python scripts/inspect_manifold.py
```

Optional RPC overrides:

- `RPC_URL_ETHEREUM`
- `RPC_URL_BASE`

The default endpoints are public and may rate-limit. Use trusted RPC endpoints if needed; never place private keys in these variables.

## GitHub Actions

Run **Read-only Manifold contract audit** manually from Actions, or wait for the weekly schedule. The JSON report is uploaded as an artifact for 30 days. The workflow has `contents: read` only and does not commit generated data to the repository.

## What the report means

- `hasCode`: RPC returned deployed bytecode at the configured address.
- `detectedStandards`: ERC-165 interface probes returned true. Some proxies or non-standard implementations may not respond as expected.
- `eip1967Implementation` / `eip1967Beacon`: non-zero values in standard EIP-1967 storage slots, if present.
- `manifoldAttribution`: deliberately remains `unconfirmed`; these probes cannot prove a contract is deployed or managed by Manifold.
- `totalSupply`: value returned by the conventional `totalSupply()` selector, if supported. For ERC-1155 this is generally not a global supply value.

This is a preliminary technical inventory, not a smart-contract security audit. Manifold attribution and extension compatibility must be confirmed against official deployment records, verified source/ABI, and relevant contract state before implementing additional functionality.
