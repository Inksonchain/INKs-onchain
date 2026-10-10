/**
 * Wix Velo page code for /area-inks.
 *
 * Add Wix page elements with these IDs:
 *   #connectXverse, #connectUnisat, #logoutButton, #statusText, #privateArea
 *
 * Install "sats-connect" as a site npm package for Xverse.
 * UniSat uses its injected browser provider. No wallet secret is ever read.
 * This page keeps the session token in memory only; refresh requires re-login.
 */
import {
  request as satsRequest,
  AddressPurpose,
} from "sats-connect";
import {
  createWalletChallenge,
  verifyWalletAndCreateSession,
  getPrivateAreaStatus,
  revokeWalletSession,
} from "backend/inksAuth.web";

let activeSessionToken = null;
let activeAddress = null;
let busy = false;

function setStatus(message) {
  $w("#statusText").text = message;
}

function setPrivateArea(visible) {
  if (visible) {
    $w("#privateArea").expand();
    $w("#logoutButton").show();
  } else {
    $w("#privateArea").collapse();
    $w("#logoutButton").hide();
  }
}

function validTaprootAddress(address) {
  return typeof address === "string" &&
    address.startsWith("bc1p") &&
    address.length >= 58 &&
    address.length <= 64;
}

async function authenticate(address, signMessage) {
  if (busy) return;
  busy = true;
  activeSessionToken = null;
  activeAddress = null;
  setPrivateArea(false);

  try {
    if (!validTaprootAddress(address)) {
      throw new Error("Seleziona un indirizzo Ordinals Taproot mainnet (bc1p).");
    }
    setStatus("Firma il messaggio di accesso nel wallet. Non verrà inviata alcuna transazione.");
    const challenge = await createWalletChallenge(address);
    const signature = await signMessage(challenge.message);
    if (typeof signature !== "string" || !signature.length) {
      throw new Error("Firma non ricevuta dal wallet.");
    }

    setStatus("Verifica firma e proprietà INK in corso…");
    const result = await verifyWalletAndCreateSession({
      challengeId: challenge.challengeId,
      signature,
    });
    if (!result || result.ok !== true || !result.sessionToken) {
      throw new Error("Autenticazione non riuscita.");
    }

    activeSessionToken = result.sessionToken;
    activeAddress = result.address;

    // Do not reveal the private area based only on the login response.
    const status = await getPrivateAreaStatus(activeSessionToken);
    if (!status.authorized) {
      activeSessionToken = null;
      activeAddress = null;
      throw new Error("Proprietà INK non verificata. Accesso negato.");
    }

    setPrivateArea(true);
    setStatus("Wallet verificato: " + activeAddress + ". Il modulo personale sarà disponibile prossimamente.");
  } catch (error) {
    console.error("INKs login failed:", error);
    setPrivateArea(false);
    setStatus(error && error.message
      ? error.message
      : "Accesso non riuscito. Riprova.");
  } finally {
    busy = false;
  }
}

async function connectXverse() {
  // Sats Connect requests the Ordinals purpose explicitly. BIP-322 is
  // the default for p2tr/Ordinals addresses in Xverse.
  const addressResponse = await satsRequest("getAddresses", {
    purposes: [AddressPurpose.Ordinals],
    message: "INKs-onChain: collega il wallet per verificare il possesso di un INK.",
  });

  if (!addressResponse || addressResponse.status !== "success") {
    throw new Error("Connessione Xverse annullata o non riuscita.");
  }
  const entries = addressResponse.result && addressResponse.result.addresses;
  const entry = Array.isArray(entries)
    ? entries.find((item) => item.purpose === AddressPurpose.Ordinals &&
        validTaprootAddress(item.address))
    : null;
  if (!entry) throw new Error("Xverse non ha restituito un indirizzo Ordinals Taproot.");

  await authenticate(entry.address, async (message) => {
    const signed = await satsRequest("signMessage", {
      address: entry.address,
      message,
      protocol: "BIP322",
    });
    if (!signed || signed.status !== "success" ||
        !signed.result || signed.result.address !== entry.address) {
      throw new Error("Firma Xverse annullata o indirizzo firmatario diverso.");
    }
    return signed.result.signature;
  });
}

async function connectUnisat() {
  const wallet = typeof window !== "undefined" ? window.unisat : null;
  if (!wallet || typeof wallet.getAccounts !== "function" ||
      typeof wallet.signMessage !== "function") {
    throw new Error("UniSat non rilevato. Installa o sblocca l'estensione UniSat.");
  }

  const accounts = await wallet.requestAccounts();
  const address = Array.isArray(accounts)
    ? accounts.find((item) => validTaprootAddress(item))
    : null;
  if (!address) throw new Error("UniSat non ha restituito un indirizzo Ordinals Taproot.");

  await authenticate(address, async (message) => {
    // UniSat explicitly supports the BIP-322 simple signing mode.
    return await wallet.signMessage(message, "bip322-simple");
  });
}

$w.onReady(() => {
  setPrivateArea(false);
  setStatus("Collega Xverse o UniSat per verificare il possesso di un INK.");

  $w("#connectXverse").onClick(async () => {
    try {
      await connectXverse();
    } catch (error) {
      console.error("Xverse connect failed:", error);
      setStatus(error && error.message ? error.message : "Connessione Xverse non riuscita.");
    }
  });

  $w("#connectUnisat").onClick(async () => {
    try {
      await connectUnisat();
    } catch (error) {
      console.error("UniSat connect failed:", error);
      setStatus(error && error.message ? error.message : "Connessione UniSat non riuscita.");
    }
  });

  $w("#logoutButton").onClick(async () => {
    const token = activeSessionToken;
    activeSessionToken = null;
    activeAddress = null;
    setPrivateArea(false);
    setStatus("Disconnessione completata.");
    if (token) {
      try {
        await revokeWalletSession(token);
      } catch (error) {
        // Local access is removed even if server-side revocation is unavailable.
        console.error("Session revocation failed:", error);
      }
    }
  });
});
