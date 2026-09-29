/* Escape untrusted text before inserting it into an HTML fragment. */
window.AppDanzaUI = Object.freeze({
    text(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, character => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[character]));
    },
    localUrl(value) {
        try {
            const url = new URL(value, window.location.origin);
            return url.origin === window.location.origin ? this.text(url.pathname + url.search) : '#';
        } catch (_) { return '#'; }
    }
});
