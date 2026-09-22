import React, { useState, useEffect } from 'react';

export default function SettingsModal({ onClose, accountInfo, onSaved }) {
  const acct = accountInfo?.accounts?.[0] || {};

  const [form, setForm] = useState({
    drawer_name: acct.drawer_name || '',
    drawer_address: acct.drawer_address || '',
    drawer_city_state_zip: acct.drawer_city_state_zip || '',
    routing_number: acct.routing_number || '',
    account_number: acct.account_number || '',
    fractional_routing: acct.fractional_routing || '',
  });

  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const handleChange = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setError(null);
    setSuccess(false);
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch('/api/config/account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Failed to save configuration.');
      } else {
        setSuccess(true);
        onSaved && onSaved();
      }
    } catch (err) {
      setError(`Network error: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog settings-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontSize: '1.4rem' }}>⚙️</span>
            <div>
              <h3 className="modal-title" style={{ margin: 0 }}>Account & Routing Settings</h3>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Edits persist to <code>config/account_config.json</code>
              </div>
            </div>
          </div>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body" style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {error && (
            <div style={{
              background: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              color: '#fca5a5',
              padding: '0.6rem 0.85rem',
              borderRadius: '6px',
              fontSize: '0.82rem',
            }}>
              ❌ {error}
            </div>
          )}
          {success && (
            <div style={{
              background: 'rgba(34, 197, 94, 0.12)',
              border: '1px solid rgba(34, 197, 94, 0.4)',
              color: '#86efac',
              padding: '0.6rem 0.85rem',
              borderRadius: '6px',
              fontSize: '0.82rem',
            }}>
              ✅ Account configuration saved successfully. New checks will use the updated values.
            </div>
          )}

          <div className="settings-section-label">Drawer / Company Identity</div>

          <div className="settings-field-row">
            <div className="input-group" style={{ flex: 1 }}>
              <label className="input-label">Drawer Name</label>
              <input
                className="input-field"
                placeholder="Your Company LLC"
                value={form.drawer_name}
                onChange={(e) => handleChange('drawer_name', e.target.value)}
              />
            </div>
          </div>

          <div className="settings-field-row">
            <div className="input-group" style={{ flex: 1 }}>
              <label className="input-label">Street Address</label>
              <input
                className="input-field"
                placeholder="123 Main Street"
                value={form.drawer_address}
                onChange={(e) => handleChange('drawer_address', e.target.value)}
              />
            </div>
            <div className="input-group" style={{ flex: 1 }}>
              <label className="input-label">City, State ZIP</label>
              <input
                className="input-field"
                placeholder="Phoenix, AZ 85001"
                value={form.drawer_city_state_zip}
                onChange={(e) => handleChange('drawer_city_state_zip', e.target.value)}
              />
            </div>
          </div>

          <div className="settings-section-label" style={{ marginTop: '0.5rem' }}>Bank & MICR Credentials</div>

          <div className="settings-field-row">
            <div className="input-group" style={{ flex: 1 }}>
              <label className="input-label">Routing Number (ABA 9-digit)</label>
              <input
                className="input-field"
                placeholder="021000021"
                maxLength={9}
                inputMode="numeric"
                value={form.routing_number}
                onChange={(e) => handleChange('routing_number', e.target.value.replace(/\D/g, ''))}
              />
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '3px' }}>
                Validated via ABA mod-10 check digit on save
              </div>
            </div>
            <div className="input-group" style={{ flex: 1 }}>
              <label className="input-label">Account Number</label>
              <input
                className="input-field"
                placeholder="123456789012"
                maxLength={17}
                inputMode="numeric"
                value={form.account_number}
                onChange={(e) => handleChange('account_number', e.target.value.replace(/\D/g, ''))}
              />
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '3px' }}>
                Digits only, max 17 characters (ANSI X9 On-Us field)
              </div>
            </div>
          </div>

          <div className="input-group">
            <label className="input-label">Fractional Routing (face upper-right)</label>
            <input
              className="input-field"
              placeholder="70-2322/719"
              value={form.fractional_routing}
              onChange={(e) => handleChange('fractional_routing', e.target.value)}
            />
            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '3px' }}>
              Format: <code>prefix-suffix/FRB</code> — obtained from your bank's spec form
            </div>
          </div>

          <div style={{
            background: 'rgba(99, 102, 241, 0.07)',
            border: '1px solid rgba(99, 102, 241, 0.2)',
            borderRadius: '6px',
            padding: '0.6rem 0.85rem',
            fontSize: '0.74rem',
            color: 'var(--text-muted)',
          }}>
            ℹ️ <strong>Important:</strong> Changes to routing and account numbers take effect on the next check preview or print. Ensure your bank has approved the MICR layout before printing live stock.
          </div>
        </div>

        <div className="modal-footer">
          <button
            className="btn-outline"
            onClick={onClose}
            style={{ padding: '0.5rem 1.25rem', fontSize: '0.85rem' }}
          >
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={handleSave}
            disabled={isSaving}
            style={{ padding: '0.5rem 1.5rem', fontSize: '0.85rem' }}
          >
            {isSaving ? 'Saving...' : '💾 Save Account & Routing'}
          </button>
        </div>
      </div>
    </div>
  );
}
