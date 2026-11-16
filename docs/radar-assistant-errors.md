# Radar assistant availability errors

On November 16, production recorded two HTTP 503 responses from the draft endpoint. The old exception handler returned the same manual-builder message for every unexpected failure and did not log its cause. Provider credentials were configured, but the historical exceptions cannot be reconstructed from those logs. An authenticated provider diagnostic from the workspace was blocked by network policy; provider billing, credentials, and availability have not been independently verified.

AI requests now retain structured status/error codes without keeping provider response text. Radar gives distinct messages for missing credentials/authentication, billing or usage limits, throttling, timeouts, connection failures, and upstream failures. An unknown application failure has a reference rather than claiming the whole assistant is unavailable. Logs contain the reference, model, exception class, provider status/code, and source locations; prompts, CRM context and secret values are excluded.

Radar retries a connection failure or upstream 5xx response once after 250 ms. Authentication, quota, throttling and long-running timeout failures do not retry. The existing CRM confirmation flow is unchanged. A fresh failed draft can be investigated by matching its reference to `radar_assistant_failed`; restoration of real provider service remains unconfirmed until a live request succeeds.

Vivian's former Version 2 (`37f2ad99-0bb7-421c-aaaa-5a57f2f6699c`) is now first and labeled Version 1. The former Version 1 is labeled Version 2; Version 3 is unchanged. Saved agent voice IDs are not migrated.
