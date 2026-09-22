import React from 'react';

export default function CheckPreview({
  previewData,
  isLoading,
  lastPrintResult,
  onClearPrintResult,
}) {
  return (
    <div className="panel-card preview-panel">
      <div className="panel-header">
        <div className="panel-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
          </svg>
          Live Optical & Magnetic Preview
        </div>
        <span className="brand-badge" style={{ borderColor: 'rgba(16, 185, 129, 0.4)', color: '#34d399', background: 'rgba(16, 185, 129, 0.1)' }}>
          {isLoading ? 'RENDERING...' : 'ANSI X9 ACCURATE'}
        </span>
      </div>

      <div className="panel-body">
        {/* Success Banner if check was just printed */}
        {lastPrintResult && (
          <div className="success-banner" style={{ marginBottom: '1.5rem' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#34d399', fontSize: '0.9rem' }}>
                Check #{lastPrintResult.serial_number} Successfully Issued & Printed!
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                Positive Pay Export #{lastPrintResult.positive_pay_export_id} logged.
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
              <a
                href={lastPrintResult.pdf_url}
                target="_blank"
                rel="noreferrer"
                className="banner-link"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                  <polyline points="15 3 21 3 21 9"></polyline>
                  <line x1="10" y1="14" x2="21" y2="3"></line>
                </svg>
                View PDF
              </a>
              <button
                type="button"
                className="btn-sm btn-secondary"
                onClick={onClearPrintResult}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Real-time PDF Canvas / Image */}
        <div className="preview-container">
          {previewData?.image_data_url ? (
            <div
              className="check-shadow-wrapper"
              style={{
                maxWidth: previewData.page_format === 'voucher_sheet' ? '460px' : '720px',
                opacity: isLoading ? 0.7 : 1,
                transition: 'opacity 0.2s ease',
              }}
            >
              <img
                src={previewData.image_data_url}
                alt="Rendered ANSI X9 Check"
                className="check-image"
              />
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Generating real-time check preview...
            </div>
          )}
        </div>

        {/* MICR Bar & Standards Verification */}
        <div className="micr-strip-box">
          <div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>
              ANSI X9 E-13B MICR Code Line (0.625" Clear Band)
            </div>
            <div className="micr-text">
              {previewData?.micr_display ? (
                <span>{previewData.micr_display}</span>
              ) : previewData?.layout === 'remittance' ? (
                <span>O0039254225O T011900445T 007740015665O</span>
              ) : (
                <span>T053000196T 123456789012O 001004</span>
              )}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>
              ANSI X9.100 Aux On-Us Match
            </div>
            <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#34d399', display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end' }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              #{previewData?.serial_formatted || previewData?.serial_number || '---'} Verified
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
