if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch(error => console.debug('PWA cache unavailable', error));
}
