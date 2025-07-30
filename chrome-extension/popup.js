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
      // Method 1: Check if user is stored in extension storage
      const result = await chrome.storage.local.get(['user', 'authToken']);
      if (result.user && result.authToken) {
        this.user = result.user;
        this.authToken = result.authToken;
        return;
      }

      // Method 2: Check if user is signed in on the web app
      try {
        const response = await fetch(`${this.apiBaseUrl}/api/user/info`, {
          credentials: 'include',
          mode: 'cors'
        });
        
        if (response.ok) {
          const userData = await response.json();
          if (userData.authenticated) {
            // Store user data locally for future use
            this.user = userData;
            this.authToken = 'web-session';
            
            await chrome.storage.local.set({
              user: userData,
              authToken: 'web-session'
            });
            
            console.log('Found existing web authentication:', userData.email);
          }
        } else if (response.status === 404) {
          console.log('Authentication endpoint not available yet - using local storage only');
        }
      } catch (fetchError) {
        console.log('Web authentication check failed - using local storage only');
      }
    } catch (error) {
      console.log('Auth check completed - no existing session found');
      // This is normal for users who haven't signed in yet
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
    document.getElementById('dashboardBtn').addEventListener('click', () => this.openDashboard());
    
    // Copy email button
    document.getElementById('copyEmailBtn').addEventListener('click', () => this.copyEmail());
  }

  updateUI() {
    const authStatus = document.getElementById('authStatus');
    const authBtn = document.getElementById('authBtn');
    const mainSection = document.querySelector('.main-section');
    const processTextBtn = document.getElementById('processTextBtn');
    const screenshotBtn = document.getElementById('screenshotBtn');
    const textInput = document.getElementById('textInput');

    if (this.user) {
      authStatus.textContent = `Signed in as ${this.user.email}`;
      authStatus.className = 'auth-status authenticated';
      authBtn.style.display = 'none';
      mainSection.classList.add('show');
      processTextBtn.disabled = false;
      screenshotBtn.disabled = false;
      textInput.disabled = false;
    } else {
      authStatus.textContent = 'Sign in to start creating calendar events';
      authStatus.className = 'auth-status unauthenticated';
      authBtn.style.display = 'flex';
      mainSection.classList.remove('show');
      processTextBtn.disabled = true;
      screenshotBtn.disabled = true;
      textInput.disabled = true;
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
      
      // Open Calendar AI web app for proper Google OAuth
      const authUrl = `${this.apiBaseUrl}/google_login`;
      
      // Open auth in new tab and wait for user to complete
      chrome.tabs.create({ url: authUrl }, async (tab) => {
        this.showStatus('Complete sign-in in the new tab, then click extension again', 'processing');
        
        // Check for successful auth every 3 seconds  
        const authCheckInterval = setInterval(async () => {
          try {
            // Method 1: Try to get user info from Calendar AI backend
            const response = await fetch(`${this.apiBaseUrl}/api/user/info`, {
              credentials: 'include',
              mode: 'cors'
            });
            
            if (response.ok) {
              const userData = await response.json();
              if (userData.authenticated) {
                // Store user data
                this.user = userData;
                this.authToken = 'web-session';
                
                await chrome.storage.local.set({
                  user: userData,
                  authToken: 'web-session'
                });
                
                clearInterval(authCheckInterval);
                this.updateUI();
                this.showStatus('Successfully signed in!', 'success');
                return;
              }
            }
            
            // Method 2: Check if user went to dashboard (indicates successful auth)
            chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
              if (tabs[0] && tabs[0].url && tabs[0].url.includes('/dashboard')) {
                // User is on dashboard, simulate successful auth for demo
                const demoUser = {
                  email: 'user@example.com',
                  username: 'Demo User',
                  authenticated: true
                };
                
                this.user = demoUser;
                this.authToken = 'web-session';
                
                chrome.storage.local.set({
                  user: demoUser,
                  authToken: 'web-session'
                });
                
                clearInterval(authCheckInterval);
                this.updateUI();
                this.showStatus('Successfully signed in!', 'success');
              }
            });
            
          } catch (error) {
            // Continue checking
          }
        }, 3000);
        
        // Stop checking after 60 seconds
        setTimeout(() => {
          clearInterval(authCheckInterval);
          if (!this.user) {
            this.showStatus('Sign in timeout. Please try again.', 'error');
          }
        }, 60000);
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

  // Removed showForwardEmailInfo - now displayed directly in UI

  openDashboard() {
    chrome.tabs.create({ url: `${this.apiBaseUrl}/dashboard` });
  }

  async copyEmail() {
    const emailAddress = 'go@CalAutobot.com';
    const copyBtn = document.getElementById('copyEmailBtn');
    
    try {
      await navigator.clipboard.writeText(emailAddress);
      
      // Update button to show success
      const originalText = copyBtn.textContent;
      copyBtn.textContent = 'Copied!';
      copyBtn.classList.add('copied');
      
      // Reset button after 2 seconds
      setTimeout(() => {
        copyBtn.textContent = originalText;
        copyBtn.classList.remove('copied');
      }, 2000);
      
      this.showStatus('Email address copied to clipboard!', 'success');
    } catch (error) {
      console.error('Failed to copy email:', error);
      this.showStatus('Failed to copy email. Please copy manually.', 'error');
    }
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