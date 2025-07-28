// Calendar AI Chrome Extension - Popup Script
class CalendarAIPopup {
  constructor() {
    this.apiBaseUrl = 'https://calautobot.com';
    this.user = null;
    this.init();
  }

  async init() {
    await this.checkAuthStatus();
    this.setupEventListeners();
    this.updateUI();
  }

  async checkAuthStatus() {
    try {
      // Check if user is stored in extension storage
      const result = await chrome.storage.local.get(['user', 'authToken']);
      if (result.user && result.authToken) {
        this.user = result.user;
        this.authToken = result.authToken;
      }
    } catch (error) {
      console.error('Error checking auth status:', error);
    }
  }

  setupEventListeners() {
    // Authentication
    document.getElementById('authBtn').addEventListener('click', () => this.handleAuth());
    
    // Text processing
    document.getElementById('processTextBtn').addEventListener('click', () => this.processText());
    
    // Screenshot
    document.getElementById('screenshotBtn').addEventListener('click', () => this.takeScreenshot());
    
    // Quick actions
    document.getElementById('forwardEmailBtn').addEventListener('click', () => this.showForwardEmailInfo());
    document.getElementById('dashboardBtn').addEventListener('click', () => this.openDashboard());
  }

  updateUI() {
    const authStatus = document.getElementById('authStatus');
    const authBtn = document.getElementById('authBtn');
    const processTextBtn = document.getElementById('processTextBtn');
    const screenshotBtn = document.getElementById('screenshotBtn');

    if (this.user) {
      authStatus.textContent = `Signed in as ${this.user.email}`;
      authStatus.className = 'auth-status authenticated';
      authBtn.textContent = 'Sign Out';
      processTextBtn.disabled = false;
      screenshotBtn.disabled = false;
    } else {
      authStatus.textContent = 'Not signed in';
      authStatus.className = 'auth-status unauthenticated';
      authBtn.textContent = 'Sign in with Google';
      processTextBtn.disabled = true;
      screenshotBtn.disabled = true;
    }
  }

  async handleAuth() {
    if (this.user) {
      // Sign out
      await chrome.storage.local.clear();
      this.user = null;
      this.authToken = null;
      this.updateUI();
      this.showStatus('Signed out successfully', 'success');
    } else {
      // Sign in
      await this.signIn();
    }
  }

  async signIn() {
    try {
      this.showStatus('Signing in...', 'processing');
      
      // Simplified sign in - redirect to Calendar AI web app for OAuth
      const authUrl = `${this.apiBaseUrl}/auth/google?extension=true`;
      
      // Open auth in new tab
      chrome.tabs.create({ url: authUrl }, (tab) => {
        // For now, user needs to complete auth on web and come back
        this.showStatus('Complete sign-in in the new tab, then return here', 'processing');
        
        // Simple demo authentication for testing
        setTimeout(() => {
          // Mock user for demo purposes
          const demoUser = {
            email: 'demo@example.com',
            name: 'Demo User'
          };
          
          this.user = demoUser;
          this.authToken = 'demo-token';
          
          chrome.storage.local.set({
            user: demoUser,
            authToken: 'demo-token'
          });
          
          this.updateUI();
          this.showStatus('Demo mode active - ready to test!', 'success');
        }, 3000);
      });
      
    } catch (error) {
      console.error('Authentication error:', error);
      this.showStatus('Sign in failed. Please try again.', 'error');
    }
  }

  async getGoogleClientId() {
    // In production, this would be your actual Google Client ID
    // For now, return a placeholder that should be configured
    return 'YOUR_GOOGLE_CLIENT_ID';
  }

  async processText() {
    const textInput = document.getElementById('textInput');
    const text = textInput.value.trim();

    if (!text) {
      this.showStatus('Please enter some text to process', 'error');
      return;
    }

    try {
      this.setButtonLoading('processTextBtn', true);
      this.showStatus('Processing text and extracting events...', 'processing');

      // Send to Chrome extension API endpoint
      const response = await fetch(`${this.apiBaseUrl}/api/extension/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.authToken}`
        },
        body: JSON.stringify({
          text: text,
          user_email: this.user.email,
          source: 'Chrome Extension Text Input'
        })
      });

      const result = await response.json();

      if (response.ok) {
        const totalEvents = result.total_events_extracted || 0;
        const syncedEvents = result.total_events_synced || 0;
        
        this.showStatus(`Success! Extracted ${totalEvents} events, ${syncedEvents} synced to calendar`, 'success');
        textInput.value = ''; // Clear input
      } else {
        this.showStatus(`Error: ${result.error || 'Processing failed'}`, 'error');
      }
    } catch (error) {
      console.error('Text processing error:', error);
      this.showStatus('Failed to process text. Please try again.', 'error');
    } finally {
      this.setButtonLoading('processTextBtn', false);
    }
  }

  async takeScreenshot() {
    try {
      this.setButtonLoading('screenshotBtn', true);
      this.showStatus('Taking screenshot...', 'processing');

      // Capture the active tab
      const tab = await this.getCurrentTab();
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: 'png',
        quality: 90
      });

      // Convert data URL to blob
      const response = await fetch(dataUrl);
      const blob = await response.blob();

      // Send to webhook endpoint with screenshot
      const formData = new FormData();
      formData.append('stripped-text', 'Screenshot taken from Chrome extension');
      formData.append('From', this.user.email);
      formData.append('Subject', 'Chrome Extension Screenshot');
      formData.append('attachment-1', blob, 'screenshot.png');

      this.showStatus('Processing screenshot and extracting events...', 'processing');

      const apiResponse = await fetch(`${this.apiBaseUrl}/api/extension/process`, {
        method: 'POST',
        body: formData,
        headers: {
          'Authorization': `Bearer ${this.authToken}`
        }
      });

      const result = await apiResponse.json();

      if (apiResponse.ok) {
        const totalEvents = result.total_events_extracted || 0;
        const syncedEvents = result.total_events_synced || 0;
        
        this.showStatus(`Success! Extracted ${totalEvents} events from screenshot, ${syncedEvents} synced to calendar`, 'success');
      } else {
        this.showStatus(`Error: ${result.error || 'Screenshot processing failed'}`, 'error');
      }
    } catch (error) {
      console.error('Screenshot error:', error);
      this.showStatus('Failed to process screenshot. Please try again.', 'error');
    } finally {
      this.setButtonLoading('screenshotBtn', false);
    }
  }

  async getCurrentTab() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab;
  }

  showForwardEmailInfo() {
    // Show instructions for email forwarding
    this.showStatus('Forward emails to: calautobot@calautobot.com for automatic processing', 'success');
  }

  openDashboard() {
    chrome.tabs.create({ url: `${this.apiBaseUrl}/dashboard` });
  }

  setButtonLoading(buttonId, loading) {
    const button = document.getElementById(buttonId);
    const buttonText = button.querySelector('.button-text');
    
    if (loading) {
      button.disabled = true;
      buttonText.innerHTML = '<span class="loading"></span>Processing...';
    } else {
      button.disabled = false;
      if (buttonId === 'processTextBtn') {
        buttonText.textContent = 'Extract Events';
      } else if (buttonId === 'screenshotBtn') {
        buttonText.textContent = 'Take Screenshot';
      }
    }
  }

  showStatus(message, type) {
    const statusElement = document.getElementById('statusMessage');
    statusElement.textContent = message;
    statusElement.className = `status ${type}`;
    statusElement.classList.remove('hidden');

    // Auto-hide success messages after 3 seconds
    if (type === 'success') {
      setTimeout(() => {
        statusElement.classList.add('hidden');
      }, 3000);
    }
  }
}

// Initialize popup when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new CalendarAIPopup();
});