#!/usr/bin/env python3
"""Read-only EVM contract inspector for INKs-onChain.

No wallet, private key, transaction submission, or contract mutation is used.
The result is evidence for manual review, not a security audit or proof that a
contract is operated by Manifold.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "evm-contracts.json"
OUT_PATH = Path(os.environ.get("AUDIT_OUTPUT", str(ROOT / "data" / "contracts-audit.json")))
RPC_DEFAULTS = {
    "ethereum": "https://cloudflare-eth.com",
    "base": "https://mainnet.base.org",
}
# EIP-1967 implementation and beacon storage slots.
IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
SELECTORS = {
    "name": "0x06fdde03",
    "symbol": "0x95d89b41",
    "totalSupply": "0x18160ddd",
    "supportsInterface": "0x01ffc9a7",
}
INTERFACES = {
    "ERC165": "0x01ffc9a7",
    "ERC721": "0x80ac58cd",
    "ERC721Metadata": "0x5b5e139f",
    "ERC1155": "0xd9b67a26",
}
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class RpcError(RuntimeError):
    pass


def rpc(chain: str, method: str, params: list[Any]) -> Any:
    url = os.environ.get(f"RPC_URL_{chain.upper()}", RPC_DEFAULTS[chain])
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "INKs-ContractInspector/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read(1_000_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RpcError(f"RPC request failed ({type(exc).__name__})") from exc
    if "error" in body:
        raise RpcError(str(body["error"])[:300])
    if "result" not in body:
        raise RpcError("RPC response has no result")
    return body["result"]


def decode_abi_string(value: str) -> str | None:
    try:
        raw = bytes.fromhex(value.removeprefix("0x"))
        if not raw:
            return None
        # ABI dynamic string: offset, length, UTF-8 bytes.
        offset = int.from_bytes(raw[:32], "big")
        if offset + 32 <= len(raw):
            length = int.from_bytes(raw[offset:offset + 32], "big")
            start = offset + 32
            if length <= len(raw) - start:
                return raw[start:start + length].decode("utf-8", "replace")
        # Some older contracts return bytes32 for name/symbol.
        return raw[:32].rstrip(b"\x00").decode("utf-8", "replace") or None
    except (ValueError, IndexError):
        return None


def eth_call(chain: str, address: str, data: str) -> str | None:
    try:
        result = rpc(chain, "eth_call", [{"to": address, "data": data}, "latest"])
        return result if isinstance(result, str) else None
    except RpcError:
        return None


def storage_address(value: str | None) -> str | None:
    if not value or value == "0x" or int(value, 16) == 0:
        return None
    candidate = "0x" + value[-40:]
    return candidate if ADDRESS_RE.fullmatch(candidate) else None


def inspect_contract(contract: dict[str, Any]) -> dict[str, Any]:
    chain = contract["chain"]
    address = contract["address"]
    result: dict[str, Any] = {
        "collection": contract["collection"],
        "chain": chain,
        "chainId": contract["chainId"],
        "address": address,
        "explorer": contract.get("explorer"),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "evidence": [],
        "warnings": [
            "Read-only RPC inspection only; this does not prove ownership, audit safety, or Manifold provenance."
        ],
    }
    try:
        code = rpc(chain, "eth_getCode", [address, "latest"])
        result["hasCode"] = isinstance(code, str) and code not in ("0x", "0x0")
        if not result["hasCode"]:
            result["status"] = "no_contract_code"
            result["warnings"].append("No deployed bytecode was returned at this address on the selected chain.")
            return result
        result["runtimeBytecodeBytes"] = max(0, (len(code) - 2) // 2)
        result["evidence"].append("Deployed bytecode found")

        name_raw = eth_call(chain, address, SELECTORS["name"])
        symbol_raw = eth_call(chain, address, SELECTORS["symbol"])
        supply_raw = eth_call(chain, address, SELECTORS["totalSupply"])
        result["name"] = decode_abi_string(name_raw) if name_raw else None
        result["symbol"] = decode_abi_string(symbol_raw) if symbol_raw else None
        try:
            result["totalSupply"] = int(supply_raw, 16) if supply_raw and supply_raw != "0x" else None
        except ValueError:
            result["totalSupply"] = None

        detected = {}
        for label, interface_id in INTERFACES.items():
            # supportsInterface(bytes4): bytes4 argument is left-aligned in a 32-byte word.
            raw = eth_call(chain, address, SELECTORS["supportsInterface"] + interface_id[2:] + "0" * 56)
            detected[label] = bool(raw and raw != "0x" and int(raw, 16) != 0)
        result["interfaces"] = detected
        standards = [name for name in ("ERC721", "ERC1155") if detected.get(name)]
        result["detectedStandards"] = standards
        if standards:
            result["evidence"].append("supportsInterface returned true for: " + ", ".join(standards))
        else:
            result["warnings"].append(
                "ERC721/ERC1155 could not be confirmed through ERC-165. A proxy or non-standard contract may need manual ABI review."
            )

        implementation = storage_address(rpc(chain, "eth_getStorageAt", [address, IMPLEMENTATION_SLOT, "latest"]))
        beacon = storage_address(rpc(chain, "eth_getStorageAt", [address, BEACON_SLOT, "latest"]))
        result["eip1967Implementation"] = implementation
        result["eip1967Beacon"] = beacon
        if implementation:
            result["evidence"].append("Non-zero EIP-1967 implementation slot found")
        if beacon:
            result["evidence"].append("Non-zero EIP-1967 beacon slot found")

        # Heuristic only: selectors/metadata and EIP-1967 slots are not proof of Manifold.
        result["manifoldAttribution"] = "unconfirmed"
        result["warnings"].append(
            "Confirm Manifold provenance by comparing address, implementation and extension state with official Manifold deployment records."
        )
        result["status"] = "ok"
    except RpcError as exc:
        result["status"] = "rpc_error"
        result["error"] = str(exc)
    return result


def main() -> int:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        contracts = config["contracts"]
        if not isinstance(contracts, list) or not contracts:
            raise ValueError("config contracts must be a non-empty list")
        for item in contracts:
            if not ADDRESS_RE.fullmatch(item.get("address", "")):
                raise ValueError(f"Invalid EVM address for {item.get('collection', 'unknown')}")
            if item.get("chain") not in RPC_DEFAULTS:
                raise ValueError(f"Unsupported chain: {item.get('chain')}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    results = []
    for contract in contracts:
        results.append(inspect_contract(contract))
        time.sleep(0.15)

    output = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "read-only",
        "sourceConfig": "config/evm-contracts.json",
        "summary": {
            "total": len(results),
            "ok": sum(item["status"] == "ok" for item in results),
            "errors": sum(item["status"] != "ok" for item in results),
            "manifoldConfirmed": 0,
        },
        "contracts": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))
    print(f"Audit report written to {OUT_PATH}")
    return 0 if output["summary"]["ok"] == output["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
