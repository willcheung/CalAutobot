const API_BASES = ['https://2df5bf01-2bac-4ced-b741-7ba31655935b-00-1qhgrsiodr7l4.kirk.replit.dev'];

let activeApiBase = API_BASES[0];

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
                console.error('getAuthToken error:', chrome.runtime.lastError);
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
    handleMessage(request).then(sendResponse).catch((err) => {
        sendResponse({ success: false, error: err.message });
    });
    return true; // Keep channel open for async response
});

async function handleMessage(request) {
    const { action, payload } = request;
    const { userEmail } = payload || {};

    switch (action) {
        case 'CHECK_AUTH':
            return handleCheckAuth(userEmail);
        case 'LOGIN':
            return handleLogin();
        case 'LOG_ERROR':
            return handleLogError(payload);
        case 'FETCH_AVAILABILITY':
            return handleFetchAvailability(userEmail, payload.count);
        case 'FETCH_BOOKING_LINK':
            return handleFetchBookingLink(userEmail);
        case 'SEND_CONTACTS':
            return handleSendContacts(userEmail, payload.contacts);
        default:
            throw new Error(`Unknown action: ${action}`);
    }
}

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
    try {
        const { token } = await getAuthToken(false);

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
        console.error('CalAutobot auth check failed', err);
        return { success: false, error: err.message };
    }
}

async function handleFetchAvailability(userEmail, count) {
    const { token, error } = await getAuthToken(false);
    if (!token) throw new Error(error || 'Not authenticated');

    const url = buildApiUrl('/api/extension/availability_text', { count: count || '3' });
    const resp = await fetchFromApi(url, {}, token);

    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));

        if (resp.status === 403 && err.error === 'SETUP_REQUIRED' && err.setup_url) {
            chrome.tabs.create({ url: err.setup_url });
            throw new Error('Please complete setup in the new tab.');
        }

        throw new Error(err.error || 'Unable to fetch availability');
    }
    const data = await resp.json();
    return { success: true, data };
}

async function handleFetchBookingLink(userEmail) {
    const { token, error } = await getAuthToken(false);
    if (!token) throw new Error(error || 'Not authenticated');

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

    const { token, error } = await getAuthToken(false);
    if (!token) return { success: false, error: error || 'Not authenticated' };

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
