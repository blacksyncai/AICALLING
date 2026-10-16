# CSV values on callbacks and redials

Campaign retry, manual campaign dial and the contact Call action all dispatch the saved Lead. They do not reread the uploaded CSV file on every attempt. CSV columns are retained as Lead custom fields and expanded into the worker's template variables.

An intermittent-looking precedence bug occurred after CRM linking: dial-time automatic CRM mappings could replace populated CSV variables, and campaign prefill could persist those replacements over the original values. For example, property_address was automatically mapped to the CRM mailing address after an initially unlinked CSV contact was linked by call sync/Radar.

Automatic mapping now preserves populated contact values (including zero/False). A concrete per-agent Script variables mapping can still deliberately override a CSV value; an empty mapping means automatic and '-' remains off. Missing variables still fill from CRM. Newly CRM-derived prefill values retain private per-provider provenance so they can refresh later; a later differing CSV/user edit clears that provenance and is protected. Provenance is excluded from visible/exported scalar fields and worker template values.

This fix does not reconstruct CSV values that were already overwritten before the update. Those require comparison with the original CSV before any repair. It also does not prove a particular live call used the wrong fields; call/contact examples are needed for that correlation. Agent-editor Call me intentionally has no selected Lead and therefore carries no CSV row context.

Regression coverage imports CSV contact data, links it to a CRM, repeatedly prefills/applies mapping, renders the actual script, and verifies values survive. It also checks explicit mappings, zero/False, CRM-derived refresh and later CSV edits. No calls are placed by these tests.
