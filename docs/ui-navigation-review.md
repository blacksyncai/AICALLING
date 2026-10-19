# Agent navigation and focus polish

UI-only changes: mobile editor tabs scroll horizontally with a visible next-tab cue; arrow keys/Home/End navigate tabs. Voice/model search inputs have stronger visual hierarchy, and Radar's composer uses 16px text. Shared dialogs dim the background and lock body scrolling (including nested open dialogs); Escape closes the top dialog before background pickers. Launch readiness displays the first blocker and its existing Fix action even when collapsed. The mobile setup wizard uses connected steps, matching the existing desktop sequence.

No saved agent, voice, model, prompt, calling, purchasing, or CRM behavior changes.

Validation: frontend type check and production build; Chromium at 390px and 1440px using actual components with sample data. Browser checks cover model search/selection, keyboard tab navigation, Escape dismissal, body-scroll restoration and page overflow. Screenshot fixtures live outside the production tree and are not deployed. The fixtures compose components for comparison; they are not screenshots of a live customer account. Real iOS Safari remains a manual rollout check.

Screenshots: /workspace/ui-review/{before,after}-{390,1440}-{workspace,dialog}.png. Workspace images include navigation, model search, voice search, readiness, setup steps and Radar composer; dialog images show backdrop changes.

Rollout: deploy UI change, check mobile agent tabs, Voice settings dismissal, Radar input and launch Fix links. Rollback by reverting this UI commit; no migration or data rollback required.
