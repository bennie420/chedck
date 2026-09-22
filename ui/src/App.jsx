import React, { useState, useEffect, useCallback } from 'react';
import './App.css';
import Header from './components/Header';
import CheckForm from './components/CheckForm';
import CheckPreview from './components/CheckPreview';
import LedgerTable from './components/LedgerTable';
import VoidModal from './components/VoidModal';

export default function App() {
  const [activeTab, setActiveTab] = useState('studio');
  const [accountInfo, setAccountInfo] = useState(null);
  const [checks, setChecks] = useState([]);
  const [isChecksLoading, setIsChecksLoading] = useState(false);

  // Form State
  const [formData, setFormData] = useState({
    account_id: 'ACC-001',
    check_number: 39254225,
    payee: 'BRANDON BACH',
    amount_dollars: 5000.0,
    issue_date: new Date().toISOString().split('T')[0],
    memo: 'Medical Payments to Others coverage',
    layout: 'remittance', // 'remittance' or 'standard'
    page_format: 'check_only', // 'check_only' or 'voucher_sheet'
    signature_name: 'Minnie Hinds',
    draw_signature: true,
    remittance_data: null,
    outline_only: false,
  });

  // Next sequential serial from DB
  const [nextSerial, setNextSerial] = useState(null);

  // Preview & Printing State
  const [previewData, setPreviewData] = useState(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isPrinting, setIsPrinting] = useState(false);
  const [lastPrintResult, setLastPrintResult] = useState(null);

  // Void modal state
  const [voidCheckTarget, setVoidCheckTarget] = useState(null);
  const [isVoiding, setIsVoiding] = useState(false);

  const fetchNextSerial = useCallback(() => {
    fetch('/api/checks/next-serial')
      .then((res) => res.json())
      .then((data) => {
        if (data.next_serial) {
          setNextSerial(data.next_serial);
        }
      })
      .catch((err) => console.error('Failed to load next serial:', err));
  }, []);

  // 1. Initial Load: Accounts, Remittance Template, Checks, Next Serial
  useEffect(() => {
    fetch('/api/accounts')
      .then((res) => res.json())
      .then((data) => setAccountInfo(data))
      .catch((err) => console.error('Failed to load accounts:', err));

    fetch('/api/templates/remittance')
      .then((res) => res.json())
      .then((data) => {
        setFormData((prev) => ({
          ...prev,
          remittance_data: data,
        }));
      })
      .catch((err) => console.error('Failed to load remittance template:', err));

    fetchNextSerial();
    loadChecks();
  }, [fetchNextSerial]);

  // 2. Load Check History
  const loadChecks = () => {
    setIsChecksLoading(true);
    fetch('/api/checks')
      .then((res) => res.json())
      .then((data) => setChecks(data.checks || []))
      .catch((err) => console.error('Failed to load checks:', err))
      .finally(() => setIsChecksLoading(false));
  };

  // 3. Debounced Live Preview Generator
  useEffect(() => {
    if (!formData.payee || formData.amount_dollars <= 0) return;

    const timer = setTimeout(() => {
      setIsPreviewLoading(true);
      fetch('/api/checks/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      })
        .then((res) => {
          if (!res.ok) throw new Error('Preview error');
          return res.json();
        })
        .then((data) => {
          setPreviewData(data);
        })
        .catch((err) => console.error('Preview failed:', err))
        .finally(() => setIsPreviewLoading(false));
    }, 280);

    return () => clearTimeout(timer);
  }, [
    formData.check_number,
    formData.payee,
    formData.amount_dollars,
    formData.issue_date,
    formData.memo,
    formData.layout,
    formData.page_format,
    formData.signature_name,
    formData.remittance_data,
    formData.outline_only,
  ]);

  // 4. Print Check Execution
  const handlePrint = async () => {
    setIsPrinting(true);
    try {
      const res = await fetch('/api/checks/print', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(`Issuance failed: ${err.detail || 'Unknown error'}`);
        return;
      }

      const result = await res.json();
      setLastPrintResult(result);
      loadChecks(); // Refresh registry
      fetchNextSerial(); // Refresh sequence counter
    } catch (err) {
      alert(`Issuance error: ${err.message}`);
    } finally {
      setIsPrinting(false);
    }
  };

  // 5. Void Check Execution
  const handleConfirmVoid = async (serial, reason) => {
    setIsVoiding(true);
    try {
      const res = await fetch(`/api/checks/${serial}/void`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(`Voiding failed: ${err.detail || 'Unknown error'}`);
        return;
      }

      setVoidCheckTarget(null);
      loadChecks();
    } catch (err) {
      alert(`Voiding error: ${err.message}`);
    } finally {
      setIsVoiding(false);
    }
  };

  return (
    <div className="app-container">
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        accountInfo={accountInfo}
        onRefresh={loadChecks}
      />

      <main className="app-content">
        {activeTab === 'studio' ? (
          <div className="studio-grid">
            <CheckForm
              formData={formData}
              setFormData={setFormData}
              previewData={previewData}
              nextSerial={nextSerial}
              onPrint={handlePrint}
              isPrinting={isPrinting}
            />

            <CheckPreview
              previewData={previewData}
              isLoading={isPreviewLoading}
              lastPrintResult={lastPrintResult}
              onClearPrintResult={() => setLastPrintResult(null)}
            />
          </div>
        ) : (
          <LedgerTable
            checks={checks}
            isLoading={isChecksLoading}
            onRefresh={loadChecks}
            onOpenVoidModal={(check) => setVoidCheckTarget(check)}
          />
        )}
      </main>

      {/* Void Confirmation Modal */}
      {voidCheckTarget && (
        <VoidModal
          check={voidCheckTarget}
          onClose={() => setVoidCheckTarget(null)}
          onConfirmVoid={handleConfirmVoid}
          isVoiding={isVoiding}
        />
      )}
    </div>
  );
}
