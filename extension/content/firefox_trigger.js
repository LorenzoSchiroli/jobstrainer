(function () {
  if (document.getElementById('tailorer-ff-trigger')) return;

  const btn = document.createElement('button');
  btn.id = 'tailorer-ff-trigger';
  Object.assign(btn.style, {
    position: 'fixed',
    bottom: '24px',
    right: '24px',
    zIndex: '2147483647',
    background: '#2563eb',
    color: '#fff',
    border: 'none',
    borderRadius: '20px',
    padding: '9px 16px',
    fontSize: '13px',
    fontFamily: 'system-ui, sans-serif',
    fontWeight: '600',
    cursor: 'pointer',
    boxShadow: '0 2px 12px rgba(0,0,0,0.35)',
  });
  btn.textContent = '⚡ Open Tailorer — click toolbar icon';
  btn.addEventListener('click', btn.remove.bind(btn));
  document.body.appendChild(btn);
})();
