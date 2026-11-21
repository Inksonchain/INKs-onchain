# INKs-onChain — Wix Ordinals-gated login

This is an integration draft, not a production-certified authentication system.

## Files
- backend/inksAuth.web.js: challenge, BIP-322 verification, live ownership check and session methods.
- pages/area-inks.js: Wix page code for Xverse/UniSat and the future private-area placeholder.

## Security model
- Short-lived one-time challenge; backend verifies the BIP-322 signature. Never request seed phrases, private keys, PSBTs, or transactions for login.
- Registry is pinned to immutable Git commit cd634d023be8f934d36e975f0d064e3a7675a2ac, not a moving main branch.
- Ownership lookup errors deny access. The JSON registry is collection membership only; it is not proof of current ownership.
- Session token is opaque, expires in 30 minutes, and only its SHA-256 hash is stored in CMS. Raw token stays in page memory; refresh requires login again.
- Current ownership is rechecked before revealing the placeholder area. Every future protected backend operation must revalidate the session and ownership itself.
- CMS collections must have Admin-only permissions. Never expose their data directly to the frontend.
- A unique-ID claim collection prevents two concurrent requests from consuming the same challenge. Keep its _id unique and its permissions Admin-only.

## Wix setup
1. Copy backend/inksAuth.web.js into Wix Velo's backend as inksAuth.web.js and pages/area-inks.js into the code for page /area-inks.
2. Add elements with IDs #connectXverse, #connectUnisat, #logoutButton, #statusText, and #privateArea. The private-area container must start collapsed.
3. Install sats-connect and bip322-js in Wix's package manager, and validate imports/API versions in Wix's current runtime.
4. Create these CMS collections, with Admin-only permissions:
   - InksAuthChallenges: address (text), message (text), expiresAt (date/time), used (boolean).
   - InksAuthChallengeClaims: claimedAt (date/time). The backend sets _id to the challenge ID.
   - InksAuthRateLimits: createdAt (date/time). Admin-only; backend creates a unique bucket per address/minute.
   - InksAuthSessions: tokenHash (text), address (text), expiresAt (date/time), createdAt (date/time).
5. Deploy first to a Wix test site, never directly to the live site.

## Wallet adapter
- Xverse adapter uses Sats Connect getAddresses for AddressPurpose.Ordinals and signMessage with BIP-322.
- UniSat adapter uses requestAccounts() and signMessage(message, bip322-simple).
- SDK APIs and response shapes may change. Verify them against exact installed package versions. Only mainnet Taproot addresses (bc1p...) are accepted in the example.
- The frontend is an integration example and has not been executed in the user's Wix environment. Do not publish before end-to-end tests.

## Ownership indexer — production blocker
The backend uses the documented batch endpoint POST https://ordinals.com/inscriptions with a JSON array of inscription IDs. The Ordinal Theory Handbook documents this endpoint and response objects containing an address field. See https://docs.ordinals.com/guides/api.html. This still needs an end-to-end live test against the public ordinals.com service and the exact Wix runtime before launch. If the service does not support the request or returns an unexpected schema, the code fails closed (denies login). Confirm the returned address represents the current controlling address for each inscription; for production, a dedicated indexer with documented availability/rate limits may be preferable. Never accept a client-supplied ownership claim.

The registry is fetched from:
https://raw.githubusercontent.com/Inksonchain/INKs-onchain/cd634d023be8f934d36e975f0d064e3a7675a2ac/data/INKs_traits.json

## Required pre-launch security tests
- Known holder succeeds in Xverse and UniSat; non-holder is denied.
- Wrong address, altered message, malformed signature, expired challenge and replay are rejected.
- Parallel replay of the same challenge yields at most one successful verification.
- Transfer the inscription to a different address and confirm the old owner loses access on the next protected check.
- Indexer outage, timeout, unexpected schema, and registry failure all deny access.
- Challenge creation is limited to one per address per minute through a unique CMS bucket. Add edge/IP-based throttling as additional protection; this per-address limit alone is not a complete anti-abuse system.
- Clean up expired challenges, claims, and sessions on a schedule.
- Confirm Wix supports the crypto imports and bip322-js in its backend runtime.
- Any future form submission must be a backend method that checks session, current ownership, field validation, and abuse limits before storing data. Hiding a Wix element is not authorization.
