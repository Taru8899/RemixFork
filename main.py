import os
import threading
import time
import webbrowser
import traceback

# =====================================================================
# Kivy imports first — these MUST succeed for anything to render
# =====================================================================
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput

# =====================================================================
# Android logcat helper (works even if android libs are missing)
# =====================================================================
LOG_TAG = "SOSDEPLOYER"

def _alog(msg):
    try:
        from jnius import autoclass
        autoclass('android.util.Log').i(LOG_TAG, str(msg))
    except Exception:
        print("[{}] {}".format(LOG_TAG, msg))

def _alog_err(msg):
    try:
        from jnius import autoclass
        autoclass('android.util.Log').e(LOG_TAG, str(msg))
    except Exception:
        print("[{}][ERR] {}".format(LOG_TAG, msg))


# =====================================================================
# DIAGNOSTIC — log the real runtime state before we touch anything
# that depends on it. Remove this block once the mystery is solved.
# =====================================================================
try:
    import sys
    _alog("DIAG sys.flags.optimize = {}".format(sys.flags.optimize))
    _alog("DIAG PYTHONOPTIMIZE env = {}".format(os.environ.get("PYTHONOPTIMIZE")))
    _relevant_env = {k: v for k, v in os.environ.items() if "PYTHON" in k or "P4A" in k or "ANDROID" in k}
    for _k, _v in sorted(_relevant_env.items()):
        _alog("DIAG env {} = {}".format(_k, _v))
except Exception:
    _alog_err("DIAG block itself failed:\n" + traceback.format_exc())


# =====================================================================
# Heavy imports — wrapped so a failure shows on screen instead of
# killing the process before Kivy starts.
# =====================================================================
_IMPORT_ERROR = None
_IMPORT_OK = False

try:
    import requests
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    from eth_abi import encode as abi_encode
    from eth_utils import keccak
    _IMPORT_OK = True
    _alog("Heavy imports OK (requests, eth_account, eth_abi, eth_utils)")
except Exception:
    _IMPORT_ERROR = traceback.format_exc()
    _alog_err("HEAVY IMPORT FAILED:\n" + _IMPORT_ERROR)


# =====================================================================
# Constants (only computed if imports succeeded; otherwise placeholders)
# =====================================================================
CONTRACT_BYTECODE = "0x608060405234801561001057600080fd5b506040516100..."  # <-- REPLACE

LEDGER_ADDR = "0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A"
DOMAIN_NAME = "69069"
DOMAIN_VERSION = "1"
C_SOS_RESERVE = 10
CONSTRUCTOR_TYPES = ["uint256", "address"]

if _IMPORT_OK:
    EIP712_DOMAIN_TYPEHASH = keccak(text=(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    ))
    RECORD_TYPEHASH = keccak(text=(
        "Record(address signer,address intendedTo,bytes32 payloadHash,bytes32 metadataHash)"
    ))
else:
    EIP712_DOMAIN_TYPEHASH = b""
    RECORD_TYPEHASH = b""

EXPLORER_HOSTS = {
    1: "etherscan.io", 5: "goerli.etherscan.io",
    11155111: "sepolia.etherscan.io", 17000: "holesky.etherscan.io",
    137: "polygonscan.com", 80001: "mumbai.polygonscan.com",
    10: "optimistic.etherscan.io", 42161: "arbiscan.io", 8453: "basescan.org",
}


# =====================================================================
# Platform / explorer
# =====================================================================
def open_url(url: str):
    try:
        from jnius import autoclass  # type: ignore
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        PythonActivity.mActivity.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(url))
        )
    except Exception:
        try:
            webbrowser.open(url)
        except Exception:
            pass


def explorer_url(chain_id, address, code_tab=False):
    host = EXPLORER_HOSTS.get(int(chain_id), "etherscan.io")
    return f"https://{host}/address/{address}{'#code' if code_tab else ''}"


# =====================================================================
# JSON-RPC
# =====================================================================
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


def selector(sig: str) -> str:
    return "0x" + keccak(text=sig)[:4].hex()


def eth_call(rpc_url, to, data):
    return rpc(rpc_url, "eth_call", [{"to": to, "data": data}, "latest"])


def decode_uint(h):
    return 0 if not h or h == "0x" else int(h, 16)


def decode_int(h):
    if not h or h == "0x":
        return 0
    n = int(h, 16)
    if n >= 2**255:
        n -= 2**256
    return n


def decode_bool(h):
    return int(h, 16) != 0 if h and h != "0x" else False


def decode_bytes32(h):
    return h if h.startswith("0x") else "0x" + h


def decode_string(h):
    b = bytes.fromhex(h[2:] if h.startswith("0x") else h)
    off = int.from_bytes(b[0:32], "big")
    ln = int.from_bytes(b[off:off + 32], "big")
    return b[off + 32:off + 32 + ln].decode("utf-8", errors="replace")


def read_uint(rpc_url, contract, sig, address_arg=None):
    data = selector(sig)
    if address_arg:
        data += abi_encode(["address"], [address_arg]).hex()
    return decode_uint(eth_call(rpc_url, contract, data))


def read_int(rpc_url, contract, sig, address_arg=None):
    data = selector(sig)
    if address_arg:
        data += abi_encode(["address"], [address_arg]).hex()
    return decode_int(eth_call(rpc_url, contract, data))


def read_bool(rpc_url, contract, sig, bytes32_arg):
    data = selector(sig) + abi_encode(["bytes32"], [bytes32_arg]).hex()
    return decode_bool(eth_call(rpc_url, contract, data))


def read_string(rpc_url, contract, sig):
    return decode_string(eth_call(rpc_url, contract, selector(sig)))


def wait_for_receipt(rpc_url, tx_hash, timeout_s=360):
    for _ in range(timeout_s // 2):
        r = rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if r:
            if r.get("status") != "0x1":
                raise RuntimeError(f"Tx reverted: {tx_hash}")
            return r
        time.sleep(2)
    raise TimeoutError(f"No receipt after {timeout_s}s. Tx: {tx_hash}")


# =====================================================================
# EIP-712 hashing
# =====================================================================
def compute_metadata(amount: int) -> str:
    return f"cSOS:MINT:{amount}"


def compute_struct_hash(signer, intended_to, payload_hash, metadata):
    if payload_hash.startswith("0x"):
        ph = bytes.fromhex(payload_hash[2:])
    else:
        ph = bytes.fromhex(payload_hash)
    metadata_hash = keccak(text=metadata)
    encoded = abi_encode(
        ["bytes32", "address", "address", "bytes32", "bytes32"],
        [RECORD_TYPEHASH, signer, intended_to, ph, metadata_hash],
    )
    return "0x" + keccak(encoded).hex()


def compute_domain_separator(chain_id: int, verifying_contract: str) -> str:
    encoded = abi_encode(
        ["bytes32", "bytes32", "bytes32", "uint256", "address"],
        [EIP712_DOMAIN_TYPEHASH, keccak(text=DOMAIN_NAME),
         keccak(text=DOMAIN_VERSION), int(chain_id), verifying_contract],
    )
    return "0x" + keccak(encoded).hex()


def sign_record(private_key, chain_id, ledger_addr,
                signer, intended_to, payload_hash, metadata) -> str:
    if not payload_hash.startswith("0x"):
        payload_hash = "0x" + payload_hash
    metadata_hash = "0x" + keccak(text=metadata).hex()
    full_message = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Record": [
                {"name": "signer", "type": "address"},
                {"name": "intendedTo", "type": "address"},
                {"name": "payloadHash", "type": "bytes32"},
                {"name": "metadataHash", "type": "bytes32"},
            ],
        },
        "primaryType": "Record",
        "domain": {
            "name": DOMAIN_NAME, "version": DOMAIN_VERSION,
            "chainId": int(chain_id), "verifyingContract": ledger_addr,
        },
        "message": {
            "signer": signer, "intendedTo": intended_to,
            "payloadHash": payload_hash, "metadataHash": metadata_hash,
        },
    }
    signed = Account.sign_message(
        encode_typed_data(full_message=full_message), private_key=private_key)
    sig = signed.signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


# =====================================================================
# Chain helpers
# =====================================================================
def check_ledger_present(rpc_url):
    code = rpc(rpc_url, "eth_getCode", [LEDGER_ADDR, "latest"])
    if not code or code == "0x":
        raise RuntimeError(
            f"LEDGER {LEDGER_ADDR} has NO code on this chain.\n"
            f"Minting would revert on every call. Aborting."
        )
    return len(code) // 2 - 1


def verify_struct_hash(rpc_url, user, payload, metadata) -> str:
    call_data = selector("recordStructHash(address,address,bytes32,string)") + abi_encode(
        ["address", "address", "bytes32", "string"],
        [user, user, bytes.fromhex(payload[2:]), metadata],
    ).hex()
    return decode_bytes32(eth_call(rpc_url, LEDGER_ADDR, call_data))


def fetch_mint_status(rpc_url, csos_addr, user):
    eff = read_int(rpc_url, LEDGER_ADDR, "effectiveOf(address)", user)
    minted = read_uint(rpc_url, csos_addr, "minted(address)", user)
    mintable = read_uint(rpc_url, csos_addr, "mintable(address)", user)
    cap = max(0, eff - C_SOS_RESERVE)
    return {
        "effectiveOf": eff,
        "reserve": C_SOS_RESERVE,
        "cap": cap,
        "minted": minted,
        "mintable": mintable,
    }


# =====================================================================
# Deploy + mint tx
# =====================================================================
def deploy_contract(rpc_url, chain_id, private_key, mint_fee, treasury):
    acct = Account.from_key(private_key)
    bytecode = CONTRACT_BYTECODE
    if not bytecode.startswith("0x"):
        bytecode = "0x" + bytecode
    if len(bytecode) < 100:
        raise ValueError("CONTRACT_BYTECODE is empty — paste it at the top of main.py")

    data = bytecode + abi_encode(CONSTRUCTOR_TYPES, [int(mint_fee), treasury]).hex()
    nonce = int(rpc(rpc_url, "eth_getTransactionCount", [acct.address, "pending"]), 16)
    gas_price = int(rpc(rpc_url, "eth_gasPrice", []), 16)
    est = rpc(rpc_url, "eth_estimateGas",
              [{"from": acct.address, "data": data, "value": "0x0"}])
    tx = {
        "nonce": nonce, "gasPrice": gas_price,
        "gas": int(int(est, 16) * 1.25),
        "to": None, "value": 0, "data": data, "chainId": int(chain_id),
    }
    signed = acct.sign_transaction(tx)
    raw = signed.raw_transaction.hex()
    raw = raw if raw.startswith("0x") else "0x" + raw
    tx_hash = rpc(rpc_url, "eth_sendRawTransaction", [raw])
    receipt = wait_for_receipt(rpc_url, tx_hash)
    return receipt["contractAddress"], tx_hash


def submit_mint(rpc_url, chain_id, private_key, csos_addr, amount,
                payload_hash, signature, mint_fee, use_max=False):
    acct = Account.from_key(private_key)
    nonce = int(rpc(rpc_url, "eth_getTransactionCount", [acct.address, "pending"]), 16)
    gas_price = int(rpc(rpc_url, "eth_gasPrice", []), 16)

    if use_max:
        sig_name = "mintMax(bytes32,bytes)"
        encoded = abi_encode(
            ["bytes32", "bytes"],
            [bytes.fromhex(payload_hash[2:]), bytes.fromhex(signature[2:])])
    else:
        sig_name = "mint(uint256,bytes32,bytes)"
        encoded = abi_encode(
            ["uint256", "bytes32", "bytes"],
            [int(amount), bytes.fromhex(payload_hash[2:]),
             bytes.fromhex(signature[2:])])

    data = selector(sig_name) + encoded.hex()
    value = int(amount) * int(mint_fee)
    est = rpc(rpc_url, "eth_estimateGas", [{
        "from": acct.address, "to": csos_addr,
        "value": hex(value), "data": data}])
    gas_limit = int(int(est, 16) * 1.25)
    tx = {
        "nonce": nonce, "gasPrice": gas_price, "gas": gas_limit,
        "to": csos_addr, "value": value, "data": data, "chainId": int(chain_id),
    }
    signed = acct.sign_transaction(tx)
    raw = signed.raw_transaction.hex()
    raw = raw if raw.startswith("0x") else "0x" + raw
    tx_hash = rpc(rpc_url, "eth_sendRawTransaction", [raw])
    wait_for_receipt(rpc_url, tx_hash)
    return tx_hash


# =====================================================================
# UI helpers
# =====================================================================
def make_input(hint, password=False, numeric=False, height=0.055, text=""):
    return TextInput(
        hint_text=hint, password=password, multiline=False,
        input_filter="int" if numeric else None,
        size_hint_y=height, text=text,
    )


def make_log_area(initial=""):
    sv = ScrollView()
    lbl = Label(text=initial, size_hint_y=None, halign="left", valign="top")
    lbl.bind(width=lambda *_: setattr(lbl, "text_size", (lbl.width, None)))
    lbl.bind(texture_size=lambda *_: setattr(lbl, "height", lbl.texture_size[1]))
    sv.add_widget(lbl)
    return sv, lbl


def log_to(label):
    def _log(msg):
        Clock.schedule_once(lambda *_: setattr(label, "text", label.text + msg + "\n"))
    return _log


# =====================================================================
# Deploy tab
# =====================================================================
class DeployTab(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=12, spacing=6, **kw)

        self.pk       = make_input("Private key (0x...)", password=True)
        self.rpc_url  = make_input("RPC URL (e.g. https://sepolia.infura.io/v3/KEY)")
        self.chain_id = make_input("Chain ID (1=mainnet, 11155111=Sepolia)", numeric=True)
        self.mint_fee = make_input("MINT_FEE in wei (recommend 0)", numeric=True)
        self.treasury = make_input("TREASURY address (0x...)")
        for w in (self.pk, self.rpc_url, self.chain_id, self.mint_fee, self.treasury):
            self.add_widget(w)

        self.chain_id.text = "11155111"
        self.mint_fee.text = "0"

        row = BoxLayout(size_hint_y=0.075, spacing=6)
        self.deploy_btn = Button(text="Deploy Contract")
        self.check_ledger_btn = Button(
            text="Check LEDGER", background_color=(0.5, 0.5, 0.5, 1))
        self.deploy_btn.bind(on_press=self.on_deploy)
        self.check_ledger_btn.bind(on_press=self.on_check_ledger)
        row.add_widget(self.deploy_btn)
        row.add_widget(self.check_ledger_btn)
        self.add_widget(row)

        self.etherscan_btn = Button(
            text="Open on Etherscan (verify source)", size_hint_y=0.075,
            background_color=(0.2, 0.6, 1.0, 1), disabled=True)
        self.etherscan_btn.bind(on_press=self._on_etherscan)
        self.add_widget(self.etherscan_btn)

        self.mint_tab_btn = Button(
            text="→ Go to Mint tab (prefilled)", size_hint_y=0.075,
            background_color=(0.2, 0.8, 0.4, 1), disabled=True)
        self.mint_tab_btn.bind(on_press=self._on_goto_mint)
        self.add_widget(self.mint_tab_btn)

        sv, self.log = make_log_area("Ready. Test on Sepolia first!\n")
        self.add_widget(sv)
        self._log = log_to(self.log)
        self._last_addr = None
        self._last_chain = None

    def _on_etherscan(self, *_):
        if self._last_addr:
            open_url(explorer_url(self._last_chain, self._last_addr, code_tab=True))

    def _on_goto_mint(self, *_):
        app = App.get_running_app()
        if hasattr(app, "mint_tab"):
            app.mint_tab.prefill_from_deploy(
                rpc_url=self.rpc_url.text.strip(),
                chain_id=self.chain_id.text.strip(),
                private_key=self.pk.text.strip(),
                contract=self._last_addr,
                mint_fee=self.mint_fee.text.strip() or "0")
            app.switch_to_tab(app.mint_tab)

    def on_check_ledger(self, *_):
        rpc_url = self.rpc_url.text.strip()
        if not rpc_url:
            self._log("❌ RPC URL required.")
            return
        self._log(f"→ Checking LEDGER at {LEDGER_ADDR} …")
        threading.Thread(target=self._check_worker, args=(rpc_url,), daemon=True).start()

    def _check_worker(self, rpc_url):
        try:
            size = check_ledger_present(rpc_url)
            self._log(f"✅ LEDGER present ({size} bytes of code)")
            on_chain_ds = decode_bytes32(eth_call(
                rpc_url, LEDGER_ADDR, selector("domainSeparator()")))
            chain_id = int(rpc(rpc_url, "eth_chainId", []), 16)
            local_ds = compute_domain_separator(chain_id, LEDGER_ADDR)
            if on_chain_ds.lower() == local_ds.lower():
                self._log("✅ Domain separator matches locally computed value")
            else:
                self._log("⚠️  Domain separator mismatch!")
                self._log(f"    on-chain: {on_chain_ds}")
                self._log(f"    local:    {local_ds}")
        except Exception as e:
            self._log(f"❌ {e}")

    def on_deploy(self, *_):
        pk, rpc_url = self.pk.text.strip(), self.rpc_url.text.strip()
        chain_id = self.chain_id.text.strip()
        mint_fee = self.mint_fee.text.strip() or "0"
        treasury = self.treasury.text.strip()
        if not all([pk, rpc_url, chain_id, treasury]):
            self._log("❌ Fill in all fields.")
            return
        if chain_id == "1":
            self._log("⚠️  MAINNET — make sure you tested on Sepolia first.")

        self.deploy_btn.disabled = True
        self.etherscan_btn.disabled = True
        self.mint_tab_btn.disabled = True
        self._log(f"→ Deploying to chain {chain_id} …")
        threading.Thread(
            target=self._worker,
            args=(rpc_url, chain_id, pk, mint_fee, treasury),
            daemon=True).start()

    def _worker(self, rpc_url, chain_id, pk, mint_fee, treasury):
        try:
            try:
                check_ledger_present(rpc_url)
                self._log("✅ LEDGER present on chain")
            except Exception as e:
                self._log(f"❌ Pre-flight failed: {e}")
                return

            addr, h = deploy_contract(rpc_url, chain_id, pk, mint_fee, treasury)
            self._log(f"✅ Contract deployed: {addr}")
            self._log(f"   Tx: {h}")
            self._last_addr = addr
            self._last_chain = chain_id

            app = App.get_running_app()
            app.last_deployed = addr
            app.last_chain = chain_id
            app.last_rpc = rpc_url

            try:
                got_t = "0x" + eth_call(rpc_url, addr, selector("TREASURY()"))[-40:]
                got_f = decode_uint(eth_call(rpc_url, addr, selector("MINT_FEE()")))
                self._log(f"   TREASURY = {got_t}")
                self._log(f"   MINT_FEE = {got_f}")
                if got_t.lower() != treasury.lower():
                    self._log("   ⚠️  TREASURY mismatch!")
                if got_f != int(mint_fee):
                    self._log("   ⚠️  MINT_FEE mismatch!")
            except Exception as e:
                self._log(f"   (read-back failed: {e})")

            Clock.schedule_once(lambda *_: setattr(self.etherscan_btn, "disabled", False))
            Clock.schedule_once(lambda *_: setattr(self.mint_tab_btn, "disabled", False))
            self._log("→ Verify on Etherscan, or tap the green button to mint.")
        except Exception as e:
            self._log(f"❌ Deployment failed:\n{e}")
        finally:
            Clock.schedule_once(lambda *_: setattr(self.deploy_btn, "disabled", False))


# =====================================================================
# Mint tab
# =====================================================================
class MintTab(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=10, spacing=5, **kw)

        self.rpc_url  = make_input("RPC URL")
        self.chain_id = make_input("Chain ID", numeric=True)
        self.pk       = make_input("Private key (signer = minter)", password=True)
        self.contract = make_input("cSOS contract address (0x...)")
        self.amount   = make_input("Amount (blank = use MintMax Preview result)")
        self.payload  = make_input("payloadHash (blank = random / reuse preview)")
        self.batch_n  = make_input("Batch count for Batch Check (default 3)", numeric=True)

        for w in (self.rpc_url, self.chain_id, self.pk,
                  self.contract, self.amount, self.payload, self.batch_n):
            self.add_widget(w)

        r1 = BoxLayout(size_hint_y=0.075, spacing=6)
        b_prev      = Button(text="Preview", background_color=(0.4, 0.4, 0.7, 1))
        b_max_prev  = Button(text="MintMax Preview", background_color=(0.4, 0.5, 0.8, 1))
        b_prev.bind(on_press=lambda *_: self._start("preview"))
        b_max_prev.bind(on_press=lambda *_: self._start("mintmax_preview"))
        r1.add_widget(b_prev); r1.add_widget(b_max_prev)
        self.add_widget(r1)

        r2 = BoxLayout(size_hint_y=0.075, spacing=6)
        b_mint = Button(text="Sign & Mint")
        b_max  = Button(text="Sign & MintMax", background_color=(0.2, 0.7, 0.3, 1))
        b_mint.bind(on_press=lambda *_: self._start("mint"))
        b_max .bind(on_press=lambda *_: self._start("mintmax"))
        r2.add_widget(b_mint); r2.add_widget(b_max)
        self.add_widget(r2)

        r3 = BoxLayout(size_hint_y=0.075, spacing=6)
        b_batch = Button(text="Batch Check", background_color=(0.5, 0.4, 0.7, 1))
        b_batch.bind(on_press=lambda *_: self._start("batch_check"))
        r3.add_widget(b_batch)
        self.add_widget(r3)

        sv, self.log = make_log_area(
            "Preview first — it verifies the LEDGER accepts your signature.\n")
        self.add_widget(sv)
        self._log = log_to(self.log)

        self._mint_fee = 0
        self._last_payload = None

    def prefill_from_deploy(self, rpc_url, chain_id, private_key, contract, mint_fee):
        self.rpc_url.text  = rpc_url
        self.chain_id.text = chain_id
        self.pk.text       = private_key
        self.contract.text = contract
        self._mint_fee     = int(mint_fee)
        self.batch_n.text  = self.batch_n.text or "3"
        self._log(f"→ Prefilled for {contract} (MINT_FEE={mint_fee} wei)")

    def _start(self, mode):
        rpc_url  = self.rpc_url.text.strip()
        chain_id = self.chain_id.text.strip()
        pk       = self.pk.text.strip()
        csos     = self.contract.text.strip()
        amt_txt  = self.amount.text.strip()
        payload  = self.payload.text.strip()
        batch_n  = self.batch_n.text.strip() or "3"

        if not all([rpc_url, chain_id, pk, csos]):
            self._log("❌ Fill RPC, chain ID, private key, and contract address.")
            return

        if mode == "batch_check":
            try:
                n = int(batch_n)
            except ValueError:
                self._log("❌ Batch count must be an integer.")
                return
            if n < 1 or n > 20:
                self._log("❌ Batch count must be between 1 and 20.")
                return
            threading.Thread(
                target=self._batch_worker,
                args=(rpc_url, pk, csos, n),
                daemon=True).start()
            return

        if not amt_txt:
            self._log("→ Querying mintable(user) …")
            try:
                acct = Account.from_key(pk)
                amt = read_uint(rpc_url, csos, "mintable(address)", acct.address)
                if amt == 0:
                    self._log("❌ mintable(user) == 0 — nothing to mint.")
                    return
                self.amount.text = str(amt)
                amt_txt = str(amt)
                self._log(f"   mintable = {amt}")
            except Exception as e:
                self._log(f"❌ mintable query failed: {e}")
                return

        threading.Thread(
            target=self._worker,
            args=(rpc_url, chain_id, pk, csos, int(amt_txt), mode, payload),
            daemon=True).start()

    def _worker(self, rpc_url, chain_id, pk, csos, amount, mode, payload_input):
        try:
            acct = Account.from_key(pk)
            user = acct.address
            metadata = compute_metadata(amount)
            is_max_preview = (mode == "mintmax_preview")

            if is_max_preview:
                self._log("─── MintMax Preview ───")
                try:
                    s = fetch_mint_status(rpc_url, csos, user)
                    self._log(f"   effectiveOf(user) = {s['effectiveOf']}")
                    self._log(f"   RESERVE           = {s['reserve']}")
                    self._log(f"   cap               = {s['cap']}")
                    self._log(f"   minted(user)      = {s['minted']}")
                    self._log(f"   mintable(user)    = {s['mintable']}")
                    if s["mintable"] == 0:
                        self._log("   ⚠️  mintable == 0 — mintMax would revert.")
                    else:
                        self._log(f"   → Sign & MintMax would mint {s['mintable']} cSOS")
                        amount = s["mintable"]
                        metadata = compute_metadata(amount)
                except Exception as e:
                    self._log(f"   ⚠️  mint-status lookup failed: {e}")
                self._log("─── Struct hash preview ───")

            if payload_input:
                payload = payload_input if payload_input.startswith("0x") else "0x" + payload_input
                if len(payload) != 66:
                    raise ValueError("payloadHash must be 32 bytes (66 chars with 0x)")
            elif self._last_payload:
                payload = self._last_payload
                self._log("   (reusing payloadHash from last preview)")
            else:
                payload = "0x" + os.urandom(32).hex()

            self._log(f"→ amount   = {amount}")
            self._log(f"   metadata = {metadata}")
            self._log(f"   payload  = {payload}")

            local_sh = compute_struct_hash(user, user, payload, metadata)
            self._log(f"   local structHash    = {local_sh}")

            try:
                on_chain_sh = verify_struct_hash(rpc_url, user, payload, metadata)
                self._log(f"   on-chain structHash = {on_chain_sh}")
                if local_sh.lower() != on_chain_sh.lower():
                    self._log("❌ STRUCT HASH MISMATCH — signing would fail!")
                    return
                self._log("   ✅ hashes match")
            except Exception as e:
                self._log(f"   ⚠️  on-chain structHash call failed: {e}")

            try:
                used_ledger = read_bool(rpc_url, LEDGER_ADDR,
                                        "isRecordHashUsed(bytes32)", local_sh)
                self._log(f"   LEDGER.isRecordHashUsed = {used_ledger}")
                if used_ledger:
                    self._log("❌ This exact record already exists on LEDGER.")
                    return
            except Exception as e:
                self._log(f"   ⚠️  isRecordHashUsed check failed: {e}")

            try:
                used_csos = read_bool(rpc_url, csos,
                                      "usedMintHash(bytes32)", local_sh)
                self._log(f"   cSOS.usedMintHash       = {used_csos}")
                if used_csos:
                    self._log("❌ This mint hash is already used on cSOS.")
                    return
            except Exception as e:
                self._log(f"   ⚠️  usedMintHash check failed: {e}")

            if mode in ("preview", "mintmax_preview"):
                self._log("✅ Preview OK — tap Sign & Mint to submit.")
                self._last_payload = payload
                Clock.schedule_once(lambda *_: setattr(self.payload, "text", payload))
                return

            self._log("→ Signing EIP-712 Record …")
            signature = sign_record(pk, chain_id, LEDGER_ADDR,
                                    user, user, payload, metadata)
            self._log(f"   signature = {signature[:20]}…")

            use_max = (mode == "mintmax")
            self._log(f"→ Submitting {'mintMax' if use_max else 'mint'} …")
            tx_hash = submit_mint(rpc_url, chain_id, pk, csos, amount,
                                  payload, signature, self._mint_fee, use_max=use_max)
            self._log(f"✅ Minted {amount} cSOS")
            self._log(f"   Tx: {tx_hash}")
            self._log(f"   {explorer_url(chain_id, csos)}")

            self._last_payload = None
            Clock.schedule_once(lambda *_: setattr(self.payload, "text", ""))

            try:
                new_bal = read_uint(rpc_url, csos, "balanceOf(address)", user)
                self._log(f"   balanceOf(user) = {new_bal}")
            except Exception:
                pass
        except Exception as e:
            self._log(f"❌ Failed:\n{e}")

    def _batch_worker(self, rpc_url, pk, csos, n):
        try:
            acct = Account.from_key(pk)
            user = acct.address
            self._log(f"─── Batch Check ───")
            self._log(f"   signer: {user}")
            self._log(f"   items:  {n}")

            amt_txt = self.amount.text.strip()
            if not amt_txt:
                try:
                    amt = read_uint(rpc_url, csos, "mintable(address)", user)
                    if amt == 0:
                        self._log("❌ mintable(user) == 0 — nothing to preview.")
                        return
                    amt_txt = str(amt)
                    Clock.schedule_once(lambda *_: setattr(self.amount, "text", amt_txt))
                    self._log(f"   mintable = {amt}")
                except Exception as e:
                    self._log(f"❌ mintable query failed: {e}")
                    return
            amount = int(amt_txt)
            metadata = compute_metadata(amount)
            self._log(f"   amount = {amount}, metadata = {metadata}")
            self._log(f"   generating {n} fresh payloadHashes …")

            fresh = []
            used = []
            for i in range(n):
                payload = "0x" + os.urandom(32).hex()
                local_sh = compute_struct_hash(user, user, payload, metadata)
                try:
                    used_flag = read_bool(
                        rpc_url, LEDGER_ADDR,
                        "isRecordHashUsed(bytes32)", local_sh)
                except Exception as e:
                    self._log(f"   [{i+1}] ⚠️  lookup failed: {e}")
                    continue

                marker = "❌ used" if used_flag else "✅ fresh"
                self._log(f"   [{i+1}] {marker}  payload={payload[:12]}…  hash={local_sh[:12]}…")
                (used if used_flag else fresh).append((payload, local_sh))

            self._log("───────────────────")
            self._log(f"   fresh: {len(fresh)}  used: {len(used)}  total: {n}")
            if fresh:
                self._log("   Fresh payload hashes (safe to mint):")
                for p, h in fresh:
                    self._log(f"     payload = {p}")
                    self._log(f"     hash    = {h}")
                self._last_payload = fresh[0][0]
                Clock.schedule_once(
                    lambda *_: setattr(self.payload, "text", fresh[0][0]))
                self._log("   → First fresh payload staged in the payloadHash field.")
                self._log("     (Each additional mint needs its own payload — "
                          "tap Batch Check again to roll a new set.)")
        except Exception as e:
            self._log(f"❌ Batch Check failed:\n{e}")


# =====================================================================
# Query tab
# =====================================================================
class QueryTab(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=12, spacing=6, **kw)

        self.rpc_url  = make_input("RPC URL")
        self.contract = make_input("cSOS contract address (0x...)")
        self.user     = make_input("User address for mintable/balanceOf (0x...)")
        for w in (self.rpc_url, self.contract, self.user):
            self.add_widget(w)

        r1 = BoxLayout(size_hint_y=0.075, spacing=6)
        r2 = BoxLayout(size_hint_y=0.075, spacing=6)
        r3 = BoxLayout(size_hint_y=0.075, spacing=6)

        entries = [
            ("mintable(user)", "mintable(address)", True,  r1),
            ("balanceOf(user)", "balanceOf(address)", True, r1),
            ("minted(user)",   "minted(address)",   True,  r2),
            ("totalSupply()",  "totalSupply()",     False, r2),
            ("name()",         "name()",            False, r3),
            ("symbol()",       "symbol()",          False, r3),
        ]
        for label, sig, needs_addr, row in entries:
            b = Button(text=label)
            b.bind(on_press=lambda _b, s=sig, n=needs_addr: self._call(s, n))
            row.add_widget(b)
        self.add_widget(r1); self.add_widget(r2); self.add_widget(r3)

        b_prefill = Button(text="Use last deployed cSOS", size_hint_y=0.07)
        b_prefill.bind(on_press=self._prefill)
        self.add_widget(b_prefill)

        b_open = Button(text="Open contract on explorer",
                        size_hint_y=0.07,
                        background_color=(0.2, 0.6, 1.0, 1))
        b_open.bind(on_press=self._open)
        self.add_widget(b_open)

        sv, self.log = make_log_area("Paste a cSOS address, or tap prefill.\n")
        self.add_widget(sv)
        self._log = log_to(self.log)

    def _prefill(self, *_):
        app = App.get_running_app()
        if getattr(app, "last_deployed", None):
            self.contract.text = app.last_deployed
            self.rpc_url.text = app.last_rpc or self.rpc_url.text
            self._log(f"Prefilled: {app.last_deployed}")
        else:
            self._log("No deployment this session.")

    def _open(self, *_):
        app = App.get_running_app()
        chain = getattr(app, "last_chain", None) or 1
        addr = self.contract.text.strip()
        if addr:
            open_url(explorer_url(chain, addr, code_tab=True))

    def _call(self, sig, needs_addr):
        rpc_url = self.rpc_url.text.strip()
        csos    = self.contract.text.strip()
        user    = self.user.text.strip()
        if not rpc_url or not csos:
            self._log("❌ RPC + contract required.")
            return
        if needs_addr and not user:
            self._log(f"❌ {sig} needs a user address.")
            return
        self._log(f"→ {sig} …")
        threading.Thread(target=self._worker,
                         args=(rpc_url, csos, sig, needs_addr, user),
                         daemon=True).start()

    def _worker(self, rpc_url, csos, sig, needs_addr, user):
        try:
            if sig in ("name()", "symbol()"):
                result = read_string(rpc_url, csos, sig)
            else:
                result = read_uint(rpc_url, csos, sig, user if needs_addr else None)
            self._log(f"✅ {sig} = {result}")
        except Exception as e:
            self._log(f"❌ {sig} failed: {e}")


# =====================================================================
# Root
# =====================================================================
class Root(TabbedPanel):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.do_default_tab = False
        self.tab_width = 120

        d = TabbedPanelItem(text="Deploy"); d.add_widget(DeployTab()); self.add_widget(d)
        m = TabbedPanelItem(text="Mint");   m.add_widget(MintTab());   self.add_widget(m)
        q = TabbedPanelItem(text="Query");  q.add_widget(QueryTab());  self.add_widget(q)

        self.default_tab = d


# =====================================================================
# Error screen shown only when heavy imports fail
# =====================================================================
class ImportErrorScreen(BoxLayout):
    def __init__(self, err_text, **kw):
        super().__init__(orientation="vertical", padding=12, spacing=8, **kw)
        self.add_widget(Label(
            text="Startup failed — missing or broken import",
            size_hint_y=None, height=48, bold=True,
            color=(1, 0.3, 0.3, 1),
        ))
        sv = ScrollView()
        lbl = Label(text=err_text, size_hint_y=None, halign="left", valign="top",
                    color=(1, 1, 1, 1))
        lbl.bind(width=lambda *_: setattr(lbl, "text_size", (lbl.width, None)))
        lbl.bind(texture_size=lambda *_: setattr(lbl, "height", lbl.texture_size[1]))
        sv.add_widget(lbl)
        self.add_widget(sv)


# =====================================================================
# App
# =====================================================================
class DeployerApp(App):
    last_deployed = None
    last_chain = None
    last_rpc = None

    def build(self):
        _alog("DeployerApp.build() called")
        if not _IMPORT_OK:
            _alog_err("Returning error screen due to import failure")
            return ImportErrorScreen(_IMPORT_ERROR or "Unknown import error")

        root = Root()
        for tab in root.tab_list:
            if tab.text == "Mint":
                self.mint_tab = tab.content
                break
        self.root_widget = root
        _alog("UI built OK")
        return root

    def switch_to_tab(self, content_widget):
        for tab in self.root_widget.tab_list:
            if tab.content is content_widget:
                self.root_widget.switch_to(tab)
                return


if __name__ == "__main__":
    try:
        _alog("Entering DeployerApp().run()")
        DeployerApp().run()
        _alog("App.run() returned cleanly")
    except Exception:
        _alog_err("TOP-LEVEL CRASH:\n" + traceback.format_exc())
        raise
