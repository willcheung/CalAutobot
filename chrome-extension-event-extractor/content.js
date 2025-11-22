// Calendar AI Chrome Extension - Content Script

class CalendarAIContent {
  constructor() {
    this.init();
  }

  init() {
    // Listen for messages from popup or background script
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      this.handleMessage(request, sender, sendResponse);
      return true; // Keep message channel open for async response
    });

    // Add keyboard shortcut listener (Ctrl+Alt+C to extract events)
    document.addEventListener('keydown', (event) => {
      if (event.ctrlKey && event.altKey && event.key === 'c') {
        this.handleKeyboardShortcut();
      }
    });
  }

  async handleMessage(request, sender, sendResponse) {
    try {
      switch (request.action) {
        case 'get_selected_text':
          const selectedText = this.getSelectedText();
          sendResponse({ success: true, text: selectedText });
          break;

        case 'get_page_text':
          const pageText = this.getPageText();
          sendResponse({ success: true, text: pageText });
          break;

        case 'highlight_extracted_events':
          // Future feature: highlight text that was converted to events
          sendResponse({ success: true });
          break;

        default:
          sendResponse({ success: false, error: 'Unknown action' });
      }
    } catch (error) {
      console.error('Content script error:', error);
      sendResponse({ success: false, error: error.message });
    }
  }

  getSelectedText() {
    const selection = window.getSelection();
    return selection.toString().trim();
  }

  getPageText() {
    // Get visible text content from the page
    const textElements = document.querySelectorAll('p, div, span, h1, h2, h3, h4, h5, h6, li, td, th');
    let pageText = '';

    textElements.forEach(element => {
      // Skip hidden elements and scripts
      const style = window.getComputedStyle(element);
      if (style.display !== 'none' && style.visibility !== 'hidden') {
        const text = element.textContent.trim();
        if (text && text.length > 10) { // Only include meaningful text
          pageText += text + '\n';
        }
      }
    });

    return pageText.trim();
  }

  async handleKeyboardShortcut() {
    try {
      const selectedText = this.getSelectedText();

      if (!selectedText) {
        this.showToast('No text selected. Please select some text first.');
        return;
      }

      // Check authentication status
      const authResponse = await chrome.runtime.sendMessage({ action: 'check_auth' });

      if (!authResponse.success || !authResponse.authStatus.isAuthenticated) {
        this.showToast('Please sign in first by clicking the Calendar AI extension icon.');
        return;
      }

      this.showToast('Processing selected text...');

      // Send message to background script to process the text
      const response = await chrome.runtime.sendMessage({
        action: 'process_selected_text',
        text: selectedText
      });

      if (response.success) {
        this.showToast('Events extracted and added to calendar!', 'success');
      } else {
        this.showToast('Failed to process text. Please try again.', 'error');
      }
    } catch (error) {
      console.error('Keyboard shortcut error:', error);
      this.showToast('Error processing text. Please try again.', 'error');
    }
  }

  showToast(message, type = 'info') {
    // Create a toast notification in the page
    const toast = document.createElement('div');
    toast.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
      color: white;
      padding: 12px 20px;
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      z-index: 10000;
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 14px;
      max-width: 300px;
      word-wrap: break-word;
      animation: slideIn 0.3s ease-out;
    `;

    // Add animation styles
    const style = document.createElement('style');
    style.textContent = `
      @keyframes slideIn {
        from {
          transform: translateX(100%);
          opacity: 0;
        }
        to {
          transform: translateX(0);
          opacity: 1;
        }
      }
      @keyframes slideOut {
        from {
          transform: translateX(0);
          opacity: 1;
        }
        to {
          transform: translateX(100%);
          opacity: 0;
        }
      }
    `;

    if (!document.querySelector('#calendar-ai-toast-styles')) {
      style.id = 'calendar-ai-toast-styles';
      document.head.appendChild(style);
    }

    toast.textContent = message;
    document.body.appendChild(toast);

    // Remove toast after 3 seconds
    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-in';
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }, 3000);
  }
}

// Initialize content script
new CalendarAIContent();