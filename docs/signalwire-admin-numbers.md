# SignalWire numbers in admin

Admin → account → Phone numbers → Assign existing lists purchased voice numbers from the configured carriers. Refresh numbers after purchasing in the provider dashboard. Assigning a SignalWire number checks provider inventory, adds the caller ID to the dedicated LiveKit outbound trunk, and stores the carrier on the account number. Existing active assignments cannot be claimed by a different account. Removing an assignment does not release the number at SignalWire.

Required server environment:

- SIGNALWIRE_SPACE: project space hostname (no scheme), e.g. example.signalwire.com
- SIGNALWIRE_PROJECT_ID: SignalWire project ID
- SIGNALWIRE_API_TOKEN: secret API token with number inventory read permission
- SIGNALWIRE_SIP_OUTBOUND_TRUNK_ID: dedicated LiveKit outbound trunk ID

For this project the created trunk is ST_siy5enve8dx2. SIP credentials are stored on LiveKit, not in application source or the browser. API credentials must be entered securely in server environment settings. Inventory API integration is implemented against SignalWire's LaML-compatible IncomingPhoneNumbers endpoint; actual account access has not been verified.

Outbound calls select the trunk by the account's assigned caller ID, preserving the room/agent dispatch before SIP dialing. SignalWire recordings use LiveKit egress when recording is enabled and storage configured, even when the platform uses Twilio recording for Twilio numbers. Existing Bandwidth calls keep their current path. SignalWire inbound campaigns are explicitly blocked until provider inbound routing is implemented. The application does not purchase SignalWire numbers or change existing account defaults when another default already exists.

Validation: 26 backend tests passed (inventory, assignment, duplicate rejection, safe pagination, failed trunk update, dedicated-trunk dispatch and existing phone behavior); frontend production build passed. No live SignalWire call or provider purchase was made.
