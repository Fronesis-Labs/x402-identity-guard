"""
Chain client layer for smart contract interactions.
Supports EVM (web3.py) and TRON (tronpy) via one API surface.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union


@dataclass
class TronContractRef:
    """Lightweight TRON contract wrapper used by the shared client API."""

    address: str
    abi: List[Dict[str, Any]]
    contract: Any


class Web3Client:
    """Unified chain client for 8004 contracts."""

    def __init__(
        self,
        rpc_url: str,
        private_key: Optional[str] = None,
        account: Optional[Any] = None,
        chain_type: str = "evm",
        tron_fee_limit: int = 10_000_000,
    ):
        self.rpc_url = rpc_url
        self.chain_type = (chain_type or "evm").lower()
        self.tron_fee_limit = int(tron_fee_limit)
        self.account = None
        self.chain_id = None
        self.w3 = None
        self._tron = None
        self._tron_private_key = None

        if self.chain_type == "tron":
            self._init_tron(private_key=private_key, account=account)
        else:
            self._init_evm(private_key=private_key, account=account)

    def _init_evm(self, private_key: Optional[str], account: Optional[Any]) -> None:
        try:
            from web3 import Web3
            from eth_account import Account
        except ImportError as exc:
            raise ImportError("EVM dependencies not installed. Install with: pip install web3 eth-account") from exc

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        # BSC and other PoA-style EVM chains require PoA middleware to decode blocks.
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception:
            try:
                from web3.middleware.geth_poa import geth_poa_middleware
                self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            except Exception:
                pass
        if not self.w3.is_connected():
            raise ConnectionError("Failed to connect to EVM node")

        if account is not None:
            self.account = account
        elif private_key:
            self.account = Account.from_key(private_key)

        self.chain_id = self.w3.eth.chain_id

    def _init_tron(self, private_key: Optional[str], account: Optional[Any]) -> None:
        try:
            from tronpy import Tron
            from tronpy.providers import HTTPProvider
            from tronpy.keys import PrivateKey
        except ImportError as exc:
            raise ImportError("TRON dependencies not installed. Install with: pip install tronpy") from exc

        self._tron = Tron(provider=HTTPProvider(self.rpc_url))

        if account is not None and isinstance(account, str):
            private_key = account

        if private_key:
            cleaned = private_key[2:] if private_key.startswith("0x") else private_key
            self._tron_private_key = PrivateKey(bytes.fromhex(cleaned))

            class _TronAccount:
                def __init__(self, pk):
                    self.key = pk
                    self.address = pk.public_key.to_base58check_address()

            self.account = _TronAccount(self._tron_private_key)

        # TRON does not expose a canonical EVM-style chain id via tronpy.
        self.chain_id = None

    def _ensure_evm(self) -> None:
        if self.chain_type != "evm":
            raise NotImplementedError("This method is only available on EVM chains")

    def _ensure_tron(self) -> None:
        if self.chain_type != "tron":
            raise NotImplementedError("This method is only available on TRON")

    def get_contract(self, address: str, abi: List[Dict[str, Any]]) -> Any:
        if self.chain_type == "tron":
            contract = self._tron.get_contract(address)
            if abi:
                contract.abi = abi
            return TronContractRef(address=address, abi=abi, contract=contract)
        return self.w3.eth.contract(address=address, abi=abi)

    @staticmethod
    def _pick_tron_function(contract_ref: TronContractRef, method_name: str, params: List[Any]):
        """Pick TRON contract method, resolving overloads by arity when needed."""
        try:
            from tronpy.contract import ContractMethod
        except ImportError as exc:
            raise RuntimeError("tronpy is required") from exc

        # Resolve from ABI by same name and same arg count (preferred for overloaded methods).
        for item in contract_ref.abi or []:
            if item.get("type", "").lower() != "function":
                continue
            if item.get("name") != method_name:
                continue
            if len(item.get("inputs", [])) == len(params):
                return ContractMethod(item, contract_ref.contract)

        # Fallback: non-overloaded function exposure on tronpy object.
        try:
            return getattr(contract_ref.contract.functions, method_name)
        except Exception:
            pass

        raise AttributeError(f"Contract method not found: {method_name}/{len(params)}")

    def call_contract(
        self,
        contract: Any,
        method_name: str,
        *args,
        **kwargs,
    ) -> Any:
        if self.chain_type == "tron":
            method = self._pick_tron_function(contract, method_name, list(args))
            return method(*args, **kwargs)

        method = getattr(contract.functions, method_name)
        return method(*args, **kwargs).call()

    def transact_contract(
        self,
        contract: Any,
        method_name: str,
        *args,
        gas_limit: Optional[int] = None,
        gas_price: Optional[int] = None,
        max_fee_per_gas: Optional[int] = None,
        max_priority_fee_per_gas: Optional[int] = None,
        **kwargs,
    ) -> str:
        if not self.account:
            raise ValueError("Cannot execute transaction: SDK is in read-only mode. Provide a signer to enable write operations.")

        if self.chain_type == "tron":
            method = self._pick_tron_function(contract, method_name, list(args))
            tx = method(*args, **kwargs).with_owner(self.account.address)
            tx = tx.fee_limit(gas_limit or self.tron_fee_limit).build()
            signed = tx.sign(self._tron_private_key)
            result = signed.broadcast()
            if hasattr(result, "wait"):
                try:
                    result.wait()
                except Exception:
                    pass
            txid = getattr(result, "txid", None) or (result.get("txid") if isinstance(result, dict) else None)
            if not txid:
                raise ValueError(f"Failed to broadcast TRON transaction for {method_name}")
            return txid

        method = getattr(contract.functions, method_name)
        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        tx = method(*args, **kwargs).build_transaction({
            "from": self.account.address,
            "nonce": nonce,
        })

        if gas_limit:
            tx["gas"] = gas_limit
        if gas_price:
            tx["gasPrice"] = gas_price
        if max_fee_per_gas:
            tx["maxFeePerGas"] = max_fee_per_gas
        if max_priority_fee_per_gas:
            tx["maxPriorityFeePerGas"] = max_priority_fee_per_gas

        signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
        tx_hash = self.w3.eth.send_raw_transaction(
            signed_tx.rawTransaction if hasattr(signed_tx, "rawTransaction") else signed_tx.raw_transaction
        )
        return tx_hash.hex()

    def wait_for_transaction(
        self,
        tx_hash: str,
        timeout: int = 60,
        confirmations: int = 1,
        throw_on_revert: bool = True,
    ) -> Dict[str, Any]:
        if self.chain_type == "tron":
            start = time.time()
            while True:
                info = self._tron.get_transaction_info(tx_hash)
                if info:
                    receipt = info.get("receipt", {})
                    result = receipt.get("result")
                    if throw_on_revert and result and str(result).upper() not in ("SUCCESS",):
                        raise ValueError(f"TRON transaction reverted: {tx_hash} ({result})")
                    return info
                if time.time() - start > timeout:
                    raise TimeoutError(f"Timed out waiting for TRON tx: {tx_hash}")
                time.sleep(1)

        if confirmations < 1:
            raise ValueError("confirmations must be >= 1")

        start = time.time()
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)

        if throw_on_revert:
            status = receipt.get("status")
            try:
                status_int = int(status)
            except Exception:
                try:
                    status_int = int(status.hex(), 16)  # type: ignore[attr-defined]
                except Exception:
                    status_int = 1
            if status_int == 0:
                raise ValueError(f"Transaction reverted: {tx_hash}")

        if confirmations > 1:
            block_number = receipt.get("blockNumber")
            if block_number is not None:
                target_block = int(block_number) + (confirmations - 1)
                while True:
                    current = int(self.w3.eth.block_number)
                    if current >= target_block:
                        break
                    if time.time() - start > timeout:
                        raise TimeoutError(
                            f"Timed out waiting for confirmations (tx={tx_hash}, confirmations={confirmations})"
                        )
                    time.sleep(1.0)

        return receipt

    def signMessage(self, message: bytes) -> bytes:
        if not self.account:
            raise ValueError("Cannot sign message: SDK is in read-only mode. Provide a signer to enable signing.")
        if self.chain_type == "tron":
            signature = self._tron_private_key.sign_msg_hash(message)
            return bytes.fromhex(signature.hex())

        from eth_account.messages import encode_defunct

        signable_message = encode_defunct(message)
        signed = self.account.sign_message(signable_message)
        return signed.signature

    def recoverAddress(self, message: bytes, signature: bytes) -> str:
        if self.chain_type == "tron":
            raise NotImplementedError("recoverAddress is not implemented for TRON in this unified client")

        from eth_account.messages import encode_defunct

        signable_message = encode_defunct(message)
        return self.w3.eth.account.recover_message(signable_message, signature=signature)

    def keccak256(self, data: bytes) -> bytes:
        if self.chain_type == "tron":
            try:
                from eth_hash.auto import keccak
            except ImportError as exc:
                raise ImportError("eth-hash is required for keccak in TRON mode") from exc
            return keccak(data)
        return self.w3.keccak(data)

    def to_checksum_address(self, address: str) -> str:
        if self.chain_type == "tron":
            return address
        return self.w3.to_checksum_address(address)

    def normalize_address(self, address: str) -> str:
        if self.chain_type == "tron":
            return address

        if address.startswith("0x") or address.startswith("0X"):
            return "0x" + address[2:].lower()
        return address.lower()

    def to_evm_address(self, address: str) -> str:
        """Convert address to canonical EVM 20-byte hex form (0x...)."""
        if not address or not isinstance(address, str):
            raise ValueError("Address must be a non-empty string")

        if self.chain_type != "tron":
            if not self.w3.is_address(address):
                raise ValueError(f"Invalid EVM address: {address}")
            return self.w3.to_checksum_address(address)

        try:
            from tronpy.keys import is_base58check_address, to_hex_address
        except ImportError as exc:
            raise ImportError("tronpy is required for TRON address conversion") from exc

        raw = address.strip()
        if raw.startswith("0x") and len(raw) == 42:
            int(raw[2:], 16)
            return "0x" + raw[2:].lower()

        cleaned = raw[2:] if raw.startswith("0x") else raw
        if len(cleaned) == 42 and cleaned[:2].lower() == "41":
            int(cleaned, 16)
            return "0x" + cleaned[2:].lower()

        if is_base58check_address(raw):
            tron_hex = to_hex_address(raw)
            tron_hex_clean = tron_hex[2:] if tron_hex.startswith("0x") else tron_hex
            return "0x" + tron_hex_clean[-40:].lower()

        raise ValueError(f"Invalid TRON address: {address}")

    def to_chain_address(self, address: str) -> str:
        """Convert address to the chain-native form accepted by transact/call paths."""
        if not address or not isinstance(address, str):
            raise ValueError("Address must be a non-empty string")

        if self.chain_type != "tron":
            return self.to_checksum_address(address)

        try:
            from tronpy.keys import is_base58check_address, to_base58check_address
        except ImportError as exc:
            raise ImportError("tronpy is required for TRON address conversion") from exc

        raw = address.strip()
        if is_base58check_address(raw):
            return raw

        if raw.startswith("0x") and len(raw) == 42:
            int(raw[2:], 16)
            return to_base58check_address("41" + raw[2:])

        cleaned = raw[2:] if raw.startswith("0x") else raw
        if len(cleaned) == 42 and cleaned[:2].lower() == "41":
            int(cleaned, 16)
            return to_base58check_address(cleaned)

        raise ValueError(f"Invalid TRON address: {address}")

    def address_equal(self, a: str, b: str) -> bool:
        """Compare addresses across chain-specific textual formats."""
        try:
            return self.to_evm_address(a).lower() == self.to_evm_address(b).lower()
        except Exception:
            return self.normalize_address(a) == self.normalize_address(b)

    def is_address(self, address: str) -> bool:
        if self.chain_type == "tron":
            try:
                from tronpy.keys import is_base58check_address
            except ImportError as exc:
                raise ImportError("tronpy is required for TRON address validation") from exc
            if is_base58check_address(address):
                return True
            cleaned = address[2:] if address.startswith("0x") else address
            return len(cleaned) == 42 and cleaned.startswith("41")

        return self.w3.is_address(address)

    def get_balance(self, address: str) -> int:
        if self.chain_type == "tron":
            bal = self._tron.get_account_balance(address)
            return int(float(bal) * 1_000_000)
        return self.w3.eth.get_balance(address)

    def get_transaction_count(self, address: str) -> int:
        if self.chain_type == "tron":
            return 0
        return self.w3.eth.get_transaction_count(address)

    def encodeEIP712Domain(
        self,
        name: str,
        version: str,
        chain_id: int,
        verifying_contract: str,
    ) -> Dict[str, Any]:
        return {
            "name": name,
            "version": version,
            "chainId": chain_id,
            "verifyingContract": verifying_contract,
        }

    def build_agent_wallet_set_typed_data(
        self,
        agent_id: int,
        new_wallet: str,
        owner: str,
        deadline: int,
        verifying_contract: str,
        chain_id: int,
    ) -> Dict[str, Any]:
        domain = self.encodeEIP712Domain(
            name="ERC8004IdentityRegistry",
            version="1",
            chain_id=chain_id,
            verifying_contract=verifying_contract,
        )

        message_types = {
            "AgentWalletSet": [
                {"name": "agentId", "type": "uint256"},
                {"name": "newWallet", "type": "address"},
                {"name": "owner", "type": "address"},
                {"name": "deadline", "type": "uint256"},
            ]
        }

        message = {
            "agentId": agent_id,
            "newWallet": new_wallet,
            "owner": owner,
            "deadline": deadline,
        }

        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **message_types,
            },
            "domain": domain,
            "primaryType": "AgentWalletSet",
            "message": message,
        }

    def sign_typed_data(
        self,
        full_message: Dict[str, Any],
        signer: Union[str, Any],
    ) -> bytes:
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        if isinstance(signer, str):
            cleaned = signer[2:] if signer.startswith("0x") else signer
            acct = Account.from_key(cleaned)
        elif hasattr(signer, "sign_message"):
            acct = signer
        elif hasattr(signer, "private_key"):
            key_val = getattr(signer, "private_key")
            if isinstance(key_val, bytes):
                acct = Account.from_key(key_val)
            else:
                key_str = str(key_val)
                key_str = key_str[2:] if key_str.startswith("0x") else key_str
                acct = Account.from_key(key_str)
        elif hasattr(signer, "key"):
            key_obj = getattr(signer, "key")
            key_hex = key_obj.hex() if hasattr(key_obj, "hex") else str(key_obj)
            key_hex = key_hex[2:] if key_hex.startswith("0x") else key_hex
            acct = Account.from_key(key_hex)
        else:
            raise ValueError("Unsupported signer type for typed-data signing")

        encoded = encode_typed_data(full_message=full_message)
        signed = acct.sign_message(encoded)
        return signed.signature

    def signEIP712Message(
        self,
        domain: Dict[str, Any],
        message_types: Dict[str, List[Dict[str, str]]],
        message: Dict[str, Any],
    ) -> bytes:
        self._ensure_evm()

        if not self.account:
            raise ValueError("Cannot sign message: SDK is in read-only mode. Provide a signer to enable signing.")

        from eth_account.messages import encode_typed_data

        structured_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **message_types,
            },
            "domain": domain,
            "primaryType": list(message_types.keys())[0] if message_types else "Message",
            "message": message,
        }

        encoded = encode_typed_data(full_message=structured_data)
        signed = self.account.sign_message(encoded)
        return signed.signature

    def verifyEIP712Signature(
        self,
        domain: Dict[str, Any],
        message_types: Dict[str, List[Dict[str, str]]],
        message: Dict[str, Any],
        signature: bytes,
    ) -> str:
        self._ensure_evm()

        from eth_account.messages import encode_typed_data

        structured_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **message_types,
            },
            "domain": domain,
            "primaryType": list(message_types.keys())[0] if message_types else "Message",
            "message": message,
        }

        encoded = encode_typed_data(full_message=structured_data)
        return self.w3.eth.account.recover_message(encoded, signature=signature)
