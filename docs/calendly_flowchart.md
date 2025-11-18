# Scheduling Agent Booking/Cancellation Flow

```mermaid
flowchart TD
  H[handle_scheduling_email] --> C1[prepare_agent_context_for_request]
  H --> AG[run_meeting_scheduler_agent]
  H --> F[_find_event_for_cancellation]
  F -->|returns Event or None| H

  H --> CB[cancel_booking_event]
  CB --> CA[CalendlyAPIClient.cancel_invitee]
  CB --> DG[delete_calendar_event]
  CB -->|failures| SENT1[Sentry capture cancellation_failed]

  H --> SEL[select EventType]
  SEL --> CREATE[create_booking_event]
  CREATE --> CALBOOK[_create_calendly_booking]
  CALBOOK --> LOC[normalize location payload]
  CALBOOK --> CI[CalendlyAPIClient.create_invitee]
  CI --> EVT[Event persisted calendly]

  CREATE --> GCREATE[create_calendar_event]
  GCREATE --> EVT2[Event persisted google_id]

  CREATE --> SENT2[Sentry capture booking_creation_failed]

  H --> UPDATE[confirmed_slot updated; Event.meeting_request_id set]

  H --> REPLY[send_agent_reply_email]
  REPLY --> FU[follow-up scheduling]

  %% Notes:
  %% - _find_event_for_cancellation tries google_event_id, then meeting_request_id, then start_datetime.
  %% - cancel_booking_event logs/Sentry on failure and still marks event cancelled locally.
  %% - create_booking_event tries Calendly first, then Google fallback.
  %% - confirmed_slot persists google_event_id/conference_url when Google was used.
```
