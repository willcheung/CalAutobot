from app import db
from flask_login import UserMixin
from datetime import datetime
import json

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)  # Not unique - multiple people can share names
    handle = db.Column(db.String(64), unique=True, index=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)  # Email is unique
    google_id = db.Column(db.String(100), unique=True, nullable=True)  # Google ID is unique
    google_token = db.Column(db.Text, nullable=True)
    google_refresh_token = db.Column(db.Text, nullable=True)  # Store refresh token separately
    extraction_calendar_id = db.Column(db.String(100), nullable=True)  # Store Cal Pilot calendar ID
    default_booking_calendar_id = db.Column(db.String(255), nullable=True)
    timezone = db.Column(db.String(50), default='UTC')  # User's timezone
    profile_picture_url = db.Column(db.String(512), nullable=True)
    email_count = db.Column(db.Integer, default=0)  # Track emails sent for provisional users
    follow_up_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default="true")
    follow_up_first_delay_days = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    follow_up_second_delay_days = db.Column(db.Integer, nullable=False, default=2, server_default="2")
    meeting_reminder_lead_hours = db.Column(db.Integer, nullable=False, default=24, server_default="24")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Google Calendar webhook fields
    webhook_channel_id = db.Column(db.String(100), nullable=True)  # Google webhook channel ID
    webhook_resource_id = db.Column(db.String(100), nullable=True)  # Google webhook resource ID
    webhook_expiration = db.Column(db.DateTime, nullable=True)  # When webhook expires

    # Calendly integration fields
    calendly_access_token = db.Column(db.Text, nullable=True)
    calendly_refresh_token = db.Column(db.Text, nullable=True)
    calendly_user_uri = db.Column(db.String(255), nullable=True)
    calendly_organization_uri = db.Column(db.String(255), nullable=True)
    calendly_scheduling_url = db.Column(db.String(512), nullable=True)
    calendly_webhook_subscription_uri = db.Column(db.String(255), nullable=True)
    calendly_timezone = db.Column(db.String(64), nullable=True)
    calendly_plan = db.Column(db.String(50), nullable=True)
    calendly_connected_at = db.Column(db.DateTime, nullable=True)

    # Email tracking fields
    tracking_last_viewed_at = db.Column(db.DateTime, nullable=True)

    # Relationship with events
    events = db.relationship('Event', backref='user', lazy=True, cascade='all, delete-orphan')
    text_inputs = db.relationship('TextInput', backref='user', lazy=True, cascade='all, delete-orphan')
    additional_emails = db.relationship('UserEmail', backref='user', lazy=True, cascade='all, delete-orphan')
    event_types = db.relationship('EventType', backref='user', lazy=True, cascade='all, delete-orphan')
    availability_windows = db.relationship('AvailabilityWindow', backref='user', lazy=True, cascade='all, delete-orphan')
    calendars = db.relationship('UserCalendar', backref='user', lazy=True, cascade='all, delete-orphan')
    contacts = db.relationship('Contact', backref='user', lazy=True, cascade='all, delete-orphan')
    contact_labels = db.relationship('ContactLabel', backref='user', lazy=True, cascade='all, delete-orphan')

    @property
    def display_name(self) -> str:
        if self.username:
            return self.username.strip()
        if self.email:
            return self.email.split("@")[0]
        return "Guest"

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Event details
    event_name = db.Column(db.String(200), nullable=False)
    event_description = db.Column(db.Text)
    start_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time)
    start_datetime = db.Column(db.String(100))  # RFC3339 datetime string
    end_date = db.Column(db.Date)
    end_time = db.Column(db.Time)
    end_datetime = db.Column(db.String(100))  # RFC3339 datetime string
    location = db.Column(db.String(500))
    conference_url = db.Column(db.String(500), nullable=True)
    invitee_email = db.Column(db.String(255), nullable=True)
    invitee_name = db.Column(db.String(255), nullable=True)
    
    # Google Calendar integration
    google_event_id = db.Column(db.String(100))
    public_token = db.Column(db.String(64), nullable=True, unique=True)
    is_synced = db.Column(db.Boolean, default=False)

    # Calendly integration fields
    calendly_event_uri = db.Column(db.String(255), nullable=True, unique=True)
    calendly_invitee_uri = db.Column(db.String(255), nullable=True)
    calendly_last_synced_at = db.Column(db.DateTime, nullable=True)
    
    # Event duration
    duration_minutes = db.Column(db.Integer)  # Duration in minutes calculated from start/end times
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    extracted_at = db.Column(db.DateTime, default=datetime.utcnow)  # When this event was extracted from text
    status = db.Column(db.String(20), nullable=False, default="scheduled", server_default="scheduled")
    source = db.Column(db.String(20), nullable=False, default="unknown", server_default="unknown")
    
    # Link to original text input
    text_input_id = db.Column(db.Integer, db.ForeignKey('text_input.id'))
    meeting_request_id = db.Column(db.Integer, db.ForeignKey('meeting_request.id'), nullable=True)
    reminder_sent_at = db.Column(db.DateTime, nullable=True)
    
    # Composite index for bookings page performance
    __table_args__ = (
        db.Index('idx_user_status_date', 'user_id', 'status', 'start_date', 'start_time'),
    )

class UserEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Add unique constraint on email to prevent duplicates across users
    __table_args__ = (db.UniqueConstraint('email', name='unique_user_email'),)

class UserCalendar(db.Model):
    __tablename__ = "user_calendars"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    calendar_id = db.Column(db.String(255), nullable=False)
    calendar_name = db.Column(db.String(255), nullable=False)
    calendar_email = db.Column(db.String(255), nullable=True)
    access_role = db.Column(db.String(50), nullable=True)
    is_primary = db.Column(db.Boolean, default=False)
    is_selected_for_conflicts = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'calendar_id', name='uq_user_calendar'),
    )

class TextInput(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Input data
    original_text = db.Column(db.Text, nullable=False)
    source_type = db.Column(db.String(50), default='manual')  # manual, email
    from_email = db.Column(db.String(120))  # if source is email
    task_type = db.Column(db.String(50), nullable=True)  # extract_event, schedule_meeting, etc.
    raw_email_context = db.Column(db.Text, nullable=True)  # Optional JSON/serialized email metadata for scheduling

    # Processing results
    extracted_events_json = db.Column(db.Text)  # JSON string of extracted events
    processing_status = db.Column(db.String(50), default='pending')  # pending, completed, failed
    error_message = db.Column(db.Text)
    
    # OpenAI API tracking
    openai_status = db.Column(db.String(50), default='pending')  # pending, success, timeout, error, offline
    openai_error_message = db.Column(db.Text)  # Specific OpenAI error details
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with events
    events = db.relationship('Event', backref='text_input', lazy=True)
    
    @property
    def extracted_events(self):
        if self.extracted_events_json:
            try:
                return json.loads(self.extracted_events_json)
            except json.JSONDecodeError:
                return []
        return []
    
    @extracted_events.setter
    def extracted_events(self, events_list):
        self.extracted_events_json = json.dumps(events_list)


class MeetingRequest(db.Model):
    """
    Tracks a multi-party meeting coordination workflow.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text_input_id = db.Column(db.Integer, db.ForeignKey('text_input.id'), nullable=True)
    thread_id = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default='pending')  # pending, collecting, proposed, confirmed, reschedule_requested, completed
    current_step = db.Column(db.String(50), nullable=True)
    proposed_slots_json = db.Column(db.Text, nullable=True)
    previous_slots_json = db.Column(db.Text, nullable=True)
    confirmed_slot_json = db.Column(db.Text, nullable=True)
    last_message_at = db.Column(db.DateTime, nullable=True)
    last_agent_reply_at = db.Column(db.DateTime, nullable=True)
    next_follow_up_at = db.Column(db.DateTime, nullable=True)
    follow_up_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('meeting_requests', lazy=True))
    text_input = db.relationship('TextInput', backref=db.backref('meeting_request', uselist=False))
    participants = db.relationship('MeetingParticipant', backref='meeting_request', lazy=True, cascade='all, delete-orphan')
    messages = db.relationship('MeetingMessage', backref='meeting_request', lazy=True, cascade='all, delete-orphan')
    events = db.relationship('Event', backref='meeting_request', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'thread_id', name='uq_meeting_request_user_thread'),
        db.Index('ix_meeting_request_thread_id', 'thread_id'),
    )

    @property
    def proposed_slots(self):
        if not self.proposed_slots_json:
            return []
        try:
            return json.loads(self.proposed_slots_json)
        except json.JSONDecodeError:
            return []

    @proposed_slots.setter
    def proposed_slots(self, value):
        self.proposed_slots_json = json.dumps(value or [])

    @property
    def previous_slots(self):
        if not self.previous_slots_json:
            return []
        try:
            return json.loads(self.previous_slots_json)
        except json.JSONDecodeError:
            return []

    @previous_slots.setter
    def previous_slots(self, value):
        self.previous_slots_json = json.dumps(value or [])

    @property
    def confirmed_slot(self):
        if not self.confirmed_slot_json:
            return None
        try:
            return json.loads(self.confirmed_slot_json)
        except json.JSONDecodeError:
            return None

    @confirmed_slot.setter
    def confirmed_slot(self, value):
        self.confirmed_slot_json = json.dumps(value) if value else None


class MeetingParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meeting_request_id = db.Column(db.Integer, db.ForeignKey('meeting_request.id'), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), default='participant')  # participant, organizer, assistant
    status = db.Column(db.String(50), default='invited')  # invited, responded, confirmed
    latest_reply_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=True)

    contact = db.relationship('Contact', back_populates='participants')


class MeetingMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meeting_request_id = db.Column(db.Integer, db.ForeignKey('meeting_request.id'), nullable=False)
    sender_email = db.Column(db.String(255), nullable=False)
    message_id = db.Column(db.String(255), nullable=True)
    thread_id = db.Column(db.String(255), nullable=True)
    body_text = db.Column(db.Text, nullable=True)
    body_html = db.Column(db.Text, nullable=True)
    parsed_slots_json = db.Column(db.Text, nullable=True)  # structured slots detected in this message
    metadata_json = db.Column(db.Text, nullable=True)  # additional metadata (headers, etc.)
    received_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('message_id', name='uq_meeting_message_message_id'),
        db.Index('ix_meeting_message_message_id', 'message_id'),
    )

    @property
    def parsed_slots(self):
        if not self.parsed_slots_json:
            return []
        try:
            return json.loads(self.parsed_slots_json)
        except json.JSONDecodeError:
            return []

    @parsed_slots.setter
    def parsed_slots(self, value):
        self.parsed_slots_json = json.dumps(value or [])


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(32), nullable=True)
    timezone = db.Column(db.String(64), nullable=True)
    company = db.Column(db.String(255), nullable=True)
    job_title = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    linkedin_url = db.Column(db.String(512), nullable=True)
    first_seen_source = db.Column(db.String(50), nullable=True)
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_interaction_at = db.Column(db.DateTime, nullable=True)
    last_incoming_email_at = db.Column(db.DateTime, nullable=True)
    last_outgoing_email_at = db.Column(db.DateTime, nullable=True)
    follow_up_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    # Email tracking engagement metrics
    emails_received = db.Column(db.Integer, default=0, nullable=False, server_default="0")
    emails_opened = db.Column(db.Integer, default=0, nullable=False, server_default="0")
    last_email_opened_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    participants = db.relationship('MeetingParticipant', back_populates='contact', lazy=True)
    label_links = db.relationship('ContactLabelLink', back_populates='contact', cascade='all, delete-orphan', lazy=True, overlaps="labels")
    labels = db.relationship('ContactLabel', secondary='contact_label_link', back_populates='contacts', lazy='selectin', overlaps="label_links")
    tracking_recipients = db.relationship('TrackingRecipient', back_populates='contact', lazy=True)

    @property
    def email_open_rate(self):
        """Calculate engagement rate"""
        if self.emails_received == 0:
            return 0.0
        return round(self.emails_opened / self.emails_received, 3)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'email', name='uq_contact_user_email'),
        db.Index('ix_contact_user_last_interaction', 'user_id', 'last_interaction_at'),
    )


class ContactLabel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(16), nullable=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    label_links = db.relationship('ContactLabelLink', back_populates='label', cascade='all, delete-orphan', lazy=True, overlaps="contacts")
    contacts = db.relationship('Contact', secondary='contact_label_link', back_populates='labels', lazy='selectin', overlaps="label_links")

    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_contact_label_user_name'),
    )


class ContactLabelLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False, index=True)
    label_id = db.Column(db.Integer, db.ForeignKey('contact_label.id'), nullable=False, index=True)
    applied_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contact = db.relationship('Contact', back_populates='label_links', overlaps="contacts,labels")
    label = db.relationship('ContactLabel', back_populates='label_links', overlaps="contacts,labels")
    applied_by = db.relationship('User', foreign_keys=[applied_by_user_id])

    __table_args__ = (
        db.UniqueConstraint('contact_id', 'label_id', name='uq_contact_label_link'),
    )


class EmailAttachment(db.Model):
    """
    Model for storing email attachment metadata and processing status.
    Used for tracking attachment processing from Mailgun emails.
    """
    id = db.Column(db.Integer, primary_key=True)
    text_input_id = db.Column(db.Integer, db.ForeignKey('text_input.id'), nullable=False)
    
    # File metadata
    filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)  # MIME type
    file_size = db.Column(db.Integer, nullable=False)
    
    # Processing status
    processing_status = db.Column(db.String(50), default='pending')  # pending, processed, failed
    extracted_events_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship back to text input
    text_input = db.relationship('TextInput', backref=db.backref('attachments', lazy=True))

class GmailPushState(db.Model):
    """
    Tracks Gmail push notification watch state per monitored mailbox.
    We keep everything in a single row per email so the renewal job
    and push processor can share state without extra services.
    """
    id = db.Column(db.Integer, primary_key=True)
    email_address = db.Column(db.String(255), unique=True, nullable=False)
    last_history_id = db.Column(db.String(255), nullable=True)
    watch_resource_id = db.Column(db.String(255), nullable=True)
    watch_expiration = db.Column(db.DateTime, nullable=True)
    label_ids_json = db.Column(db.Text, nullable=True)
    processing_locked_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def label_ids(self):
        if not self.label_ids_json:
            return []
        try:
            return json.loads(self.label_ids_json)
        except json.JSONDecodeError:
            return []

    @label_ids.setter
    def label_ids(self, value):
        self.label_ids_json = json.dumps(value or [])

class CalWaitlist(db.Model):
    """
    Model for Cal AI scheduling assistant waitlist
    """
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EventType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    slug = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    is_active = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Calendly integration fields
    calendly_event_type_uri = db.Column(db.String(255), nullable=True, unique=True)
    is_calendly_managed = db.Column(db.Boolean, default=False, server_default="false")
    calendly_last_synced_at = db.Column(db.DateTime, nullable=True)
    calendly_scheduling_url = db.Column(db.String(512), nullable=True)
    calendly_location_json = db.Column(db.Text, nullable=True)
    calendly_kind = db.Column(db.String(50), nullable=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'slug', name='uq_event_type_user_slug'),)


class AvailabilityWindow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    weekday = db.Column(db.Integer, nullable=False)  # 0 = Monday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint('weekday >= 0 AND weekday <= 6', name='ck_availability_weekday_range'),
    )


# ==============================================================================
# Email Tracking Models
# ==============================================================================

class TrackingRequest(db.Model):
    """Represents a tracked email send"""
    __tablename__ = 'tracking_request'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    tracking_id = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Email metadata
    subject = db.Column(db.String(500), nullable=True)
    # NOTE: Recipients linked via TrackingRecipient junction table (not JSON)

    # Tracking configuration
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    tracking_enabled_at_send = db.Column(db.Boolean, default=True, nullable=False)

    # Metadata
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    first_opened_at = db.Column(db.DateTime, nullable=True)
    last_opened_at = db.Column(db.DateTime, nullable=True)
    open_count = db.Column(db.Integer, default=0, nullable=False)
    unique_open_count = db.Column(db.Integer, default=0, nullable=False)  # Distinct IPs

    # Gmail context
    gmail_message_id = db.Column(db.String(255), nullable=True)
    gmail_thread_id = db.Column(db.String(255), nullable=True, index=True)

    # Sender fingerprint for self-tracking detection
    sender_ip_hash = db.Column(db.String(64), nullable=True)  # SHA256 of sender's IP
    sender_user_agent_parsed = db.Column(db.JSON, nullable=True)  # Sender's user agent at send time

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    events = db.relationship('TrackingEvent', back_populates='tracking_request',
                            lazy='dynamic', cascade='all, delete-orphan',
                            order_by='TrackingEvent.opened_at.desc()')
    recipients = db.relationship('TrackingRecipient', back_populates='tracking_request',
                                lazy='dynamic', cascade='all, delete-orphan')
    user = db.relationship('User', backref=db.backref('tracking_requests', lazy='dynamic'))

    def to_dict(self, include_events=False, event_limit=10):
        data = {
            'id': self.id,
            'tracking_id': self.tracking_id,
            'subject': self.subject,
            'recipients': [
                {
                    'email': tr.contact.email,
                    'name': tr.contact.display_name,
                    'type': tr.recipient_type,
                    'opened': tr.has_opened
                }
                for tr in self.recipients
            ],
            'is_active': self.is_active,
            'sent_at': self.sent_at.isoformat() + 'Z' if self.sent_at else None,
            'first_opened_at': self.first_opened_at.isoformat() + 'Z' if self.first_opened_at else None,
            'last_opened_at': self.last_opened_at.isoformat() + 'Z' if self.last_opened_at else None,
            'open_count': self.open_count,
            'unique_open_count': self.unique_open_count,
            'gmail_thread_id': self.gmail_thread_id,
        }
        if include_events:
            # Limit events and sort by most recent
            events_list = sorted(self.events, key=lambda e: e.opened_at, reverse=True)[:event_limit]
            data['events'] = [event.to_dict() for event in events_list]
        return data


class TrackingRecipient(db.Model):
    """Junction table linking tracking requests to contacts"""
    __tablename__ = 'tracking_recipient'

    id = db.Column(db.Integer, primary_key=True)
    tracking_request_id = db.Column(db.Integer, db.ForeignKey('tracking_request.id'),
                                   nullable=False, index=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False, index=True)
    recipient_type = db.Column(db.String(10), nullable=False)  # 'to', 'cc', 'bcc'

    # Per-recipient engagement for this email
    has_opened = db.Column(db.Boolean, default=False, nullable=False)
    first_opened_at = db.Column(db.DateTime, nullable=True)
    open_count = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tracking_request = db.relationship('TrackingRequest', back_populates='recipients')
    contact = db.relationship('Contact', back_populates='tracking_recipients')

    def to_dict(self):
        return {
            'contact_id': self.contact_id,
            'email': self.contact.email,
            'name': self.contact.display_name,
            'type': self.recipient_type,
            'has_opened': self.has_opened,
            'first_opened_at': self.first_opened_at.isoformat() + 'Z' if self.first_opened_at else None,
            'open_count': self.open_count
        }


class TrackingEvent(db.Model):
    """Represents a single email open event"""
    __tablename__ = 'tracking_event'

    id = db.Column(db.Integer, primary_key=True)
    tracking_request_id = db.Column(db.Integer, db.ForeignKey('tracking_request.id'),
                                   nullable=False, index=True)

    # Event data
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    ip_hash = db.Column(db.String(64), nullable=True, index=True)  # SHA256 for privacy

    # Client information - parsed from user agent
    user_agent_parsed = db.Column(db.JSON, nullable=True)
    # Stores: {"browser": "Chrome 120", "os": "Mac OS X", "device": "Desktop"}

    # Geolocation - from IP lookup (ip-api.com free tier)
    country_code = db.Column(db.String(2), nullable=True)  # "US", "GB", etc.
    region = db.Column(db.String(100), nullable=True)  # State/province: "CA", "NY", "England"
    city = db.Column(db.String(100), nullable=True)
    timezone = db.Column(db.String(50), nullable=True)  # "America/Los_Angeles"

    # Metadata
    is_first_open = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    tracking_request = db.relationship('TrackingRequest', back_populates='events')

    def to_dict(self):
        return {
            'id': self.id,
            'opened_at': self.opened_at.isoformat() + 'Z' if self.opened_at else None,
            'user_agent_parsed': self.user_agent_parsed,
            'city': self.city,
            'region': self.region,
            'country_code': self.country_code,
            'timezone': self.timezone,
            'is_first_open': self.is_first_open,
        }


class NewsletterSubscriber(db.Model):
    """Subscribers to Cal's Daily Briefing - AI CEO updates"""
    __tablename__ = 'newsletter_subscriber'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    source = db.Column(db.String(50), default='website')  # website, twitter, referral
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'source': self.source,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'unsubscribed_at': self.unsubscribed_at.isoformat() + 'Z' if self.unsubscribed_at else None,
        }
