# INKs-onChain — Wix Ordinals-gated login

This folder contains a Wix Velo integration draft for holder-gated access.

## Files

- `backend/inksAuth.web.js`: backend challenge, BIP-322 verification, live ownership check and session methods.
- `pages/area-inks.js`: Wix page code for Xverse/UniSat wallet connection and the future private-area placeholder.

## Security model

- A wallet must sign a short-lived, one-time challenge. No seed phrase, private key, PSBT, or transaction is requested.
- The backend verifies the BIP-322 signature and checks current ownership of at least one inscription ID from the canonical `data/INKs_traits.json` registry.
- The private-area status call repeats the live ownership check. Fail closed if the indexer or signature verification fails.
- Session token is opaque, expires in 30 minutes, and only its SHA-256 hash is stored in the CMS. Frontend code holds the raw token in memory only; refresh requires a new login.
- CMS collections must have Admin-only permissions. Never expose these collections directly to the browser.
- Any future form submission must be a backend web method that revalidates the session and ownership immediately before saving the form data.

## Install in Wix

1. In Wix Velo, create backend web module `backend/inksAuth.web.js` and copy the corresponding file from this repository.
2. Add a Wix page at `/area-inks`. Add page elements with IDs:
   - `#connectXverse` (button)
   - `#connectUnisat` (button)
   - `#logoutButton` (button)
   - `#statusText` (text)
   - `#privateArea` (container/box, initially collapsed)
3. Paste `pages/area-inks.js` into the page's Velo code.
4. Add `sats-connect` and `bip322-js` using Wix's package manager, then confirm compatibility with the currently supported Wix runtime.
5. Create the CMS collections `InksAuthChallenges` and `InksAuthSessions`. Grant Admin-only permissions:
   - `InksAuthChallenges`: `address` (text), `message` (text), `expiresAt` (date/time), `used` (boolean).
   - `InksAuthSessions`: `tokenHash` (text), `address` (text), `expiresAt` (date/time), `createdAt` (date/time).
6. Test on a Wix test site before publishing.

## Wallet support notes

- Xverse uses Sats Connect's `getAddresses` with `AddressPurpose.Ordinals` and `signMessage` with `protocol: "BIP322"`.
- UniSat uses `requestAccounts()` and `signMessage(message, "bip322-simple")`.
- Wallet SDK responses can change; verify response shapes against the installed versions. The code intentionally checks the returned signing address for Xverse.
- The page is only an example integration and has not been run in your Wix site. Do not publish until both wallets pass end-to-end tests.

## Current ownership lookup

The backend reads inscription IDs from
`https://raw.githubusercontent.com/Inksonchain/INKs-onchain/main/data/INKs_traits.json`
and queries the Ordinals API batch endpoint `POST https://ordinals.com/inscriptions`, which returns inscription detail objects including the current `address`. The metadata registry is not treated as proof of ownership.

For a larger collection, the current design makes multiple batch requests on each ownership recheck and can be slow. Before production, use a tested Ordinals indexer with documented rate limits and, if needed, store its API key in Wix Secrets Manager. If the provider returns errors or an unexpected response, access is denied.

## Production hardening required

- Test BIP-322 verification using real signatures from both wallet types, including wrong-address, altered-message, expired-challenge and replay cases.
- Test current owner address behavior after a transfer and with a wallet that owns no INKs.
- Add rate limiting / abuse protection for challenge creation and verification.
- Add automatic cleanup of expired challenge and session records.
- Confirm Wix's Node runtime supports the `crypto` and `bip322-js` usage in the backend module.
- Keep private form data server-side; do not rely on merely hiding a Wix element or redirecting to a secret URL.
