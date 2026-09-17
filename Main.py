import json
import threading
import time
import requests

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from eth_account import Account
from eth_abi import encode as abi_encode

# =====================================================================
# PASTE YOUR COMPILED BYTECODE HERE
# =====================================================================
# Compile SOS69069cSOS.sol with solc 0.8.36 (optimizer, 200 runs).
# In Remix: Compilation Details → bytecode → object → copy the long
# hex string starting with "6080604052..." (WITHOUT the 0x prefix is fine,
# the code adds it back).
CONTRACT_BYTECODE = "0x608060405234801561001057600080fd5b506040516100..."  # <-- REPLACE THIS

# =====================================================================
# ABI (from your paste — trimmed to constructor only, since that is
# all we need for deployment; the full ABI below is kept for reference
# and for the post-deploy read-back checks).
# =====================================================================
CONSTRUCTOR_TYPES = ["uint256", "address"]

# Minimal ABI entries needed for read-back verification after deploy
POST_DEPLOY_ABI = [
    {"inputs": [], "name": "TREASURY", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "MINT_FEE", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "LEDGER",   "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

# ---- JSON-RPC helper -------------------------------------------------

def rpc(url, method, params):
    r = requests.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


def encode_call(selector_hex, arg_types, args):
    """ABI-encode a call: 4-byte selector + encoded args."""
    return selector_hex + abi_encode(arg_types, args).hex()


# 4-byte selectors (keccak of signature, first 4 bytes)
# You can verify these on https://www.4byte.directory
SEL_TREASURY = "0x61d027b3"  # TREASURY()
SEL_MINT_FEE = "0x13966db5"  # MINT_FEE()
SEL_LEDGER   = "0x72655f5e"  # LEDGER()


def deploy_contract(rpc_url, chain_id, private_key, mint_fee, treasury):
    acct = Account.from_key(private_key)

    # --- ABI encode constructor args ---
    if not CONTRACT_BYTECODE.startswith("0x"):
        bytecode = "0x" + CONTRACT_BYTECODE
    else:
        bytecode = CONTRACT_BYTECODE
    if len(bytecode) < 100:
        raise ValueError("CONTRACT_BYTECODE looks empty — did you paste it?")

    args_blob = abi_encode(CONSTRUCTOR_TYPES, [int(mint_fee), treasury]).hex()
    data = bytecode + args_blob

    # --- Pre-flight ---
    nonce = int(rpc(rpc_url, "eth_getTransactionCount", [acct.address, "pending"]), 16)
    try:
        gas_price = int(rpc(rpc_url, "eth_gasPrice", []), 16)
    except Exception:
        gas_price = int(rpc(rpc_url, "eth_maxPriorityFeePerGas", []), 16)

    # Estimate gas for the deployment tx
    est = rpc(rpc_url, "eth_estimateGas", [{
        "from": acct.address,
        "data": data,
        "value": "0x0",
    }])
    gas_limit = int(int(est, 16) * 1.25)  # 25% buffer

    tx = {
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": gas_limit,
        "to": None,          # contract creation
        "value": 0,
        "data": data,
        "chainId": int(chain_id),
    }

    signed = acct.sign_transaction(tx)
    raw = signed.raw_transaction.hex()
    if not raw.startswith("0x"):
        raw = "0x" + raw

    tx_hash = rpc(rpc_url, "eth_sendRawTransaction", [raw])

    # --- Wait for receipt ---
    for _ in range(180):  # up to 6 minutes
        receipt = rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if receipt:
            if receipt.get("status") != "0x1":
                raise RuntimeError(f"Tx reverted: {tx_hash}")
            return receipt["contractAddress"], tx_hash
        time.sleep(2)

    raise TimeoutError(f"No receipt after 6 minutes. Tx hash: {tx_hash}")


def read_contract_addr(rpc_url, contract, selector):
    """Call a view function that returns one address."""
    result = rpc(rpc_url, "eth_call", [
        {"to": contract, "data": selector},
        "latest",
    ])
    return "0x" + result[-40:]


def read_contract_uint(rpc_url, contract, selector):
    result = rpc(rpc_url, "eth_call", [
        {"to": contract, "data": selector},
        "latest",
    ])
    return int(result, 16)


# ---- UI --------------------------------------------------------------

class Root(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=20, spacing=10, **kw)

        self.add_widget(Label(
            text="SOS69069cSOS Deployer",
            size_hint_y=0.06,
            font_size="20sp",
            bold=True,
        ))

        # --- Inputs ---
        self.pk = self._add_input(
            "Private key (0x...) — NOT stored, sent only to RPC",
            password=True,
        )
        self.rpc_url = self._add_input(
            "RPC URL (e.g. https://sepolia.infura.io/v3/KEY)",
        )
        self.chain_id = self._add_input(
            "Chain ID (1 = mainnet, 11155111 = Sepolia)", numeric=True,
        )
        self.mint_fee = self._add_input(
            "MINT_FEE in wei (recommended: 0)", numeric=True,
        )
        self.treasury = self._add_input(
            "TREASURY address (0x...)",
        )

        # --- Prefill for Sepolia test ---
        self.chain_id.text = "11155111"
        self.mint_fee.text = "0"

        # --- Deploy button ---
        self.btn = Button(text="Deploy Contract", size_hint_y=0.09)
        self.btn.bind(on_press=self.on_deploy)
        self.add_widget(self.btn)

        # --- Log ---
        sv = ScrollView()
        self.log = Label(
            text="Ready. Test on Sepolia first!\n",
            size_hint_y=None, halign="left", valign="top",
        )
        self.log.bind(width=lambda *_: setattr(self.log, "text_size", (self.log.width, None)))
        self.log.bind(texture_size=lambda *_: setattr(self.log, "height", self.log.texture_size[1]))
        sv.add_widget(self.log)
        self.add_widget(sv)

    def _add_input(self, hint, password=False, numeric=False):
        ti = TextInput(
            hint_text=hint,
            password=password,
            multiline=False,
            input_filter="int" if numeric else None,
            size_hint_y=0.07,
        )
        self.add_widget(ti)
        return ti

    def log_msg(self, msg):
        def _do(*_):
            self.log.text += msg + "\n"
        Clock.schedule_once(_do)

    def on_deploy(self, *_):
        pk = self.pk.text.strip()
        rpc_url = self.rpc_url.text.strip()
        chain_id = self.chain_id.text.strip()
        mint_fee = self.mint_fee.text.strip() or "0"
        treasury = self.treasury.text.strip()

        if not all([pk, rpc_url, chain_id, treasury]):
            self.log_msg("❌ Fill in all fields.")
            return

        # Safety net for mainnet
        if chain_id == "1":
            self.log_msg("⚠️  MAINNET — make sure you tested on Sepolia first.")
            time.sleep(0.1)

        self.log_msg(f"→ Deploying to chain {chain_id} …")
        threading.Thread(
            target=self._worker,
            args=(rpc_url, chain_id, pk, mint_fee, treasury),
            daemon=True,
        ).start()

    def _worker(self, rpc_url, chain_id, pk, mint_fee, treasury):
        try:
            addr, h = deploy_contract(rpc_url, chain_id, pk, mint_fee, treasury)
            self.log_msg(f"✅ Contract deployed: {addr}")
            self.log_msg(f"   Tx: {h}")

            # Post-deploy read-back sanity check
            try:
                got_treasury = read_contract_addr(rpc_url, addr, SEL_TREASURY)
                got_fee = read_contract_uint(rpc_url, addr, SEL_MINT_FEE)
                got_ledger = read_contract_addr(rpc_url, addr, SEL_LEDGER)

                self.log_msg(f"   TREASURY = {got_treasury}")
                self.log_msg(f"   MINT_FEE = {got_fee}")
                self.log_msg(f"   LEDGER   = {got_ledger}")

                if got_treasury.lower() != treasury.lower():
                    self.log_msg("   ⚠️  TREASURY mismatch — check your input!")
                if got_fee != int(mint_fee):
                    self.log_msg("   ⚠️  MINT_FEE mismatch — check your input!")
            except Exception as e:
                self.log_msg(f"   (read-back failed: {e})")

            self.log_msg("→ Verify on Etherscan for source + ABI access.")
        except Exception as e:
            self.log_msg(f"❌ Deployment failed:\n{e}")


class DeployerApp(App):
    def build(self):
        return Root()


if __name__ == "__main__":
    DeployerApp().run()
