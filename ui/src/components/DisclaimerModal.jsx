import React from 'react';

export default function DisclaimerModal({ onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog disclaimer-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontSize: '1.4rem' }}>⚖️</span>
            <div>
              <h3 className="modal-title" style={{ margin: 0 }}>Legal Disclaimer & Limitation of Developer Liability</h3>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Strict Notice & Terms of Use</div>
            </div>
          </div>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body legal-disclaimer-content" style={{ maxHeight: '60vh', overflowY: 'auto', fontSize: '0.82rem', lineHeight: '1.6', color: 'var(--text-secondary)' }}>
          <div className="alert-warning" style={{ background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.35)', padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1rem', color: '#fca5a5' }}>
            <strong>CRITICAL LEGAL NOTICE:</strong> By accessing, operating, modifying, or using this software, you explicitly agree that the developer, creators, and contributors assume <strong>ZERO LEGAL, FINANCIAL, OR CIVIL LIABILITY</strong> for any checks issued, printed, negotiated, or cleared using this application.
          </div>

          <h4 style={{ color: '#fff', margin: '1rem 0 0.25rem 0' }}>1. "AS-IS" Warranty Disclaimer</h4>
          <p>
            THE SOFTWARE IS PROVIDED &quot;AS IS&quot; AND &quot;AS AVAILABLE&quot;, WITHOUT WARRANTY OF ANY KIND, EXPRESS, IMPLIED, STATUTORY, OR OTHERWISE, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, ACCURACY, TITLE, AND NON-INFRINGEMENT. THE DEVELOPER DOES NOT WARRANT THAT THE SOFTWARE WILL BE UNINTERRUPTED, ERROR-FREE, SECURE, OR ACCURATE ACCORDING TO SPECIFIC BANK MICR REQUIREMENTS.
          </p>

          <h4 style={{ color: '#fff', margin: '1rem 0 0.25rem 0' }}>2. Absolute Limitation of Developer Liability</h4>
          <p>
            TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT SHALL THE DEVELOPER, AUTHORS, OR AFFILIATED PARTIES BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, PUNITIVE, OR EXEMPLARY DAMAGES, INCLUDING BUT NOT LIMITED TO:
          </p>
          <ul style={{ paddingLeft: '1.25rem', marginTop: '0.25rem' }}>
            <li>Loss of funds, capital, profits, revenue, or business opportunities.</li>
            <li>Bank fees, return check charges, NSF fees, or overdraft penalties.</li>
            <li>Bank rejections, MICR code-line read failures, or Check 21 image capture rejections.</li>
            <li>Civil or criminal disputes, check fraud allegations, or unauthorized check alterations.</li>
            <li>Failure to upload or match Positive Pay issue files with paying banks.</li>
          </ul>

          <h4 style={{ color: '#fff', margin: '1rem 0 0.25rem 0' }}>3. Operator Assumption of 100% Responsibility</h4>
          <p>
            The operator/user acknowledges and warrants that they have full lawful authorization to draw against the configured account. The operator bears sole, unconditional responsibility for verifying ANSI X9.100 physical compliance, obtaining written bank authorization before printing live stock, and maintaining physical security over checks, MICR toner, and signature materials.
          </p>

          <h4 style={{ color: '#fff', margin: '1rem 0 0.25rem 0' }}>4. No Banking or Legal Relationship</h4>
          <p>
            The developer is an independent software creator and is not a bank, money transmitter, or legal fiduciary. Any financial institution names or logos (e.g., USAA, JPMorgan Chase, Bank of America) displayed in templates are for sample layout positioning and formatting demonstrations only.
          </p>
        </div>

        <div className="modal-footer" style={{ borderTop: '1px solid var(--border-subtle)', padding: '1rem 1.5rem', display: 'flex', justifyContent: 'flex-end' }}>
          <button className="btn-primary" onClick={onClose} style={{ padding: '0.5rem 1.5rem', fontSize: '0.85rem' }}>
            I Understand & Accept Full Responsibility
          </button>
        </div>
      </div>
    </div>
  );
}
