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

const API_BASES = ['http://localhost:5001', 'https://2df5bf01-2bac-4ced-b741-7ba31655935b-00-1qhgrsiodr7l4.kirk.replit.dev'];

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

    // If it fails with "OAuth2 not granted or revoked", it means the user revoked access
    // but Chrome's internal state is confused or refusing to prompt.
    // We can force a prompt using launchWebAuthFlow with the same client ID.
    if (result.error && result.error.includes('OAuth2 not granted or revoked')) {
        console.log('OAuth2 revoked, attempting force re-auth via launchWebAuthFlow');
        try {
            const manifest = chrome.runtime.getManifest();
            const clientId = manifest.oauth2.client_id;
            const scopes = manifest.oauth2.scopes.join(' ');
            const redirectUri = `https://${chrome.runtime.id}.chromiumapp.org/`;

            const authUrl = new URL('https://accounts.google.com/o/oauth2/auth');
            authUrl.searchParams.set('client_id', clientId);
            authUrl.searchParams.set('response_type', 'token');
            authUrl.searchParams.set('redirect_uri', redirectUri);
            authUrl.searchParams.set('scope', scopes);
            // Force prompt to ensure user can re-grant access
            authUrl.searchParams.set('prompt', 'consent');

            const redirectUrl = await new Promise((resolve, reject) => {
                chrome.identity.launchWebAuthFlow({
                    url: authUrl.toString(),
                    interactive: true
                }, (responseUrl) => {
                    if (chrome.runtime.lastError) {
                        reject(chrome.runtime.lastError);
                    } else {
                        resolve(responseUrl);
                    }
                });
            });

            // If successful, we don't actually need to parse the token here because
            // launchWebAuthFlow will have refreshed the session state.
            // We can just try getAuthToken again and it should work now.
            // Or we can parse it if we really want to be sure.

            // Let's try getAuthToken again to ensure it's cached properly by Chrome
            result = await getAuthToken(true);

        } catch (err) {
            console.error('Force re-auth failed', err);
            return { success: false, error: err.message || 'Re-authentication failed' };
        }
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
            console.log('Auth check unauthorized, retrying with fresh token...');
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
        console.log('OAuth2 revoked in fetch availability, user needs to re-authenticate');
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
            console.log('Token unauthorized, getting fresh token...');
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
        console.log('OAuth2 revoked in fetch booking link, user needs to re-authenticate');
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
        console.log('OAuth2 revoked in send contacts, skipping sync');
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

// ===== TRACKING NOTIFICATION SYSTEM =====

/**
 * Initialize tracking notifications on extension startup
 */
chrome.runtime.onStartup.addListener(() => {
    console.log('CalAutobot: Extension started, initializing tracking notifications');
    initializeTrackingPolling();
});

chrome.runtime.onInstalled.addListener(() => {
    console.log('CalAutobot: Extension installed/updated, initializing tracking notifications');
    initializeTrackingPolling();
});

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

    console.log('CalAutobot: Tracking polling initialized (30s intervals)');
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
        // Check if user is authenticated
        let result = await getAuthToken(false);
        if (!result.token) {
            // Not authenticated, skip polling
            return;
        }

        const token = result.token;

        // Build URL with "since" parameter if we have a lastPollTime
        const params = {};
        if (lastPollTime) {
            params.since = lastPollTime;
        }

        const url = buildApiUrl('/api/tracking/requests', params);
        const resp = await fetchFromApi(url, {}, token);

        if (!resp.ok) {
            console.warn('CalAutobot: Failed to poll tracking updates', resp.status);
            return;
        }

        const data = await resp.json();

        if (data.success && data.new_opens_count > 0) {
            // Update badge
            await updateBadge(data.new_opens_count);

            // Show notifications for new opens
            await showTrackingNotifications(data.requests);
        } else if (data.success && data.new_opens_count === 0) {
            // Clear badge if no new opens
            await chrome.action.setBadgeText({ text: '' });
        }

        // Update last poll time
        lastPollTime = new Date().toISOString();
        await chrome.storage.local.set({ lastTrackingPoll: lastPollTime });

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
