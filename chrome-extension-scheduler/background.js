// InboxSDK background script handler
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'inboxsdk__injectPageWorld' && sender.tab) {
        if (chrome.scripting) {
            // MV3
            let documentIds;
            let frameIds;
            if (sender.documentId) {
                documentIds = [sender.documentId];
            } else {
                frameIds = [sender.frameId];
            }
            chrome.scripting.executeScript({
                target: { tabId: sender.tab.id, documentIds, frameIds },
                world: 'MAIN',
                files: ['pageWorld.js'],
            });
            sendResponse(true);
        } else {
            sendResponse(false);
        }
    }
});

const API_BASES = ['https://calautobot.com'];

let activeApiBase = API_BASES[0];

// Tracking notification state
const TRACKING_ALARM_NAME = 'trackingPoll';
const TRACKING_POLL_INTERVAL = 0.5; // 30 seconds (in minutes)
let lastPollTime = null;

function buildApiUrl(path, params = {}) {
    const url = new URL(path, activeApiBase);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
            url.searchParams.set(key, value);
        }
    });
    return url;
}

async function getAuthToken(interactive = false) {
    return new Promise((resolve) => {
        chrome.identity.getAuthToken({ interactive }, (token) => {
            if (chrome.runtime.lastError) {
                // Only log error if we were expecting interaction or it's a serious error
                if (interactive) {
                    console.error('getAuthToken error:', chrome.runtime.lastError);
                } else {
                    // Debug log for non-interactive check (benign failure)
                    console.debug('getAuthToken (non-interactive) failed:', chrome.runtime.lastError.message);
                }
                // If the error is "OAuth2 not granted or revoked", we might need to clear cache or force interactive
                resolve({ error: chrome.runtime.lastError.message });
            } else if (!token) {
                resolve({ error: 'No token received' });
            } else {
                resolve({ token });
            }
        });
    });
}

async function fetchFromApi(urlObj, options = {}, token = null) {
    const bases = [activeApiBase, ...API_BASES.filter((b) => b !== activeApiBase)];
    let lastError = null;
    const headers = new Headers(options.headers || {});

    if (token) {
        headers.set('Authorization', `Bearer ${token}`);
    }

    let body = options.body;
    if (body && typeof body === 'object' && !(body instanceof FormData)) {
        headers.set('Content-Type', headers.get('Content-Type') || 'application/json');
        body = JSON.stringify(body);
    }

    // Remove credentials: 'include' as we use token now
    const baseOptions = { ...options, headers, body };

    for (const base of bases) {
        const candidate = new URL(urlObj.pathname + urlObj.search, base);
        try {
            const resp = await fetch(candidate.toString(), baseOptions);
            if (resp.status === 401) {
                // Token might be invalid
                if (token) {
                    chrome.identity.removeCachedAuthToken({ token });
                }
                lastError = new Error('unauthorized');
                continue;
            }
            activeApiBase = base;
            return resp;
        } catch (err) {
            lastError = err;
        }
    }
    throw lastError || new Error('request failed');
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    // Ignore messages that don't look like ours (e.g. InboxSDK internal messages)
    if (!request || !request.action) {
        return false;
    }

    (async () => {
        try {
            const { action, payload } = request;
            switch (action) {
                case 'CHECK_AUTH':
                    sendResponse(await handleCheckAuth(payload.userEmail));
                    break;
                case 'LOGIN':
                    sendResponse(await handleLogin());
                    break;
                case 'FETCH_AVAILABILITY':
                    sendResponse(await handleFetchAvailability(payload.userEmail, payload.count));
                    break;
                case 'FETCH_BOOKING_LINK':
                    sendResponse(await handleFetchBookingLink(payload.userEmail));
                    break;
                case 'SEND_CONTACTS':
                    sendResponse(await handleSendContacts(payload.userEmail, payload.contacts));
                    break;
                case 'LOG_ERROR':
                    sendResponse(handleLogError(payload));
                    break;
                case 'GET_AUTH_TOKEN':
                    // For popup to get auth token
                    const result = await getAuthToken(false);
                    sendResponse(result);
                    break;
                case 'FETCH_TRACKING_REQUESTS':
                    // Fetch tracking requests via background to avoid CORS issues
                    const trackingResult = await handleFetchTrackingRequests(payload.userEmail, payload.since);
                    sendResponse(trackingResult);
                    break;
                case 'MARK_TRACKING_VIEWED':
                    // Mark tracking dashboard as viewed
                    const markViewedResult = await handleMarkTrackingViewed(payload.userEmail);
                    sendResponse(markViewedResult);
                    break;
                case 'CREATE_TRACKING_REQUEST':
                    // Create tracking request via background to avoid CORS issues
                    const createResult = await handleCreateTrackingRequest(payload);
                    sendResponse(createResult);
                    break;
                default:
                    // If it has an action but we don't recognize it, it might be for another part of our app
                    // or we should just log a warning and not throw
                    console.warn(`Unknown action received: ${action}`);
                    sendResponse({ success: false, error: `Unknown action: ${action}` });
            }
        } catch (err) {
            console.error('Background error:', err);
            sendResponse({ success: false, error: err.message });
        }
    })();
    return true; // Keep channel open for async response
});

function handleLogError(payload) {
    const { error, context } = payload || {};
    if (error) {
        console.error(`Extension error [${context || 'unknown'}]:`, error);
    }
    return { success: true };
}

async function handleLogin() {
    // First try interactive login
    let result = await getAuthToken(true);

    // If OAuth2 was revoked, Chrome's cache may be stale
    // The user needs to clear their browser cache or reinstall the extension
    if (result.error && result.error.includes('OAuth2 not granted or revoked')) {
        console.error('OAuth2 revoked - user needs to clear cache or reinstall extension');
        return {
            success: false,
            error: 'Authentication access was revoked. Please try: 1) Sign out of Google in Chrome and sign back in, or 2) Remove and reinstall this extension.'
        };
    }

    if (result.token) {
        return { success: true, authenticated: true };
    }
    return { success: false, error: result.error || 'Login failed' };
}

async function handleCheckAuth(userEmail) {
    let currentToken = null;
    try {
        const { token } = await getAuthToken(false);
        currentToken = token;

        if (!token) {
            return { success: true, authenticated: false };
        }

        // Verify token with backend
        const resp = await fetchFromApi(buildApiUrl('/api/user/info'), {
            method: 'GET'
        }, token);

        if (!resp.ok) {
            return { success: true, authenticated: false };
        }

        const data = await resp.json();

        // Check if authenticated AND email matches (if provided)
        // If userEmail is null (not detected), we accept any valid login
        let isAuthenticated = Boolean(data && data.authenticated);

        if (isAuthenticated && userEmail && data.email) {
            isAuthenticated = data.email.toLowerCase() === userEmail.toLowerCase();
        }

        return { success: true, authenticated: isAuthenticated };
    } catch (err) {
        // Retry logic for stale tokens
        if (err.message === 'unauthorized' && currentToken) {
            // console.log('Auth check unauthorized, retrying with fresh token...');
            // Token is already removed from cache by fetchFromApi if 401

            const freshResult = await getAuthToken(false);
            if (freshResult.token && freshResult.token !== currentToken) {
                try {
                    const resp = await fetchFromApi(buildApiUrl('/api/user/info'), {
                        method: 'GET'
                    }, freshResult.token);

                    if (resp.ok) {
                        const data = await resp.json();
                        let isAuthenticated = Boolean(data && data.authenticated);
                        if (isAuthenticated && userEmail && data.email) {
                            isAuthenticated = data.email.toLowerCase() === userEmail.toLowerCase();
                        }
                        return { success: true, authenticated: isAuthenticated };
                    }
                } catch (retryErr) {
                    console.warn('Retry auth check failed', retryErr);
                }
            }
            // If retry fails, we are definitely not authenticated
            return { success: true, authenticated: false };
        }

        console.error('CalAutobot auth check failed', err);
        return { success: false, error: err.message };
    }
}

async function handleFetchAvailability(userEmail, count) {
    let result = await getAuthToken(false);

    // Handle OAuth2 revoked error
    if (result.error && result.error.includes('OAuth2 not granted or revoked')) {
        // console.log('OAuth2 revoked in fetch availability, user needs to re-authenticate');
        return {
            success: false,
            error: 'Please sign in again. Click the CalAutobot button and try again.'
        };
    }

    if (!result.token) {
        throw new Error(result.error || 'Not authenticated');
    }

    const token = result.token;
    const url = buildApiUrl('/api/extension/availability_text');

    try {
        const resp = await fetchFromApi(url, {}, token);

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));

            if (resp.status === 403 && (err.error === 'SETUP_REQUIRED' || err.error === 'CALENDAR_RECONNECT_REQUIRED') && err.setup_url) {
                chrome.tabs.create({ url: err.setup_url });
                throw new Error('Please reconnect your calendar in the new tab.');
            }

            throw new Error(err.error || 'Unable to fetch availability');
        }
        const data = await resp.json();
        return { success: true, data };
    } catch (err) {
        // If error is "unauthorized", the token might be stale
        // Remove it from cache and try ONE more time with a fresh token
        if (err.message === 'unauthorized' && token) {
            // console.log('Token unauthorized, getting fresh token...');
            await chrome.identity.removeCachedAuthToken({ token });

            // Get a fresh token (non-interactive)
            const freshResult = await getAuthToken(false);
            if (freshResult.token && freshResult.token !== token) {
                // Retry with fresh token
                const url = buildApiUrl('/api/extension/availability_text');
                const resp = await fetchFromApi(url, {}, freshResult.token);

                if (resp.ok) {
                    const data = await resp.json();
                    return { success: true, data };
                }
            }

            // If fresh token didn't work, fail silently
            return { success: false, error: 'Please try again.' };
        }
        throw err;
    }
}

async function handleFetchBookingLink(userEmail) {
    let result = await getAuthToken(false);

    // Handle OAuth2 revoked error
    if (result.error && result.error.includes('OAuth2 not granted or revoked')) {
        // console.log('OAuth2 revoked in fetch booking link, user needs to re-authenticate');
        return {
            success: false,
            error: 'Please sign in again. Click the CalAutobot button and try again.'
        };
    }

    if (!result.token) {
        throw new Error(result.error || 'Not authenticated');
    }

    const token = result.token;

    const url = buildApiUrl('/api/extension/booking_link', {});
    const resp = await fetchFromApi(url, {}, token);

    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || 'Unable to fetch booking link');
    }
    const data = await resp.json();
    return { success: true, data };
}

async function handleSendContacts(userEmail, contacts) {
    if (!contacts || !contacts.length) {
        return { success: true };
    }

    let result = await getAuthToken(false);

    // Handle OAuth2 revoked error - fail silently for contacts sync
    if (result.error && result.error.includes('OAuth2 not granted or revoked')) {
        // console.log('OAuth2 revoked in send contacts, skipping sync');
        return { success: false, error: 'Authentication required' };
    }

    if (!result.token) {
        return { success: false, error: result.error || 'Not authenticated' };
    }

    const token = result.token;

    try {
        await fetchFromApi(buildApiUrl('/api/extension/contacts', {}), {
            method: 'POST',
            body: { contacts }
        }, token);
        return { success: true };
    } catch (err) {
        console.warn('Failed to sync contacts', err);
        return { success: false, error: err.message };
    }
}

async function handleFetchTrackingRequests(userEmail, since = null) {
    let result = await getAuthToken(false);

    if (!result.token) {
        return { success: false, error: result.error || 'Not authenticated' };
    }

    const token = result.token;

    try {
        const params = { user_email: userEmail };
        if (since) {
            params.since = since;
            // console.log('Background: Fetching tracking requests WITH since parameter:', since);
        } else {
            // console.log('Background: Fetching tracking requests WITHOUT since parameter (full load)');
        }

        const response = await fetchFromApi(
            buildApiUrl('/api/tracking/requests', params),
            { method: 'GET' },
            token
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        // console.log('Background: Fetched tracking requests:', data);
        return { success: true, data: data };
    } catch (err) {
        console.error('Failed to fetch tracking requests', err);
        return { success: false, error: err.message };
    }
}

async function handleMarkTrackingViewed(userEmail) {
    let result = await getAuthToken(false);

    if (!result.token) {
        return { success: false, error: result.error || 'Not authenticated' };
    }

    const token = result.token;

    try {
        const response = await fetchFromApi(
            buildApiUrl('/api/tracking/mark-viewed', {}),
            {
                method: 'POST',
                body: { user_email: userEmail }
            },
            token
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        // console.log('Background: Marked tracking as viewed:', data);
        return { success: true, data: data };
    } catch (err) {
        console.error('Failed to mark tracking as viewed', err);
        return { success: false, error: err.message };
    }
}

async function handleCreateTrackingRequest(payload) {
    let result = await getAuthToken(false);

    if (!result.token) {
        return { success: false, error: result.error || 'Not authenticated' };
    }

    const token = result.token;

    try {
        const response = await fetchFromApi(
            buildApiUrl('/api/tracking/requests', {}),
            {
                method: 'POST',
                body: {
                    user_email: payload.userEmail,
                    tracking_id: payload.trackingId,
                    subject: payload.subject,
                    recipients: payload.recipients,
                    cc_recipients: payload.ccRecipients || [],
                    bcc_recipients: payload.bccRecipients || [],
                    gmail_message_id: payload.gmailMessageId || null,
                    gmail_thread_id: payload.gmailThreadId || null,
                }
            },
            token
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        // console.log('Background: Tracking requests fetched - count:', data.requests?.length || 0);
        // console.log('Background: Full response:', data);
        return { success: true, data: data };
    } catch (err) {
        console.error('Failed to create tracking request', err);
        return { success: false, error: err.message };
    }
}

// ===== TRACKING NOTIFICATION SYSTEM =====

/**
 * Initialize tracking notifications on extension startup
 */
chrome.runtime.onStartup.addListener(() => {
    // console.log('CalAutobot: Extension started, initializing tracking notifications');
    initializeTrackingPolling();
    initializeLastDashboardCheck();
});

chrome.runtime.onInstalled.addListener(() => {
    // console.log('CalAutobot: Extension installed/updated, initializing tracking notifications');
    initializeTrackingPolling();
    initializeLastDashboardCheck();

    // Trigger immediate poll for testing
    setTimeout(() => {
        // console.log('CalAutobot: Running initial tracking poll...');
        pollTrackingUpdates();
    }, 2000);

    // console.log('CalAutobot: Extension installed/updated, tracking system ready');
});

/**
 * Initialize lastDashboardCheck if not set
 */
async function initializeLastDashboardCheck() {
    const storage = await chrome.storage.local.get(['lastDashboardCheck']);
    if (!storage.lastDashboardCheck) {
        // Set to now so we don't show badge for old opens
        await chrome.storage.local.set({
            lastDashboardCheck: new Date().toISOString(),
            unreadTrackingCount: 0
        });
        // console.log('CalAutobot: Initialized lastDashboardCheck');
    }
}

/**
 * Set up chrome.alarms for periodic polling
 */
async function initializeTrackingPolling() {
    // Clear any existing alarm
    await chrome.alarms.clear(TRACKING_ALARM_NAME);

    // Create new alarm for 30-second intervals
    chrome.alarms.create(TRACKING_ALARM_NAME, {
        delayInMinutes: TRACKING_POLL_INTERVAL,
        periodInMinutes: TRACKING_POLL_INTERVAL,
    });

    // Store initialization time
    await chrome.storage.local.set({
        trackingPollInitialized: new Date().toISOString()
    });

    // console.log('CalAutobot: Tracking polling initialized (30s intervals)');
}

/**
 * Handle alarm events
 */
chrome.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name === TRACKING_ALARM_NAME) {
        await pollTrackingUpdates();
    }
});

/**
 * Poll for new tracking opens
 */
async function pollTrackingUpdates() {
    try {
        // console.log('CalAutobot: Polling for tracking updates...');

        // Check if user is authenticated
        let result = await getAuthToken(false);
        if (!result.token) {
            // console.log('CalAutobot: Not authenticated, skipping poll');
            return;
        }

        const token = result.token;

        // Get lastTrackingPoll to fetch only new data since last poll (for efficiency)
        const storage = await chrome.storage.local.get(['lastDashboardCheck', 'lastTrackingPoll']);
        const lastTrackingPoll = storage.lastTrackingPoll;

        // Build URL with "since" parameter based on last poll time (for efficient polling)
        // This will only fetch tracking requests with new opens since last poll
        const params = {};
        if (lastTrackingPoll) {
            params.since = lastTrackingPoll;
            // console.log('CalAutobot: Polling for updates since:', lastTrackingPoll);
        } else {
            // console.log('CalAutobot: First poll - fetching all recent tracking requests');
        }

        const url = buildApiUrl('/api/tracking/requests', params);
        // console.log('CalAutobot: Fetching tracking data from:', url.toString());
        const resp = await fetchFromApi(url, {}, token);

        if (!resp.ok) {
            console.warn('CalAutobot: Failed to poll tracking updates', resp.status);
            return;
        }

        const data = await resp.json();
        // console.log('CalAutobot: Received tracking data:', {
        //     success: data.success,
        //     new_opens_count: data.new_opens_count,
        //     tracking_last_viewed_at: data.tracking_last_viewed_at,
        //     requests_count: data.requests?.length
        // });

        // Count unread opens (opens since last dashboard check)
        const unreadCount = data.new_opens_count || 0;
        // console.log('CalAutobot: Unread count for badge:', unreadCount);

        // Debug: Show which emails have been opened
        if (data.requests && data.requests.length > 0) {
            // console.log('CalAutobot: Recent tracking requests:');
            data.requests.slice(0, 5).forEach(req => {
                // console.log(`  - "${req.subject}" | Sent: ${req.sent_at} | Last opened: ${req.last_opened_at || 'Never'} | Opens: ${req.open_count || 0}`);
            });
        }

        // Update cache with fresh data
        if (lastTrackingPoll && data.requests && data.requests.length > 0) {
            // Incremental update: merge new data with existing cache
            const existingCache = await chrome.storage.local.get(['cachedTrackingData']);
            if (existingCache.cachedTrackingData && existingCache.cachedTrackingData.requests) {
                // Create a map of existing requests by ID
                const existingMap = new Map();
                existingCache.cachedTrackingData.requests.forEach(req => {
                    existingMap.set(req.id, req);
                });

                // Update or add new requests
                data.requests.forEach(req => {
                    existingMap.set(req.id, req);
                });

                // Convert back to array and sort by sent_at
                const mergedRequests = Array.from(existingMap.values())
                    .sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at))
                    .slice(0, 50); // Keep only 50 most recent

                data.requests = mergedRequests;
                // console.log('CalAutobot: Merged incremental updates with cache - total requests:', mergedRequests.length);
            }

            await chrome.storage.local.set({ cachedTrackingData: data });
            // console.log('CalAutobot: Cache updated with tracking_last_viewed_at:', data.tracking_last_viewed_at);
        } else if (!lastTrackingPoll) {
            // First poll - full data load, update cache
            await chrome.storage.local.set({ cachedTrackingData: data });
            // console.log('CalAutobot: Cache updated with initial data - requests:', data.requests?.length || 0);
        } else {
            // Incremental poll returned no new data - DON'T update cache
            // Just update the tracking_last_viewed_at timestamp in existing cache
            const existingCache = await chrome.storage.local.get(['cachedTrackingData']);
            if (existingCache.cachedTrackingData) {
                existingCache.cachedTrackingData.tracking_last_viewed_at = data.tracking_last_viewed_at;
                existingCache.cachedTrackingData.new_opens_count = data.new_opens_count;
                await chrome.storage.local.set({ cachedTrackingData: existingCache.cachedTrackingData });
                // console.log('CalAutobot: No new data in poll, preserved cache with', existingCache.cachedTrackingData.requests?.length || 0, 'requests');
            }
        }

        // Update lastTrackingPoll timestamp AFTER successful data fetch
        // Use tracking_last_viewed_at from response (server timestamp) instead of client timestamp
        // This ensures consistency with backend filtering logic
        if (data.success && data.tracking_last_viewed_at) {
            await chrome.storage.local.set({ lastTrackingPoll: data.tracking_last_viewed_at });
            // console.log('CalAutobot: Updated lastTrackingPoll to:', data.tracking_last_viewed_at);
        } else if (!lastTrackingPoll) {
            // First poll returned no data - don't set timestamp yet, keep fetching all data
            // console.log('CalAutobot: First poll returned no data, will retry full fetch on next poll');
        }

        if (data.success && unreadCount > 0) {
            // console.log(`CalAutobot: Found ${unreadCount} new opens, updating badge...`);

            // Store unread count
            await chrome.storage.local.set({ unreadTrackingCount: unreadCount });

            // Send message to content script to update Gmail button badge
            try {
                const tabs = await chrome.tabs.query({ url: 'https://mail.google.com/*' });
                for (const tab of tabs) {
                    chrome.tabs.sendMessage(tab.id, {
                        action: 'UPDATE_TRACKING_BADGE',
                        count: unreadCount
                    }).catch(() => {
                        // Ignore errors if content script not loaded
                    });
                }
            } catch (err) {
                console.debug('Could not send badge update to content script:', err);
            }

            // Show notifications for new opens
            await showTrackingNotifications(data.requests);
        } else if (data.success && unreadCount === 0) {
            // Clear badges if no new opens
            await chrome.storage.local.set({ unreadTrackingCount: 0 });

            // Send message to content script to clear Gmail button badge
            try {
                const tabs = await chrome.tabs.query({ url: 'https://mail.google.com/*' });
                for (const tab of tabs) {
                    chrome.tabs.sendMessage(tab.id, {
                        action: 'UPDATE_TRACKING_BADGE',
                        count: 0
                    }).catch(() => { });
                }
            } catch (err) {
                console.debug('Could not send badge clear to content script:', err);
            }
        }

    } catch (err) {
        console.error('CalAutobot: Error polling tracking updates', err);
    }
}

/**
 * Update extension badge with new opens count
 */
async function updateBadge(count) {
    if (count > 0) {
        const badgeText = count > 99 ? '99+' : count.toString();
        await chrome.action.setBadgeText({ text: badgeText });
        await chrome.action.setBadgeBackgroundColor({ color: '#1a73e8' });
    } else {
        await chrome.action.setBadgeText({ text: '' });
    }
}

/**
 * Show desktop notifications for newly opened emails
 */
async function showTrackingNotifications(requests) {
    // Get notification preferences
    const { notificationsEnabled = true } = await chrome.storage.local.get(['notificationsEnabled']);

    if (!notificationsEnabled) {
        return;
    }

    // Get stored notification state to avoid duplicates
    const { notifiedOpens = {} } = await chrome.storage.local.get(['notifiedOpens']);

    for (const request of requests) {
        // Skip if we've already notified about this tracking request's opens
        if (notifiedOpens[request.tracking_id]) {
            continue;
        }

        // Check if email was opened
        if (request.open_count > 0 && request.first_opened_at) {
            // Get list of recipients who opened
            const openedRecipients = request.recipients
                .filter(r => r.opened)
                .map(r => r.name || r.email)
                .slice(0, 3); // Limit to 3 names

            let notificationMessage = '';
            if (openedRecipients.length === 1) {
                notificationMessage = `${openedRecipients[0]} opened your email`;
            } else if (openedRecipients.length === 2) {
                notificationMessage = `${openedRecipients[0]} and ${openedRecipients[1]} opened your email`;
            } else if (openedRecipients.length > 2) {
                notificationMessage = `${openedRecipients[0]}, ${openedRecipients[1]} and ${openedRecipients.length - 2} others opened your email`;
            }

            // Create notification
            await chrome.notifications.create(`tracking-${request.tracking_id}`, {
                type: 'basic',
                iconUrl: 'icons/icon128.png',
                title: 'Email Opened',
                message: notificationMessage,
                contextMessage: request.subject || '(no subject)',
                priority: 1,
                requireInteraction: false,
            });

            // Mark as notified
            notifiedOpens[request.tracking_id] = new Date().toISOString();
        }
    }

    // Save updated notification state
    await chrome.storage.local.set({ notifiedOpens });
}

/**
 * Handle notification clicks
 */
chrome.notifications.onClicked.addListener((notificationId) => {
    if (notificationId.startsWith('tracking-')) {
        // Open Gmail when notification is clicked
        chrome.tabs.create({ url: 'https://mail.google.com' });
        chrome.notifications.clear(notificationId);
    }
});
