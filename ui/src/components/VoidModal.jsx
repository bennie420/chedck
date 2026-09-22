import React, { useState } from 'react';

export default function VoidModal({
  check,
  onClose,
  onConfirmVoid,
  isVoiding,
}) {
  const [reason, setReason] = useState('Damaged physical print');

  if (!check) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    onConfirmVoid(check.serial_number, reason);
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '1.1rem', color: '#fb7185', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line>
            </svg>
            Void Check #{String(check.serial_number).padStart(6, '0')}
          </h3>
          <button
            type="button"
            className="btn-sm btn-secondary"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Are you sure you want to void the check issued to <strong>{check.payee_name}</strong> for <strong>{check.amount_formatted}</strong>?
          This action will be logged in the immutable audit ledger.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label className="input-label">Reason for Void</label>
            <select
              className="input-field"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            >
              <option value="Damaged physical print">Damaged physical print</option>
              <option value="Printer jam during MICR line">Printer jam during MICR line</option>
              <option value="Incorrect payee name or amount">Incorrect payee name or amount</option>
              <option value="Spoiled check stock">Spoiled check stock</option>
              <option value="Lost or stopped payment">Lost or stopped payment</option>
            </select>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
            <button
              type="button"
              className="btn-sm btn-secondary"
              onClick={onClose}
              disabled={isVoiding}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-sm btn-danger"
              disabled={isVoiding}
            >
              {isVoiding ? 'Voiding...' : 'Confirm Void'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
