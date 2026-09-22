import React from 'react';

export default function Header({ activeTab, setActiveTab, accountInfo, onRefresh, onOpenDisclaimer, onOpenSettings }) {
  const isLive = accountInfo?.production_lock === 'LIVE';

  return (
    <header className="app-header">
      <div className="header-brand">
        <div className="brand-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="4" width="20" height="16" rx="3"></rect>
            <line x1="2" y1="10" x2="22" y2="10"></line>
            <path d="M6 15h2"></path>
            <path d="M12 15h6"></path>
          </svg>
        </div>
        <div>
          <div className="brand-title">
            Check Engine Studio
            <span className="brand-badge">ANSI X9.100</span>
          </div>
        </div>
      </div>

      <nav className="header-nav">
        <button
          className={`nav-tab ${activeTab === 'studio' ? 'active' : ''}`}
          onClick={() => setActiveTab('studio')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
          </svg>
          Check Studio
        </button>

        <button
          className={`nav-tab ${activeTab === 'ledger' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('ledger');
            onRefresh && onRefresh();
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="6" x2="21" y2="6"></line>
            <line x1="8" y1="12" x2="21" y2="12"></line>
            <line x1="8" y1="18" x2="21" y2="18"></line>
            <line x1="3" y1="6" x2="3.01" y2="6"></line>
            <line x1="3" y1="12" x2="3.01" y2="12"></line>
            <line x1="3" y1="18" x2="3.01" y2="18"></line>
          </svg>
          Issued Ledger
        </button>
      </nav>

      <div className="header-status">
        <button
          className="btn-disclaimer-header"
          onClick={onOpenDisclaimer}
          title="View Developer Liability Disclaimer"
          style={{
            background: 'rgba(239, 68, 68, 0.12)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#fca5a5',
            padding: '4px 10px',
            borderRadius: '6px',
            fontSize: '0.75rem',
            fontWeight: '600',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            cursor: 'pointer'
          }}
        >
          <span>⚖️</span>
          <span>Disclaimer</span>
        </button>

        <button
          onClick={onOpenSettings}
          title="Account & Routing Settings"
          style={{
            background: 'rgba(99, 102, 241, 0.12)',
            border: '1px solid rgba(99, 102, 241, 0.3)',
            color: '#a5b4fc',
            padding: '4px 10px',
            borderRadius: '6px',
            fontSize: '0.75rem',
            fontWeight: '600',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            cursor: 'pointer'
          }}
        >
          <span>⚙️</span>
          <span>Account &amp; Routing</span>
        </button>

        <div className={`status-badge ${isLive ? 'live' : 'test'}`}>
          <span className="status-dot"></span>
          {isLive ? 'LIVE MODE' : 'TEST MODE (PDF Only)'}
        </div>
      </div>
    </header>
  );
}
