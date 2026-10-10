# INKs-onChain — Wix Ordinals Login

This folder contains the first Wix Velo integration draft for a holder-gated private area. It is intentionally separate from the collection metadata under `data/`.

## Flow

1. Connect Xverse or UniSat on the Wix page and obtain a Bitcoin address.
2. Call `createWalletChallenge(address)`.
3. Ask the wallet to sign the returned `message` using BIP-322 simple signing.
4. Send `{ challengeId, signature }` to `verifyWalletAndCreateSession`.
5. Keep the returned session token in session-only browser memory/storage; call `getPrivateAreaStatus(token)` before showing the private area and before any future form submission.
6. Call `revokeWalletSession(token)` on logout.

No transaction is requested. Never ask for a seed phrase or private key.

## Install in Wix

1. In Wix Velo, create a backend web module named `inksAuth.web.js` and paste `backend/inksAuth.web.js`.
2. Install the npm package `bip322-js` in Wix Package Manager. Its current package API exposes `Verifier.verifySignature(address, message, signature)`; verify package compatibility in Wix's current Node runtime before publishing.
3. Create two CMS collections with **Admin-only permissions**:
   - `InksAuthChallenges`: `address` (text), `message` (text), `expiresAt` (date/time), `used` (boolean).
   - `InksAuthSessions`: `tokenHash` (text), `address` (text), `expiresAt` (date/time), `createdAt` (date/time).
   The code supplies `_id` for challenges. Do not grant public read/write permissions to either collection.
4. Add a Wix page named `/area-inks` with connect-wallet buttons and a private-area container. Import methods from `backend/inksAuth.web`.
5. Use wallet SDK APIs from the currently supported Xverse/Sats Connect version and UniSat provider. The wallet adapter must return the exact address that will sign the challenge and the base64 BIP-322 signature. Do not assume every wallet address type supports the same signing method.
6. Test with a holder and non-holder wallet on a Wix test site before publishing.

## Current ownership lookup

The code reads the canonical inscription IDs from
`https://raw.githubusercontent.com/Inksonchain/INKs-onchain/main/data/INKs_traits.json`
and compares them against live owner addresses returned by the Ordinals indexer at `https://ordinals.com/inscriptions`. The JSON supplies collection membership/traits, **not ownership**.

This is a minimal initial indexer adapter, not a high-volume production indexer. It requests inscription batches and can be slow for a large collection; if the public indexer rejects batch requests or is unavailable, the check fails closed. For production, replace this adapter with a supported, authenticated Ordinals API and keep its API key in Wix Secrets Manager. Test the exact API response and current ownership semantics before launch.

## Important security / production checklist

- This source has not been executed inside Wix; validate the Node built-in `crypto` import and `bip322-js` dependency against the Wix runtime.
- Add rate limiting and cleanup of expired challenges/sessions.
- The challenge is single-use and short-lived; the signature is verified server-side.
- The session token is opaque; only its SHA-256 hash is stored in the CMS. It expires after 30 minutes.
- Ownership is rechecked for every protected request. If the indexer fails, access is denied temporarily.
- Do not put protected form data in frontend code or in a publicly readable CMS collection. Implement future form submission as a backend web method that validates the session and holder status again.
- Wallet-specific frontend signing adapters and the visual page are intentionally not included yet; these must be wired to the exact Xverse and UniSat SDK versions used by the site.
