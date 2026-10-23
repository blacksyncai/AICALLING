import { post } from "@/lib/api";

/** What a checkout endpoint returns: a Stripe URL, or a HelcimPay.js session (Canada/other). */
export type CheckoutResult = { url: string } | { helcim: { checkout_token: string; purchase_id: string } };

declare global {
  interface Window {
    appendHelcimPayIframe?: (token: string, allowExit?: boolean) => void;
    removeHelcimPayIframe?: () => void;
  }
}

const SCRIPT = "https://secure.helcim.app/helcim-pay/services/start.js";
let loading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.appendHelcimPayIframe) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loading = null;
      reject(new Error("Couldn't load the payment form. Check your connection and try again."));
    };
    document.head.appendChild(s);
  });
  return loading;
}

/** Open Helcim's payment modal and confirm the payment with our backend.
 * Resolves true when paid, false when the customer closed the modal. */
export async function payWithHelcim({ checkout_token, purchase_id }: { checkout_token: string; purchase_id: string }): Promise<boolean> {
  await loadScript();
  return new Promise<boolean>((resolve, reject) => {
    const key = `helcim-pay-js-${checkout_token}`;
    const done = (fn: () => void) => {
      window.removeEventListener("message", onMessage);
      window.removeHelcimPayIframe?.();
      fn();
    };
    async function onMessage(event: MessageEvent) {
      const msg = event.data;
      if (!msg || msg.eventName !== key) return;
      if (msg.eventStatus === "ABORTED" || msg.eventStatus === "HIDE") return done(() => resolve(false));
      if (msg.eventStatus !== "SUCCESS") return;
      try {
        const data = typeof msg.eventMessage === "string" ? JSON.parse(msg.eventMessage) : msg.eventMessage;
        await post("/api/billing/helcim/confirm", { purchase_id, data });
        done(() => resolve(true));
      } catch (e) {
        done(() => reject(e));
      }
    }
    window.addEventListener("message", onMessage);
    window.appendHelcimPayIframe!(checkout_token, true);
  });
}

/** Send the browser to Stripe, or run the Helcim modal in place. Returns true when a Helcim payment went through. */
export async function startCheckout(result: CheckoutResult): Promise<boolean | "redirect"> {
  if ("url" in result) {
    window.location.href = result.url;
    return "redirect";
  }
  return payWithHelcim(result.helcim);
}
