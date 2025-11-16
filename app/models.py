from app import db
from flask_login import UserMixin
from datetime import datetime
import json

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    handle = db.Column(db.String(64), unique=True, index=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    google_id = db.Column(db.String(100), unique=True, nullable=True)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    participants = db.relationship('MeetingParticipant', back_populates='contact', lazy=True)
    label_links = db.relationship('ContactLabelLink', back_populates='contact', cascade='all, delete-orphan', lazy=True, overlaps="labels")
    labels = db.relationship('ContactLabel', secondary='contact_label_link', back_populates='contacts', lazy='selectin', overlaps="label_links")

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
