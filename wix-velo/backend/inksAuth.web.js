/**
 * INKs-onChain Ordinals-gated authentication for Wix Velo.
 *
 * Install the npm package "bip322-js" in Wix Package Manager.
 * Create backend-only CMS collections:
 *   InksAuthChallenges: _id, address, message, expiresAt, used
 *   InksAuthSessions:   _id, tokenHash, address, expiresAt, createdAt
 *
 * Fail closed: if signature verification, metadata retrieval, or Ordinals
 * ownership lookup fails, authentication is denied.
 */
import { Permissions, webMethod } from "wix-web-module";
import wixData from "wix-data";
import { fetch } from "wix-fetch";
import { Verifier } from "bip322-js";
import { randomBytes, createHash } from "crypto";

const CHALLENGES = "InksAuthChallenges";
const SESSIONS = "InksAuthSessions";
const CHALLENGE_TTL_MS = 5 * 60 * 1000;
const SESSION_TTL_MS = 30 * 60 * 1000;
const REGISTRY_URL =
  "https://raw.githubusercontent.com/Inksonchain/INKs-onchain/main/data/INKs_traits.json";
const ORDINALS_BATCH_URL = "https://ordinals.com/inscriptions";
const BATCH_SIZE = 40;

function randomHex(bytes = 32) {
  return randomBytes(bytes).toString("hex");
}

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function validBitcoinAddress(address) {
  return typeof address === "string" &&
    address.length >= 14 &&
    address.length <= 90 &&
    /^(bc1|[13])[a-zA-HJ-NP-Z0-9]+$/.test(address);
}

async function getRegistryIds() {
  const response = await fetch(REGISTRY_URL, { method: "get" });
  if (!response.ok) throw new Error("Registry unavailable");
  const registry = await response.json();
  if (!Array.isArray(registry) || registry.length === 0) {
    throw new Error("Registry format invalid");
  }
  const ids = [...new Set(registry.map((item) => item && item.id)
    .filter((id) => typeof id === "string" &&
      /^[0-9a-f]{64}i[0-9]+$/.test(id)))];
  if (ids.length === 0) throw new Error("No valid inscription IDs");
  return ids;
}

/**
 * Query the Ordinals indexer in batches and compare the live owner address.
 * Never use the metadata JSON or an OWNER CSV as proof of current ownership.
 */
async function ownsAnyInk(address) {
  const ids = await getRegistryIds();
  for (let start = 0; start < ids.length; start += BATCH_SIZE) {
    const batch = ids.slice(start, start + BATCH_SIZE);
    const response = await fetch(ORDINALS_BATCH_URL, {
      method: "post",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(batch),
    });
    if (!response.ok) throw new Error("Ordinals indexer unavailable");
    const items = await response.json();
    if (!Array.isArray(items)) throw new Error("Unexpected Ordinals response");
    if (items.some((item) => item && item.address === address &&
        batch.includes(item.id))) {
      return true;
    }
  }
  return false;
}

async function readChallenge(id) {
  try {
    return await wixData.get(CHALLENGES, id, { suppressAuth: true });
  } catch (_) {
    return null;
  }
}

/** Step 1: call from the page after connecting Xverse or UniSat. */
export const createWalletChallenge = webMethod(
  Permissions.Anyone,
  async (address) => {
    if (!validBitcoinAddress(address)) {
      throw new Error("Indirizzo Bitcoin non valido.");
    }
    const nonce = randomHex(24);
    const id = randomHex(16);
    const issuedAt = new Date();
    const expiresAt = new Date(issuedAt.getTime() + CHALLENGE_TTL_MS);
    const message = [
      "INKs-onChain — accesso area riservata",
      "Domain: inksonchain.art",
      "Address: " + address,
      "Nonce: " + nonce,
      "Issued At: " + issuedAt.toISOString(),
      "Expiration Time: " + expiresAt.toISOString(),
      "Purpose: Prove control of this Bitcoin address. No transaction will be sent.",
    ].join("\n");

    await wixData.insert(CHALLENGES, {
      _id: id,
      address,
      message,
      expiresAt,
      used: false,
    }, { suppressAuth: true });

    return { challengeId: id, message, expiresAt: expiresAt.toISOString() };
  }
);

/** Step 2: signature must be a BIP-322 simple signature encoded as base64. */
export const verifyWalletAndCreateSession = webMethod(
  Permissions.Anyone,
  async ({ challengeId, signature }) => {
    if (typeof challengeId !== "string" ||
        typeof signature !== "string" ||
        signature.length < 8 || signature.length > 10000) {
      throw new Error("Richiesta di autenticazione non valida.");
    }

    const challenge = await readChallenge(challengeId);
    if (!challenge || challenge.used ||
        new Date(challenge.expiresAt).getTime() < Date.now()) {
      throw new Error("Challenge scaduta o già utilizzata. Riprova.");
    }

    // Consume before verification to prevent replay/race reuse.
    await wixData.update(CHALLENGES, {
      ...challenge,
      used: true,
    }, { suppressAuth: true });

    let signatureValid = false;
    try {
      signatureValid = Verifier.verifySignature(
        challenge.address,
        challenge.message,
        signature
      );
    } catch (_) {
      signatureValid = false;
    }
    if (!signatureValid) throw new Error("Firma Bitcoin non valida.");

    let isHolder = false;
    try {
      isHolder = await ownsAnyInk(challenge.address);
    } catch (error) {
      console.error("INK ownership verification failed:", error);
      throw new Error("Verifica Ordinals temporaneamente non disponibile. Riprova.");
    }
    if (!isHolder) {
      throw new Error("Nessun Ordinal INKs-onChain trovato in questo wallet.");
    }

    const rawToken = randomHex(32);
    const expiresAt = new Date(Date.now() + SESSION_TTL_MS);
    await wixData.insert(SESSIONS, {
      tokenHash: sha256(rawToken),
      address: challenge.address,
      expiresAt,
      createdAt: new Date(),
    }, { suppressAuth: true });

    return {
      ok: true,
      address: challenge.address,
      sessionToken: rawToken,
      expiresAt: expiresAt.toISOString(),
    };
  }
);

/**
 * Step 3: call before returning any private data or accepting the future form.
 * Ownership is checked again on every protected request, not trusted from a
 * stale browser flag or the original login result.
 */
export const getPrivateAreaStatus = webMethod(
  Permissions.Anyone,
  async (sessionToken) => {
    if (typeof sessionToken !== "string" ||
        !/^[0-9a-f]{64}$/.test(sessionToken)) {
      return { authorized: false };
    }
    const tokenHash = sha256(sessionToken);
    const result = await wixData.query(SESSIONS)
      .eq("tokenHash", tokenHash)
      .limit(1)
      .find({ suppressAuth: true });
    const session = result.items[0];
    if (!session || new Date(session.expiresAt).getTime() < Date.now()) {
      return { authorized: false };
    }

    let stillHolder = false;
    try {
      stillHolder = await ownsAnyInk(session.address);
    } catch (error) {
      console.error("INK ownership recheck failed:", error);
      return { authorized: false, retryable: true };
    }
    if (!stillHolder) return { authorized: false, reason: "ownership-lost" };

    return {
      authorized: true,
      address: session.address,
      // Future form placeholder; do not put private form data here yet.
      formReady: false,
      message: "Wallet verificato. Il modulo personale sarà disponibile prossimamente.",
    };
  }
);

export const revokeWalletSession = webMethod(
  Permissions.Anyone,
  async (sessionToken) => {
    if (typeof sessionToken !== "string" ||
        !/^[0-9a-f]{64}$/.test(sessionToken)) return { ok: true };
    const tokenHash = sha256(sessionToken);
    const result = await wixData.query(SESSIONS)
      .eq("tokenHash", tokenHash)
      .limit(10)
      .find({ suppressAuth: true });
    await Promise.all(result.items.map((item) =>
      wixData.remove(SESSIONS, item._id, { suppressAuth: true })
    ));
    return { ok: true };
  }
);
