// Calendar AI Chrome Extension - Background Service Worker

class CalendarAIBackground {
  constructor() {
    this.init();
  }

  init() {
    // Handle extension installation
    chrome.runtime.onInstalled.addListener((details) => {
      if (details.reason === 'install') {
        console.log('Calendar AI extension installed');
        this.showWelcomeNotification();
      }
    });

    // Handle auth flow completion
    chrome.identity.onSignInChanged.addListener((account, signedIn) => {
      console.log('Auth state changed:', { account, signedIn });
    });

    // Handle messages from popup or content scripts
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      this.handleMessage(request, sender, sendResponse);
      return true; // Keep message channel open for async response
    });

    // Handle context menu - extract events from selected text
    this.setupContextMenu();
  }

  async handleMessage(request, sender, sendResponse) {
    try {
      switch (request.action) {
        case 'capture_screenshot':
          const screenshot = await this.captureScreenshot();
          sendResponse({ success: true, screenshot });
          break;

        case 'get_selected_text':
          const selectedText = await this.getSelectedText();
          sendResponse({ success: true, text: selectedText });
          break;

        case 'check_auth':
          const authStatus = await this.checkAuthStatus();
          sendResponse({ success: true, authStatus });
          break;

        default:
          sendResponse({ success: false, error: 'Unknown action' });
      }
    } catch (error) {
      console.error('Background script error:', error);
      sendResponse({ success: false, error: error.message });
    }
  }

  async captureScreenshot() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: 'png',
        quality: 90
      });
      return dataUrl;
    } catch (error) {
      console.error('Screenshot capture error:', error);
      throw error;
    }
  }

  async getSelectedText() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        function: () => {
          const selection = window.getSelection();
          return selection.toString().trim();
        }
      });

      return results[0]?.result || '';
    } catch (error) {
      console.error('Get selected text error:', error);
      throw error;
    }
  }

  async checkAuthStatus() {
    try {
      // Use same SessionManager logic as popup
      const result = await chrome.storage.local.get(['session']);
      const session = result.session;

      if (session && session.isLoggedIn) {
        return {
          isAuthenticated: true,
          user: {
            email: session.email,
            username: session.username
          }
        };
      }

      return { isAuthenticated: false, user: null };
    } catch (error) {
      console.error('Auth status check error:', error);
      return { isAuthenticated: false, user: null };
    }
  }

  setupContextMenu() {
    // Remove any existing context menus first to prevent duplicates
    chrome.contextMenus.removeAll(() => {
      // Create context menu for selected text
      chrome.contextMenus.create({
        id: 'extract-events-text',
        title: 'Extract Calendar Events',
        contexts: ['selection']
      });
    });

    // Handle context menu clicks
    chrome.contextMenus.onClicked.addListener((info, tab) => {
      if (info.menuItemId === 'extract-events-text') {
        this.handleContextMenuClick(info, tab);
      }
    });
  }

  async handleContextMenuClick(info, tab) {
    try {
      // Check if user is authenticated
      const authStatus = await this.checkAuthStatus();

      if (!authStatus.isAuthenticated) {
        // Show notification to sign in - use console instead to avoid permission issues
        console.log('Calendar AI: Please sign in first by clicking the extension icon');
        return;
      }

      // Process the selected text
      const selectedText = info.selectionText;
      await this.processTextInBackground(selectedText, authStatus.user);

    } catch (error) {
      console.error('Context menu error:', error);
    }
  }

  async processTextInBackground(text, user) {
    try {
      // Log processing instead of notification to avoid permission issues
      console.log('Calendar AI: Processing selected text...');

      // Get session (reuse SessionManager approach)
      const result = await chrome.storage.local.get(['session']);
      const authToken = 'session-token'; // Use same token as popup

      // Use same API base URL logic as popup.js
      const apiBaseUrl = 'https://calautobot.com';

      // Send to API endpoint with correct format
      const response = await fetch(`${apiBaseUrl}/api/extension/process`, {
        method: 'POST',
        credentials: 'include', // Use cookies for auth
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({
          text: text,
          user_email: user.email,
          source: 'Chrome Extension Context Menu'
        })
      });

      const responseData = await response.json();

      if (response.ok) {
        const totalEvents = responseData.total_events_extracted || 0;
        const syncedEvents = responseData.total_events_synced || 0;

        console.log(`Calendar AI - Success! Extracted ${totalEvents} events, ${syncedEvents} synced to calendar`);
      } else {
        console.log('Calendar AI - Error: Failed to process text. Please try again.');
      }
    } catch (error) {
      console.error('Background processing error:', error);
      console.log('Calendar AI - Error: Failed to process text. Please check your connection.');
    }
  }

  showWelcomeNotification() {
    // Disable welcome notification to avoid permission issues
    console.log('Calendar AI extension installed successfully');
  }
}

// Initialize background script
new CalendarAIBackground();