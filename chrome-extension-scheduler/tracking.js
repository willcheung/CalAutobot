/**
 * Email Tracking Module for CalAutobot
 * Handles pixel injection, tracking state, and API communication
 */

const API_BASE_URL = 'http://localhost:5001'; // Will fallback to production in background.js

// --- Tracking ID Generation ---

/**
 * Generate a unique 64-character hex tracking ID
 * @returns {string} Tracking ID
 */
function generateTrackingId() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, byte => byte.toString(16).padStart(2, '0')).join('');
}

// --- Tracking State Management ---

/**
 * Get tracking enabled preference from storage
 * @returns {Promise<boolean>}
 */
async function isTrackingEnabled() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['trackingEnabled'], (result) => {
      // Default to true if not set
      resolve(result.trackingEnabled !== false);
    });
  });
}

/**
 * Set tracking enabled preference
 * @param {boolean} enabled
 * @returns {Promise<void>}
 */
async function setTrackingEnabled(enabled) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ trackingEnabled: enabled }, resolve);
  });
}

/**
 * Store tracking metadata for a compose session
 * @param {string} composeId - Unique ID for this compose window
 * @param {object} metadata - { trackingId, enabled }
 */
async function storeComposeTracking(composeId, metadata) {
  return new Promise((resolve) => {
    chrome.storage.local.get(['composeTracking'], (result) => {
      const tracking = result.composeTracking || {};
      tracking[composeId] = metadata;
      chrome.storage.local.set({ composeTracking: tracking }, resolve);
    });
  });
}

/**
 * Get tracking metadata for a compose session
 * @param {string} composeId
 * @returns {Promise<object|null>}
 */
async function getComposeTracking(composeId) {
  return new Promise((resolve) => {
    chrome.storage.local.get(['composeTracking'], (result) => {
      const tracking = result.composeTracking || {};
      resolve(tracking[composeId] || null);
    });
  });
}

/**
 * Remove compose tracking metadata after send
 * @param {string} composeId
 */
async function clearComposeTracking(composeId) {
  return new Promise((resolve) => {
    chrome.storage.local.get(['composeTracking'], (result) => {
      const tracking = result.composeTracking || {};
      delete tracking[composeId];
      chrome.storage.local.set({ composeTracking: tracking }, resolve);
    });
  });
}

// --- Tracking Pixel Generation ---

/**
 * Generate tracking pixel HTML
 * @param {string} trackingId
 * @returns {string} HTML for tracking pixel
 */
function generateTrackingPixel(trackingId) {
  const pixelUrl = `${API_BASE_URL}/api/tracking/pixel/${trackingId}`;
  return `<img src="${pixelUrl}" width="1" height="1" style="display:none" alt="" />`;
}

/**
 * Inject tracking pixel into email body HTML
 * @param {string} bodyHtml - Original email body HTML
 * @param {string} trackingId - Tracking ID
 * @returns {string} Modified HTML with tracking pixel
 */
function injectTrackingPixel(bodyHtml, trackingId) {
  const pixel = generateTrackingPixel(trackingId);

  // Try to inject before closing body tag, or append to end
  if (bodyHtml.includes('</body>')) {
    return bodyHtml.replace('</body>', `${pixel}</body>`);
  } else if (bodyHtml.includes('</html>')) {
    return bodyHtml.replace('</html>', `${pixel}</html>`);
  } else {
    // Just append to end
    return bodyHtml + pixel;
  }
}

// --- API Communication ---

/**
 * Create tracking request via API
 * @param {object} params
 * @param {string} params.trackingId
 * @param {string} params.subject
 * @param {Array} params.recipients - [{email, name}]
 * @param {Array} params.ccRecipients
 * @param {Array} params.bccRecipients
 * @param {string} params.gmailMessageId
 * @param {string} params.gmailThreadId
 * @param {string} params.userEmail - For authentication
 * @returns {Promise<object>} API response
 */
async function createTrackingRequest(params) {
  const response = await fetch(`${API_BASE_URL}/api/tracking/requests`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      user_email: params.userEmail,
      tracking_id: params.trackingId,
      subject: params.subject,
      recipients: params.recipients,
      cc_recipients: params.ccRecipients || [],
      bcc_recipients: params.bccRecipients || [],
      gmail_message_id: params.gmailMessageId || null,
      gmail_thread_id: params.gmailThreadId || null,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Unknown error' }));
    throw new Error(error.error || 'Failed to create tracking request');
  }

  return response.json();
}

/**
 * Fetch tracking requests from API
 * @param {string} userEmail
 * @param {Date} since - Optional, fetch only new opens since this timestamp
 * @returns {Promise<object>} { requests: [...], new_opens_count: N }
 */
async function fetchTrackingRequests(userEmail, since = null) {
  const params = new URLSearchParams({ user_email: userEmail });
  if (since) {
    params.append('since', since.toISOString());
  }

  const response = await fetch(`${API_BASE_URL}/api/tracking/requests?${params}`);

  if (!response.ok) {
    throw new Error('Failed to fetch tracking requests');
  }

  return response.json();
}

/**
 * Fetch contact engagement data
 * @param {number} contactId
 * @param {string} userEmail
 * @returns {Promise<object>}
 */
async function fetchContactEngagement(contactId, userEmail) {
  const params = new URLSearchParams({ user_email: userEmail });
  const response = await fetch(
    `${API_BASE_URL}/api/contacts/${contactId}/engagement?${params}`
  );

  if (!response.ok) {
    throw new Error('Failed to fetch contact engagement');
  }

  return response.json();
}

// Export functions for use in content.js
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    generateTrackingId,
    isTrackingEnabled,
    setTrackingEnabled,
    storeComposeTracking,
    getComposeTracking,
    clearComposeTracking,
    generateTrackingPixel,
    injectTrackingPixel,
    createTrackingRequest,
    fetchTrackingRequests,
    fetchContactEngagement,
  };
}
