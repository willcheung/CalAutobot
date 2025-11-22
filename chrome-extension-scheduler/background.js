const API_BASES = ['https://calautobot.com', 'https://www.calautobot.com'];

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
            if (chrome.runtime.lastError || !token) {
                resolve(null);
            } else {
                resolve(token);
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

async function handleLogin() {
    const token = await getAuthToken(true);
    if (token) {
        return { success: true, authenticated: true };
    }
    return { success: false, error: 'Login failed' };
}

async function handleCheckAuth(userEmail) {
    try {
        const token = await getAuthToken(false);

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
    const token = await getAuthToken(false);
    if (!token) throw new Error('Not authenticated');

    const url = buildApiUrl('/api/extension/availability_text', { count: count || '3' });
    const resp = await fetchFromApi(url, {}, token);

    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || 'Unable to fetch availability');
    }
    const data = await resp.json();
    return { success: true, data };
}

async function handleFetchBookingLink(userEmail) {
    const token = await getAuthToken(false);
    if (!token) throw new Error('Not authenticated');

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

    const token = await getAuthToken(false);
    if (!token) return { success: false, error: 'Not authenticated' };

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
