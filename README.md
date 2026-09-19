# SOS Deployer v0.3 — Friendly Mint UX

Android / desktop tool for deploying and minting **SOS69069 cSOS**.

## What changed (v0.3)

- **Minimal input for minting**
  - User only needs: RPC, private key, cSOS address, and **Amount** (or leave blank = Mint Max)
  - `payloadHash` is **auto-generated** — no more typing random bytes32
  - Live status: Effective / Minted / Mintable
- Green color scheme matching the SOS star logo
- Logo shown on all tabs
- Cleaner single “Sign & Mint” button

## Tabs

| Tab    | Purpose                                      |
|--------|----------------------------------------------|
| Deploy | Deploy a new cSOS contract (MINT_FEE usually 0) |
| Mint   | Sign EIP-712 Record + mint cSOS              |
| Query  | Read Push / Trust / Effective / mintable     |

## Mint flow (user perspective)

1. Fill RPC + private key + cSOS address (or come from Deploy tab → green button)
2. Tap **Refresh Status**
3. Enter amount **or leave blank for Mint Max**
4. Tap **Sign & Mint**

The app automatically:
- builds metadata `cSOS:MINT:<amount>`
- generates a unique payloadHash
- signs the EIP-712 Record on the LEDGER domain
- submits the transaction

## Contracts

- LEDGER (immutable): `0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A`
- cSOS: the address returned by Deploy (or the one you already deployed)

## Build APK

```bash
buildozer android debug
```

Requires the usual Buildozer / Android SDK / NDK setup.

## Files that matter

- `main.py` — all logic + UI
- `assets/logo.png` — green star logo
- `buildozer.spec` — packaging
- `README.md` — this file

## Security note

This is a **power-user / deployer tool**. It uses a raw private key.
Do **not** use it as a public-facing wallet. For end users, build a proper
wallet-connected web dApp that never sees the private key.

## Prefill defaults (editable)

On open the app already fills safe public values. You can edit or paste over any of them.

| Field | Default |
|-------|---------|
| RPC URL | https://ethereum-sepolia-rpc.publicnode.com |
| Chain ID | 11155111 (Sepolia) |
| MINT_FEE | 0 |
| TREASURY | 0x1C10e6574ee696f54b21A611a21313E4714628ad |
| cSOS contract | 0xce9B507C242Adf722DD1DE2d7aa5Db1BF2259D8F |
| Donation | 0 |

Never prefilled: private key, amount, payloadHash, query address.

## Branding

- **App icon** (launcher): `icon.png` — SOS green star logo
- **Startup splash**: `presplash.png` — logo + SOS Deployer + **v0.3**
- In-app header: logo top-left + title + version on every tab
