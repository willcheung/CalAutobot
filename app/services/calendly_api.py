"""
Calendly API client for CalAutobot.

Provides methods to interact with Calendly API for:
- Event types
- Availability
- Scheduling (creating invitees)
- Cancellations
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import requests
from flask import current_app

from app import db
from app.models import User

logger = logging.getLogger(__name__)

CALENDLY_API_BASE = "https://api.calendly.com"


class CalendlyAPIError(Exception):
    """Raised when Calendly API returns an error."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class CalendlyAPIClient:
    """Client for interacting with Calendly API."""

    def __init__(self, user: User):
        """
        Initialize Calendly API client for a user.

        Args:
            user: User object with calendly_access_token
        """
        self.user = user
        self.access_token = user.calendly_access_token

        if not self.access_token:
            raise CalendlyAPIError("User has no Calendly access token")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Calendly API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        retry_on_401: bool = True,
    ) -> Dict:
        """
        Make a request to Calendly API with automatic token refresh.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/users/me")
            params: Query parameters
            json_data: JSON body for POST/PUT
            retry_on_401: Whether to retry with refreshed token on 401

        Returns:
            Response JSON

        Raises:
            CalendlyAPIError: If request fails
        """
        url = f"{CALENDLY_API_BASE}{endpoint}"
        headers = self._get_headers()

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=30,
            )

            # Handle 401 - token expired, try to refresh
            if response.status_code == 401 and retry_on_401:
                logger.info("Access token expired, attempting refresh")
                if self._refresh_token():
                    # Retry with new token (but don't retry again to avoid infinite loop)
                    return self._make_request(method, endpoint, params, json_data, retry_on_401=False)
                else:
                    raise CalendlyAPIError("Access token expired and refresh failed", 401)

            response.raise_for_status()
            return response.json()

        except requests.HTTPError as e:
            error_msg = f"Calendly API error: {e}"
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"Calendly API error: {error_detail.get('message', str(e))}"
                except Exception:
                    pass
            logger.error(error_msg)
            raise CalendlyAPIError(error_msg, e.response.status_code if e.response else None) from e

        except requests.RequestException as e:
            error_msg = f"Calendly API request failed: {str(e)}"
            logger.error(error_msg)
            raise CalendlyAPIError(error_msg) from e

    def _refresh_token(self) -> bool:
        """
        Refresh the access token.

        Returns:
            True if successful, False otherwise
        """
        from app.routes.calendly_auth import refresh_calendly_token

        success = refresh_calendly_token(self.user)
        if success:
            # Update the access token in this client instance
            self.access_token = self.user.calendly_access_token
        return success

    def get_current_user(self) -> Dict:
        """
        Get current user information.

        Returns:
            User data from Calendly

        Example response:
            {
                "resource": {
                    "uri": "https://api.calendly.com/users/AAAAAAAAAAAAAAAA",
                    "name": "John Doe",
                    "slug": "johndoe",
                    "email": "john@example.com",
                    "scheduling_url": "https://calendly.com/johndoe",
                    "timezone": "America/New_York",
                    "avatar_url": "https://...",
                    "created_at": "2020-01-01T00:00:00.000000Z",
                    "updated_at": "2020-01-01T00:00:00.000000Z",
                    "current_organization": "https://api.calendly.com/organizations/AAAAAAAAAAAAAAAA"
                }
            }
        """
        return self._make_request("GET", "/users/me")

    def get_event_types(self, user_uri: Optional[str] = None) -> List[Dict]:
        """
        Get all event types for a user.

        Args:
            user_uri: Calendly user URI. If None, uses current user's URI.

        Returns:
            List of event type objects

        Example response item:
            {
                "uri": "https://api.calendly.com/event_types/AAAAAAAAAAAAAAAA",
                "name": "30 Minute Meeting",
                "active": true,
                "slug": "30min",
                "scheduling_url": "https://calendly.com/johndoe/30min",
                "duration": 30,
                "kind": "solo",
                "type": "StandardEventType",
                ...
            }
        """
        if not user_uri:
            user_uri = self.user.calendly_user_uri

        if not user_uri:
            raise CalendlyAPIError("User URI is required to fetch event types")

        params = {"user": user_uri, "count": 100}  # Max 100 per page
        response = self._make_request("GET", "/event_types", params=params)

        return response.get("collection", [])

    def get_event_type_available_times(
        self,
        event_type_uri: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict]:
        """
        Get available time slots for an event type.

        Args:
            event_type_uri: Calendly event type URI
            start_time: Start of time range (must be in future)
            end_time: End of time range (max 7 days from start_time)

        Returns:
            List of available time slots

        Example response:
            {
                "collection": [
                    {
                        "start_time": "2020-01-01T09:00:00Z",
                        "invitees_remaining": 1,
                        "status": "available"
                    },
                    ...
                ]
            }

        Note: Calendly API limits to 7-day ranges
        """
        params = {
            "event_type": event_type_uri,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }

        response = self._make_request("GET", "/event_type_available_times", params=params)
        return response.get("collection", [])

    def create_invitee(
        self,
        event_type_uri: str,
        start_time: datetime,
        email: str,
        name: str,
        timezone: str = "UTC",
        guests: Optional[List[str]] = None,
        questions_and_answers: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Create a new scheduled event (book a meeting) via Scheduling API.

        Args:
            event_type_uri: Calendly event type URI
            start_time: Start time for the meeting
            email: Invitee email
            name: Invitee name
            timezone: Invitee timezone
            guests: List of guest email addresses
            questions_and_answers: Custom form questions/answers

        Returns:
            Created event data

        Example response:
            {
                "resource": {
                    "uri": "https://api.calendly.com/scheduled_events/AAAAAAAAAAAAAAAA",
                    "name": "30 Minute Meeting",
                    "status": "active",
                    "start_time": "2020-01-01T09:00:00Z",
                    "end_time": "2020-01-01T09:30:00Z",
                    "event_type": "https://api.calendly.com/event_types/...",
                    "location": {...},
                    "invitees": [
                        {
                            "uri": "https://api.calendly.com/scheduled_events/.../invitees/...",
                            "email": "invitee@example.com",
                            "name": "Jane Doe",
                            ...
                        }
                    ],
                    ...
                }
            }
        """
        payload = {
            "event_type": event_type_uri,
            "start_time": start_time.isoformat(),
            "invitee": {
                "email": email,
                "name": name,
                "timezone": timezone,
            }
        }

        if guests:
            payload["invitee"]["guests"] = guests

        if questions_and_answers:
            payload["invitee"]["questions_and_answers"] = questions_and_answers

        response = self._make_request("POST", "/scheduled_events", json_data=payload)
        return response.get("resource", {})

    def cancel_invitee(self, invitee_uri: str, reason: Optional[str] = None) -> bool:
        """
        Cancel a scheduled event invitee.

        Args:
            invitee_uri: Calendly invitee URI
            reason: Cancellation reason

        Returns:
            True if successful

        Note: This cancels the entire event if there's only one invitee
        """
        payload = {}
        if reason:
            payload["reason"] = reason

        # Extract event UUID from invitee URI
        # URI format: https://api.calendly.com/scheduled_events/{event_uuid}/invitees/{invitee_uuid}
        parts = invitee_uri.split("/")
        if len(parts) < 6:
            raise CalendlyAPIError(f"Invalid invitee URI format: {invitee_uri}")

        event_uuid = parts[4]

        endpoint = f"/scheduled_events/{event_uuid}/cancellation"
        self._make_request("POST", endpoint, json_data=payload)
        return True

    def get_scheduled_event(self, event_uri: str) -> Dict:
        """
        Get details of a scheduled event.

        Args:
            event_uri: Calendly event URI

        Returns:
            Event data
        """
        # Extract UUID from URI
        event_uuid = event_uri.split("/")[-1]
        response = self._make_request("GET", f"/scheduled_events/{event_uuid}")
        return response.get("resource", {})

    def list_scheduled_events(
        self,
        organization_uri: Optional[str] = None,
        user_uri: Optional[str] = None,
        min_start_time: Optional[datetime] = None,
        max_start_time: Optional[datetime] = None,
        count: int = 100,
    ) -> List[Dict]:
        """
        List scheduled events.

        Args:
            organization_uri: Filter by organization
            user_uri: Filter by user
            min_start_time: Events starting on or after this time
            max_start_time: Events starting before this time
            count: Number of results (max 100)

        Returns:
            List of scheduled events
        """
        params = {"count": min(count, 100)}

        if organization_uri:
            params["organization"] = organization_uri
        elif user_uri:
            params["user"] = user_uri
        else:
            # Default to current user
            if self.user.calendly_user_uri:
                params["user"] = self.user.calendly_user_uri

        if min_start_time:
            params["min_start_time"] = min_start_time.isoformat()
        if max_start_time:
            params["max_start_time"] = max_start_time.isoformat()

        response = self._make_request("GET", "/scheduled_events", params=params)
        return response.get("collection", [])

    def create_webhook_subscription(
        self,
        webhook_url: str,
        events: List[str],
        organization_uri: str,
        signing_key: str,
    ) -> Dict:
        """
        Create a webhook subscription.

        Args:
            webhook_url: URL to receive webhooks
            events: List of event types (e.g., ["invitee.created", "invitee.canceled"])
            organization_uri: Organization URI
            signing_key: Secret key for webhook signature verification

        Returns:
            Webhook subscription data
        """
        payload = {
            "url": webhook_url,
            "events": events,
            "organization": organization_uri,
            "signing_key": signing_key,
        }

        response = self._make_request("POST", "/webhook_subscriptions", json_data=payload)
        return response.get("resource", {})

    def delete_webhook_subscription(self, webhook_uri: str) -> bool:
        """
        Delete a webhook subscription.

        Args:
            webhook_uri: Webhook subscription URI

        Returns:
            True if successful
        """
        webhook_uuid = webhook_uri.split("/")[-1]
        self._make_request("DELETE", f"/webhook_subscriptions/{webhook_uuid}")
        return True
