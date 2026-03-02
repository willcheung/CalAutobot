# Lead/Duration Scoring Feature

**Status:** Design Phase
**Created:** 2026-02-28
**Owner:** Cal (AI CEO)

## Overview

Add intelligent scoring to meetings and leads based on duration, timing, and other factors. This helps users prioritize their calendar and understand the value of different meetings.

## User Stories

1. **As a busy professional**, I want to know which meetings are worth my time
2. **As a salesperson**, I want to prioritize leads based on engagement signals
3. **As a user**, I want to see a "priority score" on my calendar

## Scoring Algorithm

### Meeting Score (1-100)

```python
def calculate_meeting_score(meeting):
    score = 50  # Base score
    
    # Duration bonus (longer = more valuable)
    if meeting.duration_minutes >= 60:
        score += 15
    elif meeting.duration_minutes >= 30:
        score += 10
    elif meeting.duration_minutes >= 15:
        score += 5
    
    # Timing bonus (business hours = higher priority)
    if is_business_hours(meeting.start_time):
        score += 10
    
    # Recurring penalty (recurring = lower priority)
    if meeting.is_recurring:
        score -= 10
    
    # Weekend penalty
    if is_weekend(meeting.start_date):
        score -= 15
    
    # Invitee count bonus (more people = more important)
    if meeting.attendee_count >= 5:
        score += 10
    elif meeting.attendee_count >= 2:
        score += 5
    
    # Source bonus (scheduled via CalAutobot = higher value)
    if meeting.source == 'calendly':
        score += 5
    
    return max(1, min(100, score))
```

### Lead Score (1-100)

```python
def calculate_lead_score(lead):
    score = 50  # Base score
    
    # Email domain bonus
    if lead.email_domain in ['gmail.com', 'yahoo.com']:
        score -= 5  # Personal email
    elif lead.email_domain in ENTERPRISE_DOMAINS:
        score += 15  # Enterprise email
    
    # Response time bonus (faster = hotter)
    if lead.response_time_hours <= 1:
        score += 20
    elif lead.response_time_hours <= 4:
        score += 10
    
    # Meeting history bonus
    if lead.total_meetings >= 3:
        score += 15
    elif lead.total_meetings >= 1:
        score += 5
    
    # Follow-up engagement
    if lead.opened_followup:
        score += 10
    
    return max(1, min(100, score))
```

## Implementation Plan

### Phase 1: Database Schema
- Add `meeting_score` column to Event model
- Add `lead_score` column to Contact model
- Add `last_scored_at` timestamp

### Phase 2: Scoring Service
- Create `scoring_service.py`
- Implement scoring algorithms
- Add background job to score existing events

### Phase 3: UI Integration
- Display score on event cards
- Add "Priority" filter to calendar view
- Add score breakdown tooltip

### Phase 4: Analytics
- Track average scores over time
- Score-based insights ("Your highest-value meetings are on Tuesdays")

## Success Metrics

1. **Adoption**: 30% of users view priority scores weekly
2. **Accuracy**: User feedback on score relevance >80% positive
3. **Behavior change**: Users reschedule low-priority meetings

## Technical Notes

- Score should be recalculated when event details change
- Cache scores to avoid recalculation on every page load
- Consider ML model for personalized scoring in future

---

*Created by Cal, CEO of CalAutobot*
*Last updated: 2026-02-28*
