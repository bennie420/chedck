import React, { useState } from 'react';

export default function CheckForm({
  formData,
  setFormData,
  previewData,
  nextSerial,
  onPrint,
  isPrinting,
}) {
  const [showClaimDetails, setShowClaimDetails] = useState(true);
  const [showPayeeAddress, setShowPayeeAddress] = useState(false);
  const [showAccountFields, setShowAccountFields] = useState(false);

  const handleChange = (field, value) => {
    setFormData((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const handleRemittanceField = (field, value) => {
    setFormData((prev) => ({
      ...prev,
      remittance_data: {
        ...prev.remittance_data,
        [field]: value,
      },
    }));
  };

  const handleClaimMeta = (index, value) => {
    setFormData((prev) => {
      const updated = [...(prev.remittance_data?.claim_fields || [])];
      updated[index] = { ...updated[index], value };
      return {
        ...prev,
        remittance_data: {
          ...prev.remittance_data,
          claim_fields: updated,
        },
      };
    });
  };

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
            <polyline points="10 9 9 9 8 9"></polyline>
          </svg>
          Issue Payment Request
        </div>
      </div>

      <div className="panel-body">
        {/* Layout Selection */}
        <div className="form-section">
          <label className="section-label">Check Format & Design</label>
          <div className="layout-selector">
            <button
              type="button"
              className={`layout-pill ${formData.layout === 'personal' || (!formData.layout && formData.layout !== 'business' && formData.layout !== 'remittance') ? 'active' : ''}`}
              onClick={() => {
                handleChange('layout', 'personal');
                if (nextSerial) handleChange('check_number', nextSerial);
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="6" width="18" height="12" rx="2"></rect>
                <circle cx="8" cy="12" r="1.5"></circle>
              </svg>
              Personal (BofA)
            </button>
            <button
              type="button"
              className={`layout-pill ${formData.layout === 'business' ? 'active' : ''}`}
              onClick={() => {
                handleChange('layout', 'business');
                if (nextSerial) handleChange('check_number', nextSerial);
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="5" width="20" height="14" rx="2"></rect>
                <line x1="2" y1="10" x2="22" y2="10"></line>
              </svg>
              Business (BofA)
            </button>
            <button
              type="button"
              className={`layout-pill ${formData.layout === 'remittance' ? 'active' : ''}`}
              onClick={() => {
                handleChange('layout', 'remittance');
                if (formData.check_number === 1001 || formData.check_number === 1002) {
                  handleChange('check_number', 39254225);
                }
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2"></rect>
                <line x1="3" y1="9" x2="21" y2="9"></line>
                <line x1="9" y1="21" x2="9" y2="9"></line>
              </svg>
              USAA Remittance
            </button>
          </div>

          {/* Page Format & Options */}
          <div className="input-row" style={{ marginBottom: '1rem' }}>
            <div>
              <label className="input-label">Document Size</label>
              <select
                className="input-field"
                value={formData.page_format}
                onChange={(e) => handleChange('page_format', e.target.value)}
              >
                {formData.layout === 'personal' ? (
                  <>
                    <option value="check_only">Personal Check (6.0" × 2 3/5")</option>
                    <option value="voucher_sheet">Personal Voucher Sheet (8.5" × 11.0")</option>
                  </>
                ) : formData.layout === 'business' ? (
                  <>
                    <option value="check_only">Business Check (8.5" × 3.5")</option>
                    <option value="voucher_sheet">Business Voucher Sheet (8.5" × 11.0")</option>
                  </>
                ) : (
                  <>
                    <option value="check_only">Check Only (8.5" × 3.5")</option>
                    <option value="voucher_sheet">Voucher Sheet (8.5" × 11.0")</option>
                  </>
                )}
              </select>
            </div>
            {formData.layout === 'remittance' ? (
              <div>
                <label className="input-label">Authorized Signer</label>
                <input
                  type="text"
                  className="input-field"
                  value={formData.signature_name}
                  onChange={(e) => handleChange('signature_name', e.target.value)}
                />
              </div>
            ) : (
              <div>
                <div className="input-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>Bank MICR Routing / Account</span>
                  <button
                    type="button"
                    className="tag-btn"
                    onClick={() => setShowAccountFields(!showAccountFields)}
                  >
                    {showAccountFields ? 'Hide Details' : 'Edit Routing & Acct'}
                  </button>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', paddingTop: '6px' }}>
                  {formData.routing_number && formData.account_number
                    ? `Routing: ${formData.routing_number} · Acct: ${formData.account_number}`
                    : 'Using Bank of America default profile (111000012)'}
                </div>
              </div>
            )}
          </div>

          {/* Personal / Business Check Routing & Account Number Editing */}
          {formData.layout !== 'remittance' && showAccountFields && (
            <div className="accordion-body" style={{ marginBottom: '1rem', background: 'rgba(99, 102, 241, 0.05)', borderColor: 'rgba(99, 102, 241, 0.25)' }}>
              <div style={{ fontSize: '0.72rem', fontWeight: 600, color: '#a5b4fc', marginBottom: '8px', textTransform: 'uppercase' }}>
                Bank MICR Line Overrides (BofA Specs)
              </div>
              <div className="input-row">
                <div className="input-group">
                  <label className="input-label">Routing Number (9 Digits)</label>
                  <input
                    type="text"
                    maxLength={9}
                    inputMode="numeric"
                    className="input-field"
                    placeholder="111000012"
                    value={formData.routing_number || ''}
                    onChange={(e) => handleChange('routing_number', e.target.value.replace(/\D/g, ''))}
                  />
                </div>
                <div className="input-group">
                  <label className="input-label">Account Number</label>
                  <input
                    type="text"
                    maxLength={17}
                    inputMode="numeric"
                    className="input-field"
                    placeholder="123456789012"
                    value={formData.account_number || ''}
                    onChange={(e) => handleChange('account_number', e.target.value.replace(/\D/g, ''))}
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Payment Essentials */}
        <div className="form-section">
          <label className="section-label">Payment Essentials</label>

          {/* Check Serial Number & Date */}
          <div className="input-row" style={{ marginBottom: '1rem' }}>
            <div className="input-group">
              <div className="input-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>Check Number</span>
                {nextSerial && (
                  <button
                    type="button"
                    className="tag-btn"
                    title={`Set to next sequential check serial from ledger (#${nextSerial})`}
                    onClick={() => handleChange('check_number', nextSerial)}
                  >
                    Auto #{nextSerial}
                  </button>
                )}
              </div>
              <input
                type="number"
                min="1"
                max="9999999999"
                className="input-field"
                placeholder="e.g. 1001 or 39254225"
                value={formData.check_number ?? ''}
                onChange={(e) => {
                  const val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
                  handleChange('check_number', val);
                }}
              />
              <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '3px', display: 'block' }}>
                {formData.layout === 'personal'
                  ? `On-Us Serial Field: ⑈${previewData?.serial_formatted || formData.check_number || '1001'}⑈`
                  : `Aux On-Us: ⑈${previewData?.serial_formatted || formData.check_number || '000000'}⑈`}
              </span>
            </div>

            <div className="input-group">
              <label className="input-label">Issue Date</label>
              <input
                type="date"
                className="input-field"
                value={formData.issue_date}
                onChange={(e) => handleChange('issue_date', e.target.value)}
              />
            </div>
          </div>

          {/* Payee Name & Optional Address */}
          <div className="input-group">
            <div className="input-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span>Payee (Order Of)</span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginLeft: '6px' }}>ANSI Legal Name</span>
              </div>
              <button
                type="button"
                className="tag-btn"
                onClick={() => setShowPayeeAddress(!showPayeeAddress)}
              >
                {showPayeeAddress ? 'Hide Address' : '+ Add Address'}
              </button>
            </div>
            <input
              type="text"
              className="input-field"
              placeholder="e.g. BRANDON BACH"
              value={formData.payee}
              onChange={(e) => handleChange('payee', e.target.value)}
            />
          </div>

          {/* Optional Payee Address Fields */}
          {showPayeeAddress && (
            <div className="accordion-body" style={{ marginBottom: '1rem', background: 'rgba(255, 255, 255, 0.02)' }}>
              <div style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase' }}>
                Optional Payee Remittance Address
              </div>
              <div className="input-row" style={{ marginBottom: '0.5rem' }}>
                <div className="input-group">
                  <label className="input-label">Street Address</label>
                  <input
                    type="text"
                    className="input-field"
                    placeholder="e.g. 742 Evergreen Terrace"
                    value={formData.payee_address || ''}
                    onChange={(e) => handleChange('payee_address', e.target.value)}
                  />
                </div>
              </div>
              <div className="input-row">
                <div className="input-group">
                  <label className="input-label">City, State ZIP</label>
                  <input
                    type="text"
                    className="input-field"
                    placeholder="e.g. Springfield, OR 97477"
                    value={formData.payee_city_state_zip || ''}
                    onChange={(e) => handleChange('payee_city_state_zip', e.target.value)}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Payment Amount */}
          <div className="input-group">
            <label className="input-label">Payment Amount ($)</label>
            <div className="amount-wrapper">
              <span className="currency-symbol">$</span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className="input-field amount-field"
                placeholder="5000.00"
                value={formData.amount_dollars}
                onChange={(e) => handleChange('amount_dollars', parseFloat(e.target.value) || 0)}
              />
            </div>
          </div>

          {/* Legal Words Live Wording Preview */}
          {previewData?.legal_text && (
            <div className="legal-words-box">
              <div style={{ color: 'var(--text-muted)', fontSize: '0.68rem', marginBottom: '2px', textTransform: 'uppercase' }}>
                ANSI Legal Wording Line:
              </div>
              <strong>{previewData.legal_text}</strong>
            </div>
          )}
        </div>

        {/* Memo */}
        <div className="input-group">
          <label className="input-label">Memo / Description</label>
          <input
            type="text"
            className="input-field"
            placeholder="e.g. Medical Payments to Others coverage"
            value={formData.memo}
            onChange={(e) => handleChange('memo', e.target.value)}
          />
        </div>

        {formData.layout === 'standard' && (
          <div className="form-section">
            <label className="section-label">Standard Check Banking & Drawer Overrides (Optional)</label>

            <div className="input-row" style={{ marginBottom: '0.75rem' }}>
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">Routing Number (ABA)</label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="Optional: 9 digits"
                  maxLength={9}
                  inputMode="numeric"
                  value={formData.routing_number || ''}
                  onChange={(e) => handleChange('routing_number', e.target.value.replace(/\D/g, ''))}
                />
              </div>
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">Account Number</label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="Optional: digits only"
                  inputMode="numeric"
                  value={formData.account_number || ''}
                  onChange={(e) => handleChange('account_number', e.target.value.replace(/\D/g, ''))}
                />
              </div>
            </div>

            <div className="input-group" style={{ marginBottom: '0.75rem' }}>
              <label className="input-label">Drawer Name (optional override)</label>
              <input
                type="text"
                className="input-field"
                placeholder="Optional drawer name override"
                value={formData.drawer_name || ''}
                onChange={(e) => handleChange('drawer_name', e.target.value)}
              />
            </div>

            <div className="input-row" style={{ marginBottom: '0.75rem' }}>
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">Address Line 1 (optional)</label>
                <input
                  type="text"
                  className="input-field"
                  value={formData.drawer_address_line1 || ''}
                  onChange={(e) => handleChange('drawer_address_line1', e.target.value)}
                />
              </div>
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">Address Line 2 (optional)</label>
                <input
                  type="text"
                  className="input-field"
                  value={formData.drawer_address_line2 || ''}
                  onChange={(e) => handleChange('drawer_address_line2', e.target.value)}
                />
              </div>
            </div>

            <div className="input-row">
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">City (optional)</label>
                <input
                  type="text"
                  className="input-field"
                  value={formData.drawer_city || ''}
                  onChange={(e) => handleChange('drawer_city', e.target.value)}
                />
              </div>
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">State / Province (optional)</label>
                <input
                  type="text"
                  className="input-field"
                  value={formData.drawer_state_province || ''}
                  onChange={(e) => handleChange('drawer_state_province', e.target.value)}
                />
              </div>
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">Postal Code (optional)</label>
                <input
                  type="text"
                  className="input-field"
                  value={formData.drawer_postal_code || ''}
                  onChange={(e) => handleChange('drawer_postal_code', e.target.value)}
                />
              </div>
              <div className="input-group" style={{ flex: 1 }}>
                <label className="input-label">Country (optional)</label>
                <input
                  type="text"
                  className="input-field"
                  value={formData.drawer_country || ''}
                  onChange={(e) => handleChange('drawer_country', e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {/* Remittance Claim Metadata (if remittance layout) */}
        {formData.layout === 'remittance' && (
          <div className="form-section">
            <button
              type="button"
              className="accordion-toggle"
              onClick={() => setShowClaimDetails(!showClaimDetails)}
            >
              <span>USAA Claim & Policy Metadata</span>
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                style={{ transform: showClaimDetails ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
              >
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>

            {showClaimDetails && (
              <div className="accordion-body">
                <div className="input-row" style={{ marginBottom: '0.75rem' }}>
                  <div>
                    <label className="input-label">USAA #</label>
                    <input
                      type="text"
                      className="input-field"
                      value={formData.remittance_data?.claim_fields?.[0]?.value || ''}
                      onChange={(e) => handleClaimMeta(0, e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="input-label">Loss Report #</label>
                    <input
                      type="text"
                      className="input-field"
                      value={formData.remittance_data?.claim_fields?.[1]?.value || ''}
                      onChange={(e) => handleClaimMeta(1, e.target.value)}
                    />
                  </div>
                </div>

                <div className="input-row" style={{ marginBottom: '0.75rem' }}>
                  <div>
                    <label className="input-label">Loss Date</label>
                    <input
                      type="date"
                      className="input-field"
                      value={formData.remittance_data?.claim_fields?.[2]?.value || ''}
                      onChange={(e) => handleClaimMeta(2, e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="input-label">Policyholder</label>
                    <input
                      type="text"
                      className="input-field"
                      value={formData.remittance_data?.claim_fields?.[3]?.value || ''}
                      onChange={(e) => handleClaimMeta(3, e.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <label className="input-label">Payment Explanation</label>
                  <input
                    type="text"
                    className="input-field"
                    value={formData.remittance_data?.payment_explanation_text || ''}
                    onChange={(e) => handleRemittanceField('payment_explanation_text', e.target.value)}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Print Mode Toggle */}
        <div className="form-section" style={{ marginBottom: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--text-primary)', marginBottom: '2px' }}>
                Outline Only (Check Stock)
              </div>
              <div style={{ fontSize: '0.70rem', color: 'var(--text-muted)' }}>
                Suppress background — print on pre-printed check stock
              </div>
            </div>
            <label className="toggle-switch" style={{ flexShrink: 0 }}>
              <input
                type="checkbox"
                checked={!!formData.outline_only}
                onChange={(e) => handleChange('outline_only', e.target.checked)}
              />
              <span className="toggle-slider" />
            </label>
          </div>
        </div>

        {/* Non-Liability Pre-issuance Notice */}
        <div className="form-disclaimer-notice" style={{
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.25)',
          borderRadius: 'var(--radius-sm)',
          padding: '0.6rem 0.85rem',
          fontSize: '0.74rem',
          lineHeight: '1.4',
          color: '#fca5a5',
          marginBottom: '1rem'
        }}>
          <strong>⚠️ Developer Non-Liability Notice:</strong> This software is provided &quot;AS IS&quot;. The software developer disclaims all legal and financial liability for check printing, bank clearance, or negotiation. Operator assumes 100% legal responsibility under UCC Articles 3 &amp; 4.
        </div>

        {/* Submit Print Button */}
        <button
          type="button"
          className="btn-primary"
          onClick={onPrint}
          disabled={isPrinting || !formData.payee || formData.amount_dollars <= 0}
        >
          {isPrinting ? (
            <>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="spinner">
                <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="10"></circle>
              </svg>
              Allocating & Rendering...
            </>
          ) : (
            <>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="6 9 6 2 18 2 18 9"></polyline>
                <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
                <rect x="6" y="14" width="12" height="8"></rect>
              </svg>
              Print & Issue Check
            </>
          )}
        </button>
      </div>
    </div>
  );
}
