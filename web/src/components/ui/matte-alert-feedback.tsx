"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface MatteAlertFeedbackProps {
  /** Heading of the surrounding card. */
  cardTitle?: string;
  /** Supporting copy under the card heading. */
  cardDescription?: string;
  /** Small pill badge shown next to the card heading. */
  pillText?: string;
  /** Title of the inline alert message. */
  alertTitle?: string;
  /** Detail copy of the inline alert message. */
  alertDetail?: string;
  /** Label of the button that (re)shows the alert. */
  buttonLabel?: string;
  /** Caption shown under the demo controls. */
  caption?: string;
  /** Whether the alert is visible on mount. */
  defaultVisible?: boolean;
  /** Show the "Show alert" button and caption under the card (the original demo controls). */
  showControls?: boolean;
  /** Remember a dismissal in this browser under this key (in-app use). */
  persistKey?: string;
  /** Optional action rendered under the card copy (e.g. a link). */
  action?: React.ReactNode;
  /** Called after the alert is dismissed. */
  onDismiss?: () => void;
  /** Called after the alert is (re)shown. */
  onShow?: () => void;
}

function readDismissed(key?: string): boolean {
  if (!key) return false;
  try {
    return localStorage.getItem(`matte-alert:${key}`) === "1";
  } catch {
    return false;
  }
}

function writeDismissed(key: string | undefined, dismissed: boolean) {
  if (!key) return;
  try {
    if (dismissed) localStorage.setItem(`matte-alert:${key}`, "1");
    else localStorage.removeItem(`matte-alert:${key}`);
  } catch {
    /* storage unavailable — dismissal just won't stick */
  }
}

/**
 * React port of the SL UI Library "alert" feedback package. A card contains a collapsible inline
 * alert; a close button dismisses it, and a "Show alert" button brings it back. Visibility changes
 * are announced through a polite live region. Styles live in globals.css (`.fb-*`).
 */
export default function MatteAlertFeedback({
  cardTitle = "Project access",
  cardDescription = "Only invited people can open this project.",
  pillText = "Private",
  alertTitle = "Review permissions",
  alertDetail = "Two invitations are still pending.",
  buttonLabel = "Show alert",
  caption = "Close and reopen the message.",
  defaultVisible = true,
  showControls = true,
  persistKey,
  action,
  onDismiss,
  onShow,
}: MatteAlertFeedbackProps) {
  const [visible, setVisible] = useState(defaultVisible);
  const [liveMessage, setLiveMessage] = useState("");
  const showButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (readDismissed(persistKey)) setVisible(false);
  }, [persistKey]);

  const handleDismiss = useCallback(() => {
    setVisible(false);
    setLiveMessage("Message dismissed.");
    writeDismissed(persistKey, true);
    requestAnimationFrame(() => {
      showButtonRef.current?.focus({ preventScroll: true });
    });
    onDismiss?.();
  }, [onDismiss, persistKey]);

  const handleShow = useCallback(() => {
    setVisible(true);
    setLiveMessage(alertTitle);
    writeDismissed(persistKey, false);
    onShow?.();
  }, [alertTitle, onShow, persistKey]);

  return (
    <div className="fb-demo" data-feedback="alert" tabIndex={-1}>
      <div className="fb-scene">
        <div className="fb-card">
          <div className="fb-card-head">
            <h3>{cardTitle}</h3>
            {pillText && <span className="fb-pill">{pillText}</span>}
          </div>
          <p>{cardDescription}</p>
          {action && <div className="fb-action">{action}</div>}
          <div className="fb-collapse" data-panel data-visible={visible ? "true" : "false"}>
            <div>
              <div className="fb-alert">
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="m10.3 4.8-8 13.8A1.6 1.6 0 0 0 3.7 21h16.6a1.6 1.6 0 0 0 1.4-2.4l-8-13.8a2 2 0 0 0-3.4 0Z" />
                  <path d="M12 9v5m0 3h.01" />
                </svg>
                <div className="fb-copy">
                  <h3 data-title>{alertTitle}</h3>
                  <p data-detail>{alertDetail}</p>
                </div>
                <button className="fb-close" type="button" data-action="dismiss" aria-label="Dismiss notification" onClick={handleDismiss}>
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="m6 6 12 12M6 18 18 6" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      {showControls && (
        <>
          <div className="fb-tools">
            <button type="button" className="fb-button" data-demo="show" ref={showButtonRef} onClick={handleShow}>
              {buttonLabel}
            </button>
          </div>
          <p className="fb-caption">{caption}</p>
        </>
      )}
      <span className="fb-sr" data-live role="status" aria-live="polite" aria-atomic="true">
        {liveMessage}
      </span>
      <span className="fb-sr" data-error role="alert" aria-atomic="true"></span>
    </div>
  );
}
