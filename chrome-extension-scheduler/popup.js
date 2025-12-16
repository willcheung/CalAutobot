/**
 * Popup UI Logic for CalAutobot Email Tracking Dashboard
 */

const API_BASE_URL = 'http://localhost:5001';

// State
let trackingData = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  loadTrackingData();

  // Event listeners
  document.getElementById('refreshBtn').addEventListener('click', () => {
    loadTrackingData();
  });

  document.getElementById('retryBtn').addEventListener('click', () => {
    loadTrackingData();
  });
});

/**
 * Load tracking data from API
 */
async function loadTrackingData() {
  showLoading();

  try {
    // Get auth token from background
    const { token } = await chrome.runtime.sendMessage({ action: 'GET_AUTH_TOKEN' });

    if (!token) {
      throw new Error('Not authenticated');
    }

    // Fetch tracking requests
    const response = await fetch(`${API_BASE_URL}/api/tracking/requests`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      throw new Error('Failed to fetch tracking data');
    }

    const data = await response.json();

    if (!data.success) {
      throw new Error(data.error || 'Unknown error');
    }

    trackingData = data.requests || [];

    // Clear badge when popup is opened
    await chrome.action.setBadgeText({ text: '' });
    await chrome.storage.local.set({ notifiedOpens: {} });

    renderTrackingList();

  } catch (error) {
    console.error('Error loading tracking data:', error);
    showError();
  }
}

/**
 * Show loading state
 */
function showLoading() {
  document.getElementById('loading').style.display = 'flex';
  document.getElementById('error').style.display = 'none';
  document.getElementById('empty').style.display = 'none';
  document.getElementById('trackingList').style.display = 'none';
}

/**
 * Show error state
 */
function showError() {
  document.getElementById('loading').style.display = 'none';
  document.getElementById('error').style.display = 'flex';
  document.getElementById('empty').style.display = 'none';
  document.getElementById('trackingList').style.display = 'none';
}

/**
 * Render tracking list
 */
function renderTrackingList() {
  document.getElementById('loading').style.display = 'none';
  document.getElementById('error').style.display = 'none';

  if (!trackingData || trackingData.length === 0) {
    document.getElementById('empty').style.display = 'flex';
    document.getElementById('trackingList').style.display = 'none';
    return;
  }

  document.getElementById('empty').style.display = 'none';
  document.getElementById('trackingList').style.display = 'block';

  const listEl = document.getElementById('trackingList');
  listEl.innerHTML = trackingData.map(req => createTrackingCard(req)).join('');

  // Attach event listeners
  attachCardEventListeners();
}

/**
 * Create tracking card HTML
 */
function createTrackingCard(req) {
  const hasOpened = req.first_opened_at !== null;
  const openedRecipients = req.recipients.filter(r => r.opened);
  const unopenedRecipients = req.recipients.filter(r => !r.opened);

  // Header text
  let headerText;
  if (hasOpened) {
    const names = openedRecipients.map(r => r.name || r.email).slice(0, 2);
    if (openedRecipients.length === 1) {
      headerText = `${names[0]} opened your message ${formatRelativeTime(req.first_opened_at)}`;
    } else if (openedRecipients.length === 2) {
      headerText = `${names[0]} and ${names[1]} opened your message ${formatRelativeTime(req.first_opened_at)}`;
    } else {
      headerText = `${names[0]}, ${names[1]} and ${openedRecipients.length - 2} others opened your message ${formatRelativeTime(req.first_opened_at)}`;
    }
  } else {
    headerText = `Sent to ${req.recipients.length} recipient${req.recipients.length > 1 ? 's' : ''}`;
  }

  // Get first tracking event for platform/browser info
  const firstEvent = req.events && req.events[0];
  const userAgent = firstEvent?.user_agent_parsed || {};
  const browser = userAgent.browser || 'Unknown';
  const os = userAgent.os || 'Unknown';
  const device = userAgent.device || 'Desktop';
  const location = firstEvent?.city && firstEvent?.region && firstEvent?.country_code
    ? `${firstEvent.city}, ${firstEvent.region}, ${firstEvent.country_code}`
    : firstEvent?.city && firstEvent?.country_code
      ? `${firstEvent.city}, ${firstEvent.country_code}`
      : 'Unknown location';

  return `
    <div class="tracking-card ${hasOpened ? 'opened' : 'unopened'}" data-tracking-id="${req.tracking_id}">
      <div class="tracking-card-header">
        <div class="tracking-card-main">
          <div class="tracking-header-line">
            <span class="status-icon">${hasOpened ? '✓' : '⏱'}</span>
            ${escapeHTML(headerText)}
          </div>
          <div class="tracking-subject-line">
            <strong>${escapeHTML(req.subject || '(no subject)')}</strong>
            <span class="tracking-sent-time">sent ${formatRelativeTime(req.sent_at)}</span>
          </div>
        </div>
        ${hasOpened ? `
          <div class="tracking-card-actions">
            <button class="tracking-action-btn" data-action="pause">Pause Tracking</button>
          </div>
        ` : ''}
      </div>

      ${hasOpened ? `
        <div class="tracking-card-body">
          <div class="tracking-platform">
            <span class="platform-icon">
              ${device === 'Mobile' ? '📱' : device === 'Tablet' ? '💻' : device === 'Gmail' ? '🌐' : '🖥️'}
            </span>
            <span>${browser} on ${os}</span>
            ${location !== 'Unknown location' ? `<span class="tracking-location">• ${location}</span>` : ''}
          </div>
          <div class="tracking-open-count">
            <span>Opened ${req.open_count} time${req.open_count > 1 ? 's' : ''}</span>
            ${req.open_count > 1 && req.unique_open_count > 1 ?
        `<span class="unique-count">(${req.unique_open_count} unique)</span>` : ''}
            ${req.open_count > 1 ? `
              <button class="tracking-expand-btn" data-action="expand">▼</button>
            ` : ''}
          </div>

          ${req.open_count > 1 ? `
            <div class="tracking-details" style="display: none;">
              <div class="tracking-detail-item">
                <span class="detail-label">First open</span>
                <span class="detail-time">${formatFullTime(req.first_opened_at)}</span>
              </div>
              <div class="tracking-detail-item">
                <span class="detail-label">Most recent</span>
                <span class="detail-time">${formatFullTime(req.last_opened_at)}</span>
              </div>
              ${req.unique_open_count > 1 ? `
                <div class="tracking-detail-item">
                  <span class="detail-label">Unique opens</span>
                  <span class="detail-count">${req.unique_open_count} IP${req.unique_open_count > 1 ? 's' : ''}</span>
                </div>
              ` : ''}
            </div>
          ` : ''}
        </div>
      ` : `
        <div class="tracking-card-body">
          <div class="tracking-unopened-info">
            <span>Not opened yet</span>
            ${unopenedRecipients.length > 0 ? `
              <span class="recipient-list">• ${unopenedRecipients.map(r => r.email).join(', ')}</span>
            ` : ''}
          </div>
        </div>
      `}
    </div>
  `;
}

/**
 * Attach event listeners to cards
 */
function attachCardEventListeners() {
  // Expand/collapse buttons
  document.querySelectorAll('[data-action="expand"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const card = e.target.closest('.tracking-card');
      const details = card.querySelector('.tracking-details');
      const isExpanded = details.style.display !== 'none';

      details.style.display = isExpanded ? 'none' : 'block';
      e.target.textContent = isExpanded ? '▼' : '▲';
    });
  });

  // Pause tracking buttons
  document.querySelectorAll('[data-action="pause"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const card = e.target.closest('.tracking-card');
      const trackingId = card.dataset.trackingId;

      // TODO: Implement pause tracking API call
      console.log('Pause tracking:', trackingId);
      alert('Pause tracking feature coming soon!');
    });
  });
}

/**
 * Format relative time (e.g., "2 hours ago")
 */
function formatRelativeTime(dateString) {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return 'just now';
  if (diffMins < 60) return `${diffMins} minute${diffMins > 1 ? 's' : ''} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
  if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Format full time (e.g., "Nov 25, 10:30 AM")
 */
function formatFullTime(dateString) {
  const date = new Date(dateString);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
  });
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHTML(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
