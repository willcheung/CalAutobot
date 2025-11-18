# Scheduling Agent Booking/Cancellation Flow

```mermaid
flowchart TD
  H[handle_scheduling_email] -->|context=prepare_agent_context_for_request(user,mr)| C1[prepare_agent_context_for_request]
  H -->|availability ok → run| AG[run_meeting_scheduler_agent]
  H -->|action in {cancel_meeting,reschedule}\nslot_reference=confirmed_slot/rescheduled_from| F[_find_event_for_cancellation]
  F -->|returns Event or None| H

  H -->|when cancel_meeting/reschedule\nand event found| CB[cancel_booking_event]
  CB -->|calendly_invitee_uri -> cancel_invitee| CA[CalendlyAPIClient.cancel_invitee]
  CB -->|google_event_id -> delete_calendar_event| DG[delete_calendar_event]
  CB -->|failures| SENT1[Sentry capture cancellation_failed]

  H -->|effective_action=confirm_slot| SEL[select EventType]
  SEL -->|event_type, slot_start/end, invitee info| CREATE[create_booking_event]
  CREATE -->|if Calendly| CALBOOK[_create_calendly_booking]
  CALBOOK -->|location from event_type.calendly_location_json| LOC[normalize location payload]
  CALBOOK -->|create_invitee(...)| CI[CalendlyAPIClient.create_invitee]
  CI -->|response includes calendly_event_uri/invitee_uri| EVT[Event persisted (calendly URIs)]

  CREATE -->|fallback Google| GCREATE[create_calendar_event]
  GCREATE -->|returns google_event_id, conference_url| EVT2[Event persisted (google_event_id)]

  CREATE -->|on error| SENT2[Sentry capture booking_creation_failed]

  H -->|after creation| UPDATE[confirmed_slot updated; Event.meeting_request_id set]

  H -->|send reply?\nBlocked if creation_failed or cancellation_failed| REPLY[send_agent_reply_email]
  REPLY -->|tracks follow-ups| FU[follow-up scheduling]

  %% Notes:
  %% - _find_event_for_cancellation tries google_event_id, then meeting_request_id, then start_datetime.
  %% - cancel_booking_event logs/Sentry on failure and still marks event cancelled locally.
  %% - create_booking_event tries Calendly first, then Google fallback.
  %% - confirmed_slot persists google_event_id/conference_url when Google was used.
```
