# Meetings calendar & Google Calendar

The **Meetings** page has a week calendar (one row per day) next to the list of
meeting cards.

- **Times.** A meeting's time is either *set* in BlackSync (from the "Set time" popup, or
  by dragging it on the calendar) or *read from the call*: what the agent agreed
  ("Tuesday at 2pm", "tomorrow 10:30 am", "March 5 at 3 PM") is read in the campaign's or
  account's time zone (Profile → Organization), relative to when the call happened.
  Anything vague ("sometime next week") stays **without a confirmed time** until someone
  sets it. Stored in the call's `extracted_data` (`_meeting_start`, `_meeting_minutes`),
  so no schema change.
- **Drag to move.** Scheduled meetings can be dragged to another day or time (15-minute
  steps). Completed / no-show / cancelled ones are fixed.

## Google Calendar

Owners and admins click **Connect with Google** on the Meetings page. Once connected:

- Your Google events show as grey "busy" blocks on the calendar, and a meeting can't be
  dropped on top of one.
- Meetings with a time are added to the calendar as events ("Meeting with …"), moved when
  the time changes, and removed when a meeting is cancelled. **Sync now** adds every
  upcoming meeting. Guests are never emailed (`sendUpdates=none`).
- The refresh token is stored encrypted (Fernet, `SECRETS_ENCRYPTION_KEY`) in
  `calendar_connections`, one connection per account. Disconnect revokes it.

### Server setup (once)

1. Google Cloud Console → APIs & Services → **Enable** "Google Calendar API".
2. **OAuth consent screen**: External, app name BlackSync, add the scopes
   `openid`, `email` and `https://www.googleapis.com/auth/calendar.events`.
   While the app is in *Testing*, add each Google account that will connect as a test
   user (up to 100). Publishing for everyone requires Google's verification because
   the calendar scope is sensitive.
3. **Credentials → Create OAuth client ID → Web application**, authorized redirect URI:
   `https://blacksync.si/api/calendar/google/callback`
4. Set on the server: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (and `APP_URL`,
   `SECRETS_ENCRYPTION_KEY`, already set).

Until those are set, the Meetings page shows the Google card with the button disabled.

### API

| Method | Path | |
|---|---|---|
| GET | `/api/calendar/google` | `{configured, connected, email, connected_at, can_manage}` |
| POST | `/api/calendar/google/connect` | `{url}` — Google consent URL (owners/admins) |
| GET | `/api/calendar/google/callback` | Google redirects here; back to `/meetings?google=connected` |
| DELETE | `/api/calendar/google` | Disconnect (revokes the token) |
| POST | `/api/calendar/google/sync` | Push upcoming scheduled meetings |
| GET | `/api/calendar/events?start&end` | Busy events (≤ 31 days) |
| PATCH | `/api/meetings/{call_id}` | `{status?, start? (ISO with offset or null), duration_minutes?}` |
