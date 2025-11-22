const API_BASES = ['https://calautobot.com', 'https://www.calautobot.com'];
const AUTH_TOKEN = 'session-token';

let activeApiBase = API_BASES[0];

function buildApiUrl(path, params = {}, userEmail = null) {
    const url = new URL(path, activeApiBase);
    if (userEmail) {
        url.searchParams.set('user_email', userEmail);
    }
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
            url.searchParams.set(key, value);
        }
    });
    return url;
}

async function fetchFromApi(urlObj, options = {}) {
    const bases = [activeApiBase, ...API_BASES.filter((b) => b !== activeApiBase)];
    let lastError = null;
    const headers = new Headers(options.headers || {});
    headers.set('Authorization', `Bearer ${AUTH_TOKEN}`);
    let body = options.body;
    if (body && typeof body === 'object' && !(body instanceof FormData)) {
        headers.set('Content-Type', headers.get('Content-Type') || 'application/json');
        body = JSON.stringify(body);
    }
    const baseOptions = { credentials: 'include', ...options, headers, body };

    for (const base of bases) {
        const candidate = new URL(urlObj.pathname + urlObj.search, base);
        try {
            const resp = await fetch(candidate.toString(), baseOptions);
            if (resp.status === 401) {
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

async function handleCheckAuth(userEmail) {
    try {
        // Use the standard user info endpoint (same as event extractor)
        const resp = await fetchFromApi(buildApiUrl('/api/user/info'), {
            method: 'GET'
        });

        if (!resp.ok) {
            throw new Error('auth check failed');
        }

        const data = await resp.json();

        // Check if authenticated AND email matches
        const isAuthenticated = Boolean(
            data &&
            data.authenticated &&
            data.email &&
            userEmail &&
            data.email.toLowerCase() === userEmail.toLowerCase()
        );

        return { success: true, authenticated: isAuthenticated };
    } catch (err) {
        console.error('CalAutobot auth check failed', err);
        return { success: false, error: err.message };
    }
}

async function handleFetchAvailability(userEmail, count) {
    const url = buildApiUrl('/api/extension/availability_text', { count: count || '3' }, userEmail);
    const resp = await fetchFromApi(url);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || 'Unable to fetch availability');
    }
    const data = await resp.json();
    return { success: true, data };
}

async function handleFetchBookingLink(userEmail) {
    const url = buildApiUrl('/api/extension/booking_link', {}, userEmail);
    const resp = await fetchFromApi(url);
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
    try {
        await fetchFromApi(buildApiUrl('/api/extension/contacts', {}, userEmail), {
            method: 'POST',
            body: { contacts }
        });
        return { success: true };
    } catch (err) {
        console.warn('Failed to sync contacts', err);
        return { success: false, error: err.message };
    }
}
