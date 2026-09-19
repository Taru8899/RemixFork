import os
import threading
import time
import webbrowser
import traceback
import sys
import types
import functools

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
APP_VERSION = "0.3"

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
# Pure-Python cytoolz stub (complete enough for eth-account 0.10.0)
# Injected into sys.modules BEFORE eth_account is imported
# =====================================================================
def _make_cytoolz_stub():
    mod = types.ModuleType("cytoolz")

    def dissoc(d, *keys):
        return {k: v for k, v in d.items() if k not in keys}

    def assoc(d, key, value):
        result = dict(d)
        result[key] = value
        return result

    def merge(*dicts):
        result = {}
        for d in dicts:
            if d:
                result.update(d)
        return result

    def get_in(keys, coll, default=None):
        for key in keys:
            try:
                coll = coll[key]
            except (KeyError, TypeError, IndexError):
                return default
        return coll

    def curry(func):
        """Minimal curry implementation sufficient for eth-account."""
        @functools.wraps(func)
        def curried(*args, **kwargs):
            try:
                needed = func.__code__.co_argcount
            except Exception:
                needed = 1
            if len(args) + len(kwargs) >= needed:
                return func(*args, **kwargs)
            return functools.partial(curried, *args, **kwargs)
        return curried

    def compose(*funcs):
        def composed(*args, **kwargs):
            for f in reversed(funcs):
                args = (f(*args, **kwargs),)
                kwargs = {}
            return args[0] if args else None
        return composed

    def identity(x):
        return x

    def first(seq):
        return next(iter(seq))

    def second(seq):
        it = iter(seq)
        next(it)
        return next(it)

    def last(seq):
        item = None
        for item in seq:
            pass
        return item

    def take(n, seq):
        return list(seq)[:n]

    def drop(n, seq):
        it = iter(seq)
        for _ in range(n):
            next(it, None)
        return list(it)

    def concat(seqs):
        for seq in seqs:
            for item in seq:
                yield item

    def mapcat(func, seqs):
        return concat(map(func, seqs))

    def pipe(data, *funcs):
        for f in funcs:
            data = f(data)
        return data

    partial = functools.partial

    def keymap(func, d):
        return {func(k): v for k, v in d.items()}

    def valmap(func, d):
        return {k: func(v) for k, v in d.items()}

    def itemmap(func, d):
        return dict(func(k, v) for k, v in d.items())

    def keyfilter(pred, d):
        return {k: v for k, v in d.items() if pred(k)}

    def valfilter(pred, d):
        return {k: v for k, v in d.items() if pred(v)}

    def itemfilter(pred, d):
        return {k: v for k, v in d.items() if pred((k, v))}

    # Expose everything eth-account is likely to need
    for name, obj in list(locals().items()):
        if not name.startswith("_") and name != "mod":
            setattr(mod, name, obj)

    mod.functoolz = mod
    mod.dicttoolz = mod
    mod.itertoolz = mod
    return mod

# Install the stub so "import cytoolz" and "from cytoolz import curry" succeed
_cytoolz = _make_cytoolz_stub()
sys.modules["cytoolz"] = _cytoolz
sys.modules["cytoolz.dicttoolz"] = _cytoolz
sys.modules["cytoolz.functoolz"] = _cytoolz
sys.modules["cytoolz.itertoolz"] = _cytoolz


# =====================================================================
# Fix CFFI / pycryptodome crash on Android (PYTHONOPTIMIZE=2)
# Must run BEFORE any Crypto / eth_account / eth_keyfile import
# =====================================================================
import ctypes
try:
    ctypes.pythonapi = ctypes.PyDLL("libpython%d.%d.so" % sys.version_info[:2])
except Exception:
    pass


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
CONTRACT_BYTECODE = "0x6080604052600436106101fb575f3560e01c8063739e2e091161010c578063a457c2d71161009f578063d113b95c1161006e578063d113b95c146107f5578063d7bf81a31461080b578063dd62ed3e14610835578063fed3fdcb14610871578063fed976f71461089b57610232565b8063a457c2d71461073d578063a6cd4c6914610779578063a9059cbb146107a3578063cfc98a24146107df57610232565b806395d89b41116100db57806395d89b41146106a35780639ab475b5146106cd5780639d2cc436146106e95780639fbaf3de1461071357610232565b8063739e2e09146105d757806377b5255614610601578063862e2fc81461063d57806392a49e211461066757610232565b8063313ce5671161018f5780634b6604191161015e5780634b660419146104c857806359441eae146104f257806364e4d3a41461052e5780636fab912a1461055e57806370a082311461059b57610232565b8063313ce567146103fc57806339509351146104265780633c3a44da1461046257806342fcfe391461048c57610232565b80631e7269c5116101cb5780631e7269c51461033057806323b872dd1461036c57806324031a05146103a85780632d2c5565146103d257610232565b80625dfcbf1461026457806306fdde03146102a0578063095ea7b3146102ca57806318160ddd1461030657610232565b36610232576040517f60f8f32100000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b6040517f60f8f32100000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b34801561026f575f5ffd5b5061028a60048036038101906102859190612302565b6108c5565b6040516102979190612345565b60405180910390f35b3480156102ab575f5ffd5b506102b46108da565b6040516102c191906123ce565b60405180910390f35b3480156102d5575f5ffd5b506102f060048036038101906102eb9190612418565b610913565b6040516102fd9190612470565b60405180910390f35b348015610311575f5ffd5b5061031a610a00565b6040516103279190612345565b60405180910390f35b34801561033b575f5ffd5b5061035660048036038101906103519190612302565b610a06565b6040516103639190612345565b60405180910390f35b348015610377575f5ffd5b50610392600480360381019061038d9190612489565b610a1b565b60405161039f9190612470565b60405180910390f35b3480156103b3575f5ffd5b506103bc610d75565b6040516103c991906124e8565b60405180910390f35b3480156103dd575f5ffd5b506103e6610d8d565b6040516103f391906124e8565b60405180910390f35b348015610407575f5ffd5b50610410610db1565b60405161041d919061251c565b60405180910390f35b348015610431575f5ffd5b5061044c60048036038101906104479190612418565b610db5565b6040516104599190612470565b60405180910390f35b34801561046d575f5ffd5b50610476610f2a565b6040516104839190612345565b60405180910390f35b348015610497575f5ffd5b506104b260048036038101906104ad9190612535565b610f30565b6040516104bf91906123ce565b60405180910390f35b3480156104d3575f5ffd5b506104dc610f98565b6040516104e991906125bb565b60405180910390f35b3480156104fd575f5ffd5b5061051860048036038101906105139190612302565b610fb0565b6040516105259190612345565b60405180910390f35b61054860048036038101906105439190612668565b6110cb565b6040516105559190612345565b60405180910390f35b348015610569575f5ffd5b50610584600480360381019061057f91906126c5565b61116f565b604051610592929190612724565b60405180910390f35b3480156105a6575f5ffd5b506105c160048036038101906105bc9190612302565b611219565b6040516105ce9190612345565b60405180910390f35b3480156105e2575f5ffd5b506105eb61122e565b6040516105f89190612345565b60405180910390f35b34801561060c575f5ffd5b5061062760048036038101906106229190612752565b611233565b6040516106349190612470565b60405180910390f35b348015610648575f5ffd5b50610651611250565b60405161065e9190612345565b60405180910390f35b348015610672575f5ffd5b5061068d600480360381019061068891906126c5565b611256565b60405161069a919061277d565b60405180910390f35b3480156106ae575f5ffd5b506106b76112fa565b6040516106c491906123ce565b60405180910390f35b6106e760048036038101906106e29190612796565b611333565b005b3480156106f4575f5ffd5b506106fd6113ca565b60405161070a9190612345565b60405180910390f35b34801561071e575f5ffd5b506107276113cf565b6040516107349190612345565b60405180910390f35b348015610748575f5ffd5b50610763600480360381019061075e9190612418565b6113d5565b6040516107709190612470565b60405180910390f35b348015610784575f5ffd5b5061078d611589565b60405161079a91906123ce565b60405180910390f35b3480156107ae575f5ffd5b506107c960048036038101906107c49190612418565b6115c2565b6040516107d69190612470565b60405180910390f35b3480156107ea575f5ffd5b506107f36117b4565b005b348015610800575f5ffd5b50610809611920565b005b348015610816575f5ffd5b5061081f611a96565b60405161082c9190612345565b60405180910390f35b348015610840575f5ffd5b5061085b60048036038101906108569190612807565b611aba565b6040516108689190612345565b60405180910390f35b34801561087c575f5ffd5b50610885611ada565b6040516108929190612345565b60405180910390f35b3480156108a6575f5ffd5b506108af611ae1565b6040516108bc9190612345565b60405180910390f35b6007602052805f5260405f205f915090505481565b6040518060400160405280600d81526020017f534f5336393036392063534f530000000000000000000000000000000000000081525081565b5f8160085f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f8573ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f20819055508273ffffffffffffffffffffffffffffffffffffffff163373ffffffffffffffffffffffffffffffffffffffff167f8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925846040516109ee9190612345565b60405180910390a36001905092915050565b60045481565b6006602052805f5260405f205f915090505481565b5f5f73ffffffffffffffffffffffffffffffffffffffff168373ffffffffffffffffffffffffffffffffffffffff1603610a81576040517fd92e233d00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b8160055f8673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f20541015610af8576040517ff4d678b800000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b5f60085f8673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f2054905082811015610bae576040517f13be252b00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8114610c5e578281610be19190612872565b60085f8773ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f20819055505b8260055f8773ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f828254610caa9190612872565b925050819055508260055f8673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f828254610cfd91906128a5565b925050819055508373ffffffffffffffffffffffffffffffffffffffff168573ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef85604051610d619190612345565b60405180910390a360019150509392505050565b731c10e6574ee696f54b21a611a21313e4714628ad81565b7f0000000000000000000000001c10e6574ee696f54b21a611a21313e4714628ad81565b5f81565b5f5f8260085f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f8673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f2054610e3b91906128a5565b90508060085f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f8673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f20819055508373ffffffffffffffffffffffffffffffffffffffff163373ffffffffffffffffffffffffffffffffffffffff167f8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b92583604051610f179190612345565b60405180910390a3600191505092915050565b60015481565b60606040518060400160405280600a81526020017f63534f533a4d494e543a00000000000000000000000000000000000000000000815250610f7183611af6565b604051602001610f82929190612912565b6040516020818303038152906040529050919050565b737373dbc24dcd785896e8ac3d5372c6ced9b75a8a81565b5f5f737373dbc24dcd785896e8ac3d5372c6ced9b75a8a73ffffffffffffffffffffffffffffffffffffffff166378be73fc846040518263ffffffff1660e01b8152600401610fff91906124e8565b602060405180830381865afa15801561101a573d5f5f3e3d5ffd5b505050506040513d601f19601f8201168201806040525081019061103e9190612968565b9050600a8113611051575f9150506110c6565b5f600a8261105f9190612872565b90505f60065f8673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205490508181106110b4575f93505050506110c6565b80826110c09190612872565b93505050505b919050565b5f6002600a5403611108576040517fab143c0600000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b6002600a8190555061111933610fb0565b90505f8103611154576040517f017f629a00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b61116081858585611c4f565b6001600a819055509392505050565b60605f61117b84610f30565b9150737373dbc24dcd785896e8ac3d5372c6ced9b75a8a73ffffffffffffffffffffffffffffffffffffffff1663cd6f7d9b868786866040518563ffffffff1660e01b81526004016111d09493929190612993565b602060405180830381865afa1580156111eb573d5f5f3e3d5ffd5b505050506040513d601f19601f8201168201806040525081019061120f91906129f1565b9050935093915050565b6005602052805f5260405f205f915090505481565b5f5481565b6009602052805f5260405f205f915054906101000a900460ff1681565b60025481565b5f737373dbc24dcd785896e8ac3d5372c6ced9b75a8a73ffffffffffffffffffffffffffffffffffffffff1663cd6f7d9b85868561129388610f30565b6040518563ffffffff1660e01b81526004016112b29493929190612993565b602060405180830381865afa1580156112cd573d5f5f3e3d5ffd5b505050506040513d601f19601f820116820180604052508101906112f191906129f1565b90509392505050565b6040518060400160405280600481526020017f63534f530000000000000000000000000000000000000000000000000000000081525081565b6002600a540361136f576040517fab143c0600000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b6002600a819055505f84036113b0576040517f017f629a00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b6113bc84848484611c4f565b6001600a8190555050505050565b600a81565b60035481565b5f5f60085f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f8573ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205490508281101561148c576040517f13be252b00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b5f83826114999190612872565b90508060085f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f8773ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f20819055508473ffffffffffffffffffffffffffffffffffffffff163373ffffffffffffffffffffffffffffffffffffffff167f8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925836040516115759190612345565b60405180910390a360019250505092915050565b6040518060400160405280600a81526020017f63534f533a4d494e543a0000000000000000000000000000000000000000000081525081565b5f5f73ffffffffffffffffffffffffffffffffffffffff168373ffffffffffffffffffffffffffffffffffffffff1603611628576040517fd92e233d00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b8160055f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f2054101561169f576040517ff4d678b800000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b8160055f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f8282546116eb9190612872565b925050819055508160055f8573ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f82825461173e91906128a5565b925050819055508273ffffffffffffffffffffffffffffffffffffffff163373ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef846040516117a29190612345565b60405180910390a36001905092915050565b6002600a54036117f0576040517fab143c0600000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b6002600a819055505f60015490505f810361180b5750611916565b5f6001819055505f731c10e6574ee696f54b21a611a21313e4714628ad73ffffffffffffffffffffffffffffffffffffffff168260405161184b90612a49565b5f6040518083038185875af1925050503d805f8114611885576040519150601f19603f3d011682016040523d82523d5f602084013e61188a565b606091505b50509050806118c5576040517fd41997a500000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b3373ffffffffffffffffffffffffffffffffffffffff167fcb2e84b08a7a96bf62a4416748a26a53aeb0f87dd26e2ef25bc46df567411b348360405161190b9190612345565b60405180910390a250505b6001600a81905550565b6002600a540361195c576040517fab143c0600000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b6002600a819055505f5f5490505f81036119765750611a8c565b5f5f819055505f7f0000000000000000000000001c10e6574ee696f54b21a611a21313e4714628ad73ffffffffffffffffffffffffffffffffffffffff16826040516119c190612a49565b5f6040518083038185875af1925050503d805f81146119fb576040519150601f19603f3d011682016040523d82523d5f602084013e611a00565b606091505b5050905080611a3b576040517f0e373cf800000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b3373ffffffffffffffffffffffffffffffffffffffff167fb6c81b526e1bd55a3845d8caa6fe0c1ce87b3c9e534eec43f43b3c1849d4e2e883604051611a819190612345565b60405180910390a250505b6001600a81905550565b7f000000000000000000000000000000000000000000000000000000000000000081565b6008602052815f5260405f20602052805f5260405f205f91509150505481565b6201388081565b5f3a62013880611af19190612a5d565b905090565b60605f8203611b3c576040518060400160405280600181526020017f30000000000000000000000000000000000000000000000000000000000000008152509050611c4a565b5f8290505f5b5f8214611b6b578080611b5490612a9e565b915050600a82611b649190612b12565b9150611b42565b5f8167ffffffffffffffff811115611b8657611b85612b42565b5b6040519080825280601f01601f191660200182016040528015611bb85781602001600182028036833780820191505090505b5090505b5f8514611c4357600182611bd09190612872565b9150600a85611bdf9190612b6f565b6030611beb91906128a5565b60f81b818381518110611c0157611c00612b9f565b5b60200101907effffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff191690815f1a905350600a85611c3c9190612b12565b9450611bbc565b8093505050505b919050565b5f611c5933610fb0565b905080851115611c95576040517f017f629a00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b5f7f000000000000000000000000000000000000000000000000000000000000000086611cc29190612a5d565b905080341015611cfe576040517f9a0833b600000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b5f8134611d0b9190612872565b90505f611d1788610f30565b90505f737373dbc24dcd785896e8ac3d5372c6ced9b75a8a73ffffffffffffffffffffffffffffffffffffffff1663cd6f7d9b33338b866040518563ffffffff1660e01b8152600401611d6d9493929190612993565b602060405180830381865afa158015611d88573d5f5f3e3d5ffd5b505050506040513d601f19601f82011682018060405250810190611dac91906129f1565b905060095f8281526020019081526020015f205f9054906101000a900460ff1615611e03576040517f8ec9ddad00000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b600160095f8381526020019081526020015f205f6101000a81548160ff0219169083151502179055508860065f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f828254611e7891906128a5565b925050819055508360075f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f828254611ecb91906128a5565b925050819055508360035f828254611ee391906128a5565b92505081905550835f5f828254611efa91906128a5565b925050819055505f831115611f3a578260015f828254611f1a91906128a5565b925050819055508260025f828254611f3291906128a5565b925050819055505b737373dbc24dcd785896e8ac3d5372c6ced9b75a8a73ffffffffffffffffffffffffffffffffffffffff16631c7c27c833338b8b8b886040518763ffffffff1660e01b8152600401611f9196959493929190612c16565b5f604051808303815f87803b158015611fa8575f5ffd5b505af1158015611fba573d5f5f3e3d5ffd5b50505050737373dbc24dcd785896e8ac3d5372c6ced9b75a8a73ffffffffffffffffffffffffffffffffffffffff1663f8e5bb59826040518263ffffffff1660e01b815260040161200b919061277d565b602060405180830381865afa158015612026573d5f5f3e3d5ffd5b505050506040513d601f19601f8201168201806040525081019061204a9190612ca1565b612080576040517f63be7c4900000000000000000000000000000000000000000000000000000000815260040160405180910390fd5b61208a338a6121cc565b3373ffffffffffffffffffffffffffffffffffffffff167f5a3358a3d27a5373c0df2604662088d37894d56b7cfd27f315770440f4e0d9198a8660065f3373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205460405161211193929190612ccc565b60405180910390a2803373ffffffffffffffffffffffffffffffffffffffff167fd01f93a87f0f41307d528a0bce47898b357d3fcc990e88d8a5e4967366044a248b85604051612162929190612d01565b60405180910390a35f8311156121c1573373ffffffffffffffffffffffffffffffffffffffff167f264f630d9efa0d07053a31163641d9fcc0adafc9d9e76f1c37c2ce3a558d2c52846040516121b89190612345565b60405180910390a25b505050505050505050565b8060045f8282546121dd91906128a5565b925050819055508060055f8473ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020015f205f82825461223091906128a5565b925050819055508173ffffffffffffffffffffffffffffffffffffffff165f73ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef836040516122949190612345565b60405180910390a35050565b5f5ffd5b5f5ffd5b5f73ffffffffffffffffffffffffffffffffffffffff82169050919050565b5f6122d1826122a8565b9050919050565b6122e1816122c7565b81146122eb575f5ffd5b50565b5f813590506122fc816122d8565b92915050565b5f60208284031215612317576123166122a0565b5b5f612324848285016122ee565b91505092915050565b5f819050919050565b61233f8161232d565b82525050565b5f6020820190506123585f830184612336565b92915050565b5f81519050919050565b5f82825260208201905092915050565b8281835e5f83830152505050565b5f601f19601f8301169050919050565b5f6123a08261235e565b6123aa8185612368565b93506123ba818560208601612378565b6123c381612386565b840191505092915050565b5f6020820190508181035f8301526123e68184612396565b905092915050565b6123f78161232d565b8114612401575f5ffd5b50565b5f81359050612412816123ee565b92915050565b5f5f6040838503121561242e5761242d6122a0565b5b5f61243b858286016122ee565b925050602061244c85828601612404565b9150509250929050565b5f8115159050919050565b61246a81612456565b82525050565b5f6020820190506124835f830184612461565b92915050565b5f5f5f606084860312156124a05761249f6122a0565b5b5f6124ad868287016122ee565b93505060206124be868287016122ee565b92505060406124cf86828701612404565b9150509250925092565b6124e2816122c7565b82525050565b5f6020820190506124fb5f8301846124d9565b92915050565b5f60ff82169050919050565b61251681612501565b82525050565b5f60208201905061252f5f83018461250d565b92915050565b5f6020828403121561254a576125496122a0565b5b5f61255784828501612404565b91505092915050565b5f819050919050565b5f61258361257e612579846122a8565b612560565b6122a8565b9050919050565b5f61259482612569565b9050919050565b5f6125a58261258a565b9050919050565b6125b58161259b565b82525050565b5f6020820190506125ce5f8301846125ac565b92915050565b5f819050919050565b6125e6816125d4565b81146125f0575f5ffd5b50565b5f81359050612601816125dd565b92915050565b5f5ffd5b5f5ffd5b5f5ffd5b5f5f83601f84011261262857612627612607565b5b8235905067ffffffffffffffff8111156126455761264461260b565b5b6020830191508360018202830111156126615761266061260f565b5b9250929050565b5f5f5f6040848603121561267f5761267e6122a0565b5b5f61268c868287016125f3565b935050602084013567ffffffffffffffff8111156126ad576126ac6122a4565b5b6126b986828701612613565b92509250509250925092565b5f5f5f606084860312156126dc576126db6122a0565b5b5f6126e9868287016122ee565b93505060206126fa86828701612404565b925050604061270b868287016125f3565b9150509250925092565b61271e816125d4565b82525050565b5f6040820190508181035f83015261273c8185612396565b905061274b6020830184612715565b9392505050565b5f60208284031215612767576127666122a0565b5b5f612774848285016125f3565b91505092915050565b5f6020820190506127905f830184612715565b92915050565b5f5f5f5f606085870312156127ae576127ad6122a0565b5b5f6127bb87828801612404565b94505060206127cc878288016125f3565b935050604085013567ffffffffffffffff8111156127ed576127ec6122a4565b5b6127f987828801612613565b925092505092959194509250565b5f5f6040838503121561281d5761281c6122a0565b5b5f61282a858286016122ee565b925050602061283b858286016122ee565b9150509250929050565b7f4e487b71000000000000000000000000000000000000000000000000000000005f52601160045260245ffd5b5f61287c8261232d565b91506128878361232d565b925082820390508181111561289f5761289e612845565b5b92915050565b5f6128af8261232d565b91506128ba8361232d565b92508282019050808211156128d2576128d1612845565b5b92915050565b5f81905092915050565b5f6128ec8261235e565b6128f681856128d8565b9350612906818560208601612378565b80840191505092915050565b5f61291d82856128e2565b915061292982846128e2565b91508190509392505050565b5f819050919050565b61294781612935565b8114612951575f5ffd5b50565b5f815190506129628161293e565b92915050565b5f6020828403121561297d5761297c6122a0565b5b5f61298a84828501612954565b91505092915050565b5f6080820190506129a65f8301876124d9565b6129b360208301866124d9565b6129c06040830185612715565b81810360608301526129d28184612396565b905095945050505050565b5f815190506129eb816125dd565b92915050565b5f60208284031215612a0657612a056122a0565b5b5f612a13848285016129dd565b91505092915050565b5f81905092915050565b50565b5f612a345f83612a1c565b9150612a3f82612a26565b5f82019050919050565b5f612a5382612a29565b9150819050919050565b5f612a678261232d565b9150612a728361232d565b9250828202612a808161232d565b91508282048414831517612a9757612a96612845565b5b5092915050565b5f612aa88261232d565b91507fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8203612ada57612ad9612845565b5b600182019050919050565b7f4e487b71000000000000000000000000000000000000000000000000000000005f52601260045260245ffd5b5f612b1c8261232d565b9150612b278361232d565b925082612b3757612b36612ae5565b5b828204905092915050565b7f4e487b71000000000000000000000000000000000000000000000000000000005f52604160045260245ffd5b5f612b798261232d565b9150612b848361232d565b925082612b9457612b93612ae5565b5b828206905092915050565b7f4e487b71000000000000000000000000000000000000000000000000000000005f52603260045260245ffd5b5f82825260208201905092915050565b828183375f83830152505050565b5f612bf58385612bcc565b9350612c02838584612bdc565b612c0b83612386565b840190509392505050565b5f60a082019050612c295f8301896124d9565b612c3660208301886124d9565b612c436040830187612715565b8181036060830152612c56818587612bea565b90508181036080830152612c6a8184612396565b9050979650505050505050565b612c8081612456565b8114612c8a575f5ffd5b50565b5f81519050612c9b81612c77565b92915050565b5f60208284031215612cb657612cb56122a0565b5b5f612cc384828501612c8d565b91505092915050565b5f606082019050612cdf5f830186612336565b612cec6020830185612336565b612cf96040830184612336565b949350505050565b5f604082019050612d145f830185612336565b8181036020830152612d268184612396565b9050939250505056fea2646970667358221220ffb5a3ed0c96dacaf2545c241af67b369012ebd7333f6dc917042bcaf5f2257464736f6c63430008240033"

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


def _encode_address(addr: str) -> str:
    """Manual ABI word for address — avoids eth_abi isinstance issues on Android."""
    a = addr.lower().replace("0x", "")
    if len(a) != 40:
        raise ValueError(f"bad address: {addr}")
    return a.rjust(64, "0")


def _encode_bytes32(b32: str) -> str:
    h = b32.lower().replace("0x", "")
    if len(h) != 64:
        raise ValueError(f"bad bytes32: {b32}")
    return h


def read_uint(rpc_url, contract, sig, address_arg=None):
    data = selector(sig)
    if address_arg:
        data += _encode_address(address_arg)
    return decode_uint(eth_call(rpc_url, contract, data))


def read_int(rpc_url, contract, sig, address_arg=None):
    data = selector(sig)
    if address_arg:
        data += _encode_address(address_arg)
    return decode_int(eth_call(rpc_url, contract, data))


def read_bool(rpc_url, contract, sig, bytes32_arg):
    data = selector(sig) + _encode_bytes32(bytes32_arg)
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
    """Returns (effective, minted, mintable). Raises on RPC/decode errors."""
    eff = read_int(rpc_url, LEDGER_ADDR, "effectiveOf(address)", user)
    minted = read_uint(rpc_url, csos_addr, "minted(address)", user)
    mintable = read_uint(rpc_url, csos_addr, "mintable(address)", user)
    return int(eff), int(minted), int(mintable)


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
# Color scheme from the green star logo
# =====================================================================
GREEN       = (0.00, 0.78, 0.33, 1)   # primary action
GREEN_DARK  = (0.00, 0.55, 0.22, 1)
BLUE        = (0.12, 0.35, 0.95, 1)
DARK_BG     = (0.06, 0.06, 0.06, 1)
GRAY        = (0.45, 0.45, 0.45, 1)
WHITE       = (1, 1, 1, 1)


def make_header(title_text):
    """Logo top-left + title + version — same style on every page."""
    from kivy.uix.image import Image
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    row = BoxLayout(orientation="horizontal", size_hint_y=None, height=56, spacing=8, padding=[4, 4, 4, 4])
    try:
        logo = Image(source="assets/logo.png", size_hint_x=None, width=52,
                     allow_stretch=True, keep_ratio=True)
        row.add_widget(logo)
    except Exception:
        pass
    mid = BoxLayout(orientation="vertical", size_hint_x=1)
    lbl = Label(text=title_text, bold=True, color=GREEN, halign="left", valign="bottom",
                size_hint_y=0.6)
    lbl.bind(size=lambda *_: setattr(lbl, "text_size", (lbl.width, lbl.height)))
    ver = Label(text=f"v{APP_VERSION}", color=(0.7, 0.9, 0.75, 1), halign="left", valign="top",
                size_hint_y=0.4, font_size="12sp")
    ver.bind(size=lambda *_: setattr(ver, "text_size", (ver.width, ver.height)))
    mid.add_widget(lbl)
    mid.add_widget(ver)
    row.add_widget(mid)
    return row



def make_unique_payload(user: str, amount: int) -> str:
    """Generate a unique payloadHash so the user never has to type one."""
    import os, time
    rand = os.urandom(32)
    raw = abi_encode(
        ["address", "uint256", "bytes32", "uint256"],
        [user, int(amount), rand, int(time.time())],
    )
    return "0x" + keccak(raw).hex()


def status_label(text=""):
    return Label(
        text=text, size_hint_y=None, height=28,
        color=GREEN, bold=True, halign="left", valign="middle",
    )


# =====================================================================
# Deploy tab  (kept almost identical, only green accents + logo)
# =====================================================================
class DeployTab(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=10, spacing=5, **kw)

        self.add_widget(make_header("SOS Deployer — Deploy"))

        self.pk       = make_input("Private key (0x...)", password=True)
        self.rpc_url  = make_input("RPC URL (mainnet)",
                                  text="https://ethereum-rpc.publicnode.com")
        self.chain_id = make_input("Chain ID (1=mainnet)", numeric=True,
                                   text="1")
        self.mint_fee = make_input("MINT_FEE in wei (recommend 0)", numeric=True, text="0")
        self.treasury = make_input("TREASURY address (0x...)",
                                   text="0x1C10e6574ee696f54b21A611a21313E4714628ad")
        for w in (self.pk, self.rpc_url, self.chain_id, self.mint_fee, self.treasury):
            self.add_widget(w)

        row = BoxLayout(size_hint_y=0.07, spacing=6)
        self.deploy_btn = Button(text="Deploy Contract", background_color=GREEN)
        self.check_ledger_btn = Button(text="Check LEDGER", background_color=GRAY)
        self.deploy_btn.bind(on_press=self.on_deploy)
        self.check_ledger_btn.bind(on_press=self.on_check_ledger)
        row.add_widget(self.deploy_btn)
        row.add_widget(self.check_ledger_btn)
        self.add_widget(row)

        self.etherscan_btn = Button(
            text="Open on Etherscan (verify source)", size_hint_y=0.07,
            background_color=BLUE, disabled=True)
        self.etherscan_btn.bind(on_press=self._on_etherscan)
        self.add_widget(self.etherscan_btn)

        self.mint_tab_btn = Button(
            text="→ Go to Mint tab (prefilled)", size_hint_y=0.07,
            background_color=GREEN, disabled=True)
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
                contract=self._last_addr or "",
                mint_fee=self.mint_fee.text.strip() or "0",
            )
            app.switch_to_tab(app.mint_tab)

    def on_check_ledger(self, *_):
        rpc_url = self.rpc_url.text.strip()
        if not rpc_url:
            self._log("❌ Enter RPC URL first.")
            return
        self._log(f"→ Checking LEDGER at {LEDGER_ADDR} …")
        threading.Thread(target=self._check_worker, args=(rpc_url,), daemon=True).start()

    def _check_worker(self, rpc_url):
        try:
            size = check_ledger_present(rpc_url)
            self._log(f"✅ LEDGER present ({size} bytes of code)")
            onchain_ds = decode_bytes32(eth_call(
                rpc_url, LEDGER_ADDR, selector("domainSeparator()")))
            chain_id = int(self.chain_id.text.strip() or "1")
            local_ds = compute_domain_separator(chain_id, LEDGER_ADDR)
            self._log(f"   on-chain domainSeparator = {onchain_ds}")
            self._log(f"   local domainSeparator    = {local_ds}")
            if onchain_ds.lower() == local_ds.lower():
                self._log("   ✅ domain separators match")
            else:
                self._log("   ⚠️  domain separators differ — check chain ID")
        except Exception as e:
            self._log(f"❌ {e}")

    def on_deploy(self, *_):
        pk = self.pk.text.strip()
        rpc_url = self.rpc_url.text.strip()
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
# Mint tab  — simplified, minimal user input
# =====================================================================
class MintTab(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=10, spacing=4, **kw)

        self.add_widget(make_header("SOS cSOS — Mint"))

        # Connection fields (can be prefilled from Deploy)
        self.rpc_url  = make_input("RPC URL",
                                  text="https://ethereum-rpc.publicnode.com")
        self.chain_id = make_input("Chain ID", numeric=True, text="1")
        self.pk       = make_input("Private key (signer = minter)", password=True)
        self.contract = make_input("cSOS contract address (0x...)",
                                   text="0xce9B507C242Adf722DD1DE2d7aa5Db1BF2259D8F")
        for w in (self.rpc_url, self.chain_id, self.pk, self.contract):
            self.add_widget(w)

        # Live status
        self.status = status_label("Connect & tap Refresh Status")
        self.add_widget(self.status)

        # Amount — the only number the user normally cares about
        self.amount = make_input("Amount to mint (leave blank = Mint Max)")
        self.add_widget(self.amount)

        # Optional donation
        self.donation = make_input("Optional donation in wei (0 = none)", numeric=True)
        self.donation.text = "0"
        self.add_widget(self.donation)

        # Advanced (collapsed by default – payload only shown for power users)
        self.payload = make_input("payloadHash (leave blank = auto-generate)")
        self.add_widget(self.payload)

        # Buttons
        row1 = BoxLayout(size_hint_y=0.07, spacing=6)
        b_refresh = Button(text="Refresh Status", background_color=GRAY)
        b_refresh.bind(on_press=lambda *_: self._start("status"))
        row1.add_widget(b_refresh)
        self.add_widget(row1)

        row2 = BoxLayout(size_hint_y=0.08, spacing=6)
        self.mint_btn = Button(text="Sign & Mint", background_color=GREEN)
        self.mint_btn.bind(on_press=lambda *_: self._start("mint"))
        row2.add_widget(self.mint_btn)
        self.add_widget(row2)

        # Log
        sv, self.log = make_log_area(
            "1. Fill RPC / key / contract (or come from Deploy tab)\n"
            "2. Tap Refresh Status\n"
            "3. Enter amount (or leave blank for max)\n"
            "4. Tap Sign & Mint — payloadHash is generated automatically\n")
        self.add_widget(sv)
        self._log = log_to(self.log)

        self._mint_fee = 0
        self._last_payload = None
        self._mintable = 0

    def prefill_from_deploy(self, rpc_url, chain_id, private_key, contract, mint_fee):
        self.rpc_url.text  = rpc_url or ""
        self.chain_id.text = chain_id or ""
        self.pk.text       = private_key or ""
        self.contract.text = contract or ""
        self._mint_fee     = int(mint_fee or 0)
        self._log(f"Prefill: contract={contract}  fee={self._mint_fee}")
        # auto-refresh status after a short delay
        Clock.schedule_once(lambda *_: self._start("status"), 0.4)

    def _start(self, mode):
        rpc_url = self.rpc_url.text.strip()
        chain_id = self.chain_id.text.strip()
        pk = self.pk.text.strip()
        csos = self.contract.text.strip()
        if not all([rpc_url, chain_id, pk, csos]):
            self._log("❌ Fill RPC, Chain ID, Private key and cSOS address.")
            return
        self.mint_btn.disabled = True
        threading.Thread(
            target=self._worker,
            args=(mode, rpc_url, int(chain_id), pk, csos),
            daemon=True).start()

    def _worker(self, mode, rpc_url, chain_id, pk, csos):
        try:
            acct = Account.from_key(pk)
            user = acct.address
            self._log(f"→ User = {user}")

            # Always fetch live status
            try:
                eff, minted, mintable = fetch_mint_status(rpc_url, csos, user)
                self._mintable = mintable
                status_txt = f"Effective {eff}  |  Minted {minted}  |  Mintable {mintable}"
                Clock.schedule_once(lambda *_: setattr(self.status, "text", status_txt))
                self._log(f"   {status_txt}")
            except Exception as e:
                self._log(f"⚠️  status read failed: {e}")
                if mode == "status":
                    return
                eff = minted = mintable = 0

            if mode == "status":
                self._log("✅ Status updated.")
                return

            # ---- prepare amount ----
            amount_txt = self.amount.text.strip()
            if amount_txt == "":
                amount = mintable
                if amount == 0:
                    self._log("❌ Nothing mintable (need effective > 10 and remaining capacity).")
                    return
                self._log(f"→ MintMax selected → amount = {amount}")
            else:
                amount = int(amount_txt)
                if amount <= 0:
                    self._log("❌ Amount must be > 0")
                    return
                if amount > mintable:
                    self._log(f"❌ Requested {amount} but only {mintable} mintable.")
                    return

            # ---- payloadHash (auto if blank) ----
            payload = self.payload.text.strip()
            if not payload:
                payload = make_unique_payload(user, amount)
                self._log(f"→ Auto payloadHash = {payload[:18]}…")
                Clock.schedule_once(lambda *_: setattr(self.payload, "text", payload))
            else:
                if not payload.startswith("0x"):
                    payload = "0x" + payload
                self._log(f"→ Using provided payloadHash = {payload[:18]}…")

            metadata = compute_metadata(amount)
            self._log(f"   metadata = {metadata}")

            # local struct hash
            local_sh = compute_struct_hash(user, user, payload, metadata)
            self._log(f"   local structHash = {local_sh}")

            # verify against LEDGER
            try:
                onchain_sh = verify_struct_hash(rpc_url, user, payload, metadata)
                if onchain_sh.lower() != local_sh.lower():
                    self._log("❌ structHash mismatch with LEDGER — aborting.")
                    return
                self._log("   ✅ hashes match")
            except Exception as e:
                self._log(f"   ⚠️  on-chain structHash call failed: {e}")

            try:
                used_ledger = read_bool(rpc_url, LEDGER_ADDR,
                                        "isRecordHashUsed(bytes32)", local_sh)
                if used_ledger:
                    self._log("❌ This exact record already exists on LEDGER.")
                    return
            except Exception as e:
                self._log(f"   ⚠️  isRecordHashUsed check failed: {e}")

            try:
                used_csos = read_bool(rpc_url, csos, "usedMintHash(bytes32)", local_sh)
                if used_csos:
                    self._log("❌ This mint hash is already used on cSOS.")
                    return
            except Exception as e:
                self._log(f"   ⚠️  usedMintHash check failed: {e}")

            # ---- sign ----
            self._log("→ Signing EIP-712 Record …")
            signature = sign_record(pk, chain_id, LEDGER_ADDR,
                                    user, user, payload, metadata)
            self._log(f"   signature = {signature[:20]}…")

            # ---- submit ----
            use_max = (self.amount.text.strip() == "")
            self._log(f"→ Submitting {'mintMax' if use_max else 'mint'} …")
            # note: donation is currently not attached to value; fee path still uses MINT_FEE
            tx_hash = submit_mint(rpc_url, chain_id, pk, csos, amount,
                                  payload, signature, self._mint_fee, use_max=use_max)
            self._log(f"✅ Minted {amount} cSOS")
            self._log(f"   Tx: {tx_hash}")
            self._log(f"   {explorer_url(chain_id, csos)}")

            self._last_payload = None
            Clock.schedule_once(lambda *_: setattr(self.payload, "text", ""))
            Clock.schedule_once(lambda *_: setattr(self.amount, "text", ""))

            try:
                new_bal = read_uint(rpc_url, csos, "balanceOf(address)", user)
                self._log(f"   balanceOf(user) = {new_bal}")
            except Exception:
                pass

            # refresh status numbers
            try:
                eff2, minted2, mintable2 = fetch_mint_status(rpc_url, csos, user)
                status_txt = f"Effective {eff2}  |  Minted {minted2}  |  Mintable {mintable2}"
                Clock.schedule_once(lambda *_: setattr(self.status, "text", status_txt))
            except Exception:
                pass

        except Exception as e:
            self._log(f"❌ {e}\n{traceback.format_exc()}")
        finally:
            Clock.schedule_once(lambda *_: setattr(self.mint_btn, "disabled", False))


# =====================================================================
# Query tab (simple read-only helper)
# =====================================================================
class QueryTab(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=10, spacing=5, **kw)

        self.add_widget(make_header("SOS — Query"))

        self.rpc_url  = make_input("RPC URL",
                                  text="https://ethereum-rpc.publicnode.com")
        self.address  = make_input("Address to query (0x...)")
        self.csos     = make_input("cSOS contract (optional)",
                                   text="0xce9B507C242Adf722DD1DE2d7aa5Db1BF2259D8F")
        for w in (self.rpc_url, self.address, self.csos):
            self.add_widget(w)

        row = BoxLayout(size_hint_y=0.07, spacing=6)
        b = Button(text="Query", background_color=GREEN)
        b.bind(on_press=self.on_query)
        row.add_widget(b)
        self.add_widget(row)

        sv, self.log = make_log_area("Enter an address and tap Query.\n")
        self.add_widget(sv)
        self._log = log_to(self.log)

    def on_query(self, *_):
        rpc_url = self.rpc_url.text.strip()
        addr = self.address.text.strip()
        csos = self.csos.text.strip()
        if not rpc_url or not addr:
            self._log("❌ RPC + address required.")
            return
        threading.Thread(target=self._worker, args=(rpc_url, addr, csos), daemon=True).start()

    def _worker(self, rpc_url, addr, csos):
        try:
            self._log(f"→ Query {addr}")
            push = read_uint(rpc_url, LEDGER_ADDR, "pushCountOf(address)", addr)
            trust = read_uint(rpc_url, LEDGER_ADDR, "trustCountOf(address)", addr)
            eff = read_int(rpc_url, LEDGER_ADDR, "effectiveOf(address)", addr)
            bal = read_uint(rpc_url, LEDGER_ADDR, "balanceOf(address)", addr)
            self._log(f"   Push   = {push}")
            self._log(f"   Trust  = {trust}")
            self._log(f"   Effective = {eff}")
            self._log(f"   balanceOf (SOS display) = {bal}")
            if csos:
                try:
                    m = read_uint(rpc_url, csos, "minted(address)", addr)
                    cbal = read_uint(rpc_url, csos, "balanceOf(address)", addr)
                    mintable = read_uint(rpc_url, csos, "mintable(address)", addr)
                    self._log(f"   cSOS minted   = {m}")
                    self._log(f"   cSOS balance  = {cbal}")
                    self._log(f"   cSOS mintable = {mintable}")
                except Exception as e:
                    self._log(f"   cSOS read error: {e}")
            self._log("✅ done")
        except Exception as e:
            self._log(f"❌ {e}")


# =====================================================================
# Root
# =====================================================================
class Root(TabbedPanel):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.do_default_tab = False
        self.tab_width = 120

        d = TabbedPanelItem(text="Deploy")
        d.add_widget(DeployTab())
        self.add_widget(d)

        m = TabbedPanelItem(text="Mint")
        m.add_widget(MintTab())
        self.add_widget(m)

        q = TabbedPanelItem(text="Query")
        q.add_widget(QueryTab())
        self.add_widget(q)

        self.default_tab = d


# =====================================================================
# Error screen
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
    title = f"SOS Deployer v{APP_VERSION}"
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
