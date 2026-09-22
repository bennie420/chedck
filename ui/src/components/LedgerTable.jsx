import React, { useState } from 'react';

export default function LedgerTable({
  checks,
  isLoading,
  onRefresh,
  onOpenVoidModal,
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const filteredChecks = checks.filter((c) => {
    const matchesSearch =
      c.payee_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      String(c.serial_number).includes(searchTerm);

    const matchesStatus =
      statusFilter === 'ALL' ||
      (statusFilter === 'PRINTED' && c.status === 'printed') ||
      (statusFilter === 'VOIDED' && c.status === 'voided');

    return matchesSearch && matchesStatus;
  });

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="6" x2="21" y2="6"></line>
            <line x1="8" y1="12" x2="21" y2="12"></line>
            <line x1="8" y1="18" x2="21" y2="18"></line>
            <line x1="3" y1="6" x2="3.01" y2="6"></line>
            <line x1="3" y1="12" x2="3.01" y2="12"></line>
            <line x1="3" y1="18" x2="3.01" y2="18"></line>
          </svg>
          Check Registry & Positive Pay Audit
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            type="button"
            className="btn-sm btn-secondary"
            onClick={onRefresh}
            disabled={isLoading}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            Refresh
          </button>
        </div>
      </div>

      <div className="panel-body" style={{ padding: '1rem 1.5rem' }}>
        {/* Filters */}
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem' }}>
          <div style={{ flex: 1 }}>
            <input
              type="text"
              className="input-field"
              placeholder="Search by Payee or Serial #..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div style={{ width: '180px' }}>
            <select
              className="input-field"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="ALL">All Statuses</option>
              <option value="PRINTED">Printed / Issued</option>
              <option value="VOIDED">Voided</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="table-container">
          <table className="checks-table">
            <thead>
              <tr>
                <th>Serial #</th>
                <th>Issue Date</th>
                <th>Payee Name</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Positive Pay</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredChecks.length === 0 ? (
                <tr>
                  <td colSpan="7" style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                    No checks found matching filter.
                  </td>
                </tr>
              ) : (
                filteredChecks.map((check) => (
                  <tr key={check.serial_number}>
                    <td>
                      <span className="serial-pill">
                        #{String(check.serial_number).padStart(6, '0')}
                      </span>
                    </td>
                    <td>{check.issue_date}</td>
                    <td style={{ fontWeight: 500, color: '#f1f5f9' }}>{check.payee_name}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{check.amount_formatted}</td>
                    <td>
                      {check.status === 'voided' ? (
                        <span className="badge badge-voided">VOID</span>
                      ) : (
                        <span className="badge badge-printed">ISSUED</span>
                      )}
                    </td>
                    <td>
                      {check.positive_pay_file ? (
                        <span style={{ fontSize: '0.75rem', color: '#94a3b8', fontFamily: 'var(--font-mono)' }}>
                          {check.positive_pay_file}
                        </span>
                      ) : (
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>None</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', gap: '0.5rem' }}>
                        {check.pdf_url && (
                          <a
                            href={check.pdf_url}
                            target="_blank"
                            rel="noreferrer"
                            className="btn-sm btn-secondary"
                          >
                            PDF
                          </a>
                        )}
                        {check.status !== 'voided' && (
                          <button
                            type="button"
                            className="btn-sm btn-danger"
                            onClick={() => onOpenVoidModal(check)}
                          >
                            Void
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
