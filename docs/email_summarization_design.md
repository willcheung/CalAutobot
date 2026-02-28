# Email Summarization & Sender Categorization Feature

**Status:** Design Phase
**Created:** 2026-02-28
**Owner:** Cal (AI CEO)

## Overview

Add intelligent email summarization and sender categorization to CalAutobot. When users forward emails, Cal will:
1. Summarize the email content
2. Categorize the sender (e.g., newsletter, promotion, personal, business, urgent)
3. Track sender patterns over time

## User Stories

1. **As a busy professional**, I want Cal to tell me what an email is about without reading it
2. **As a CalAutobot user**, I want to see patterns in who emails me (newsletters vs personal)
3. **As a user**, I want Cal to prioritize emails that need action

## Technical Design

### 1. Database Schema

```sql
-- New table for email summaries
CREATE TABLE email_summaries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    text_input_id INTEGER REFERENCES text_inputs(id),
    sender_email VARCHAR(255),
    sender_domain VARCHAR(255),
    summary TEXT,
    category VARCHAR(50), -- 'newsletter', 'promotion', 'personal', 'business', 'urgent', 'scheduling', 'other'
    priority_score INTEGER, -- 1-10
    action_required BOOLEAN DEFAULT FALSE,
    action_description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- New table for sender patterns
CREATE TABLE sender_patterns (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    sender_email VARCHAR(255) UNIQUE,
    sender_name VARCHAR(255),
    category VARCHAR(50),
    email_count INTEGER DEFAULT 1,
    last_email_date TIMESTAMP,
    avg_priority_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 2. OpenAI Prompt for Summarization

```python
EMAIL_SUMMARY_PROMPT = """Analyze this email and provide:

1. **Summary**: A 1-2 sentence summary of what this email is about
2. **Category**: Classify as one of:
   - 'newsletter' (subscriptions, updates)
   - 'promotion' (marketing, sales)
   - 'personal' (friends, family)
   - 'business' (work, professional)
   - 'urgent' (needs immediate attention)
   - 'scheduling' (meeting requests, calendar-related)
   - 'other' (doesn't fit above)
3. **Priority**: Rate 1-10 (10 = urgent action needed)
4. **Action Required**: Does this email need a response or action?
5. **Action Description**: If action required, what specifically?

Output as JSON:
{
  "summary": "...",
  "category": "...",
  "priority": 5,
  "action_required": true/false,
  "action_description": "..." or null
}

Email content:
'''{email_text}'''
"""
```

### 3. Integration Points

#### A. Modify `event_extractor.py`
- After event extraction, also run summarization
- Store both events and summary

#### B. New Service: `email_summarizer.py`
```python
def summarize_email(text: str, from_email: str = None) -> dict:
    """
    Summarize email and categorize sender.
    Returns: {summary, category, priority, action_required, action_description}
    """
    pass

def update_sender_pattern(user_id: int, sender_email: str, category: str, priority: int):
    """
    Update sender pattern tracking for this user.
    """
    pass
```

#### C. API Endpoints
```
POST /api/email/summarize - Summarize an email
GET /api/senders - Get sender patterns for user
GET /api/senders/{category} - Get senders by category
```

### 4. UI Components

1. **Email Summary Card**: Show summary, category badge, priority indicator
2. **Sender Dashboard**: Show patterns by category
3. **Priority Inbox**: Filter emails by priority

### 5. Phased Implementation

#### Phase 1: Core Summarization (Week 1)
- [ ] Add database tables
- [ ] Implement `summarize_email()` function
- [ ] Integrate with existing email processing flow
- [ ] Store summaries in database

#### Phase 2: Sender Tracking (Week 2)
- [ ] Implement `update_sender_pattern()` function
- [ ] Track sender statistics
- [ ] Build sender patterns over time

#### Phase 3: UI & Dashboard (Week 3)
- [ ] Add summary display to existing UI
- [ ] Create sender dashboard
- [ ] Add priority filtering

#### Phase 4: Smart Features (Week 4)
- [ ] Auto-prioritize emails from known senders
- [ ] Suggest actions based on patterns
- [ ] Weekly email digest summary

## Success Metrics

1. **Summarization Accuracy**: >90% user satisfaction with summaries
2. **Categorization Accuracy**: >85% correct category assignments
3. **Time Saved**: Users report saving 5+ minutes per day
4. **Engagement**: 50%+ of users view summaries within 7 days

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| OpenAI API costs increase | Cache summaries, batch process |
| Categorization errors | Allow user corrections, learn from feedback |
| Privacy concerns | Summaries stored per-user, not shared |

## Dependencies

- OpenAI API (gpt-4.1-mini)
- PostgreSQL database
- Existing email processing pipeline

## Next Steps

1. Review and approve design
2. Create database migration
3. Implement Phase 1

---

*Created by Cal, CEO of CalAutobot*
*Last updated: 2026-02-28*
